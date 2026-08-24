"""Two-stage, one-time authority for applying Sydney task suggestions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.command import CRMTask
from models.gmail_task_intake import CRMTaskSuggestion
from models.sydney_tasks import CRMTaskSuggestionEvent, TaskSuggestionApprovalNonce
from services.crm_task_service import (
    CreateTaskCommand,
    TaskActor,
    TaskCommandValidationError,
    TaskContactNotFound,
    TaskCreationStateError,
    TaskIdempotencyConflict,
    TaskSource,
    TaskSourceConflict,
    crm_task_service,
)
from services.crm_task_suggestion_service import (
    CRMTaskSuggestionAuthorityError,
    CRMTaskSuggestionService,
    canonical_task_payload_hash,
)
from services.integration_advisory_locks import transaction_advisory_lock


_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")


class TaskSuggestionApprovalError(RuntimeError):
    def __init__(self, category: str, *, status_code: int = 409) -> None:
        super().__init__(category)
        self.category = category
        self.status_code = status_code
        self.__cause__ = None
        self.__context__ = None


@dataclass(frozen=True, slots=True)
class IssuedApproval:
    token: str
    nonce: TaskSuggestionApprovalNonce


@dataclass(frozen=True, slots=True)
class AppliedSuggestion:
    suggestion: CRMTaskSuggestion
    task: CRMTask
    request_id: UUID
    replayed: bool


def _error(category: str, status_code: int = 409) -> TaskSuggestionApprovalError:
    return TaskSuggestionApprovalError(category, status_code=status_code)


def parse_approval_token(value: object) -> str:
    """Reject malformed or non-canonical tokens before any database lookup."""
    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise _error("approval_token_invalid", 422)
    try:
        raw = base64.urlsafe_b64decode(value + "=")
        canonical = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    except (UnicodeEncodeError, ValueError):
        raise _error("approval_token_invalid", 422) from None
    if len(raw) != 32 or canonical != value:
        raise _error("approval_token_invalid", 422)
    return value


def approval_token_hash(value: object) -> bytes:
    token = parse_approval_token(value)
    return hashlib.sha256(token.encode("ascii")).digest()


def _new_token() -> str:
    return parse_approval_token(secrets.token_urlsafe(32))


def _payload_hash(suggestion: CRMTaskSuggestion) -> str:
    return canonical_task_payload_hash(
        title=suggestion.title,
        description=suggestion.description,
        priority=suggestion.priority,
        due_at=suggestion.due_at,
        contact_id=suggestion.contact_id,
        status=suggestion.task_status,
    )


def _assert_current(
    suggestion: CRMTaskSuggestion,
    *,
    expected_version: int,
    expected_payload_hash: str,
    require_eligible: bool = True,
) -> None:
    if not CRMTaskSuggestionService.is_current(
        suggestion,
        expected_version=expected_version,
        expected_payload_hash=expected_payload_hash,
    ):
        raise _error("suggestion_stale")
    if not hmac.compare_digest(suggestion.payload_hash, _payload_hash(suggestion)):
        raise _error("suggestion_payload_corrupt")
    if require_eligible and not CRMTaskSuggestionService.approval_eligible(suggestion):
        raise _error("suggestion_blocked")


async def _locked_suggestion(
    session: AsyncSession,
    suggestion_id: UUID,
) -> CRMTaskSuggestion:
    authority = (
        await session.execute(
            select(
                CRMTaskSuggestion.source_type,
                CRMTaskSuggestion.gmail_account_id,
                CRMTaskSuggestion.gmail_thread_id,
            ).where(CRMTaskSuggestion.id == suggestion_id)
        )
    ).one_or_none()
    if authority is None:
        raise _error("suggestion_not_found", 404)
    if authority.source_type == "gmail_message":
        if authority.gmail_account_id is None or authority.gmail_thread_id is None:
            raise _error("suggestion_authority_invalid")
        # Gmail reconciliation takes this lock before the suggestion row lock.
        # Approval must preserve that global ordering to avoid a lock inversion.
        await transaction_advisory_lock(
            await session.connection(),
            authority.gmail_account_id,
            authority.gmail_thread_id,
        )
    elif authority.source_type != "sydney_chat":
        raise _error("suggestion_authority_invalid")
    suggestion = await session.scalar(
        select(CRMTaskSuggestion)
        .where(CRMTaskSuggestion.id == suggestion_id)
        .with_for_update()
    )
    if suggestion is None:
        raise _error("suggestion_not_found", 404)
    return suggestion


async def _issue(
    session: AsyncSession,
    *,
    suggestion: CRMTaskSuggestion,
    kind: str,
    issuance_path: str,
    administrator_id: int | None,
    parent_nonce_id: UUID | None,
    lifetime: timedelta,
    now: datetime,
) -> IssuedApproval:
    for _attempt in range(3):
        token = _new_token()
        nonce = TaskSuggestionApprovalNonce(
            id=uuid4(),
            suggestion_id=suggestion.id,
            suggestion_version=suggestion.version,
            payload_hash=suggestion.payload_hash,
            kind=kind,
            issuance_path=issuance_path,
            token_hash=approval_token_hash(token),
            administrator_id=administrator_id,
            parent_nonce_id=parent_nonce_id,
            issued_at=now,
            expires_at=now + lifetime,
        )
        try:
            async with session.begin_nested():
                session.add(nonce)
                await session.flush()
        except IntegrityError as error:
            constraint = getattr(getattr(error, "orig", None), "constraint_name", None)
            if constraint == "uq_crm_task_suggestion_approval_nonces_token_hash":
                continue
            raise _error("approval_nonce_persistence_invalid", 503) from None
        return IssuedApproval(token=token, nonce=nonce)
    raise _error("approval_nonce_collision", 503)


class TaskSuggestionApprovalService:
    async def prepare(
        self,
        session: AsyncSession,
        *,
        suggestion_id: UUID,
        administrator_id: int,
        expected_version: int,
        expected_payload_hash: str,
        now: datetime | None = None,
    ) -> tuple[CRMTaskSuggestion, IssuedApproval]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        suggestion = await _locked_suggestion(session, suggestion_id)
        _assert_current(
            suggestion,
            expected_version=expected_version,
            expected_payload_hash=expected_payload_hash,
        )
        issued = await _issue(
            session,
            suggestion=suggestion,
            kind="approval",
            issuance_path="command_prepare",
            administrator_id=administrator_id,
            parent_nonce_id=None,
            lifetime=timedelta(minutes=5),
            now=now,
        )
        return suggestion, issued

    async def issue_handoff(
        self,
        session: AsyncSession,
        *,
        suggestion_id: UUID,
        expected_version: int,
        expected_payload_hash: str,
        now: datetime | None = None,
    ) -> tuple[CRMTaskSuggestion, IssuedApproval]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        suggestion = await _locked_suggestion(session, suggestion_id)
        _assert_current(
            suggestion,
            expected_version=expected_version,
            expected_payload_hash=expected_payload_hash,
        )
        active_handoffs = list(
            (
                await session.scalars(
                    select(TaskSuggestionApprovalNonce)
                    .where(
                        TaskSuggestionApprovalNonce.suggestion_id == suggestion.id,
                        TaskSuggestionApprovalNonce.suggestion_version
                        == suggestion.version,
                        TaskSuggestionApprovalNonce.payload_hash
                        == suggestion.payload_hash,
                        TaskSuggestionApprovalNonce.kind == "handoff",
                        TaskSuggestionApprovalNonce.issuance_path == "approval_link",
                        TaskSuggestionApprovalNonce.consumed_at.is_(None),
                        TaskSuggestionApprovalNonce.expires_at > now,
                    )
                    .with_for_update()
                )
            ).all()
        )
        for active in active_handoffs:
            active.consumed_at = now
        issued = await _issue(
            session,
            suggestion=suggestion,
            kind="handoff",
            issuance_path="approval_link",
            administrator_id=None,
            parent_nonce_id=None,
            lifetime=timedelta(minutes=15),
            now=now,
        )
        return suggestion, issued

    async def exchange_handoff(
        self,
        session: AsyncSession,
        *,
        suggestion_id: UUID,
        administrator_id: int,
        handoff: object,
        expected_version: int,
        expected_payload_hash: str,
        now: datetime | None = None,
    ) -> tuple[CRMTaskSuggestion, IssuedApproval]:
        digest = approval_token_hash(handoff)
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        suggestion = await _locked_suggestion(session, suggestion_id)
        parent = await session.scalar(
            select(TaskSuggestionApprovalNonce)
            .where(TaskSuggestionApprovalNonce.token_hash == digest)
            .with_for_update()
        )
        if (
            parent is None
            or parent.suggestion_id != suggestion_id
            or parent.kind != "handoff"
            or parent.issuance_path != "approval_link"
            or parent.administrator_id is not None
            or parent.parent_nonce_id is not None
            or parent.consumed_at is not None
            or now >= parent.expires_at
            or parent.suggestion_version != expected_version
            or not hmac.compare_digest(parent.payload_hash, expected_payload_hash)
        ):
            raise _error("handoff_invalid")
        _assert_current(
            suggestion,
            expected_version=expected_version,
            expected_payload_hash=expected_payload_hash,
        )
        # The database parent guard requires the handoff to be consumed before
        # its stage-two child can be inserted. Both writes remain in this one
        # caller transaction, so a child issuance failure rolls consumption back.
        parent.consumed_at = now
        await session.flush()
        issued = await _issue(
            session,
            suggestion=suggestion,
            kind="approval",
            issuance_path="handoff_exchange",
            administrator_id=administrator_id,
            parent_nonce_id=parent.id,
            lifetime=timedelta(minutes=5),
            now=now,
        )
        return suggestion, issued

    async def approve(
        self,
        session: AsyncSession,
        *,
        suggestion_id: UUID,
        administrator_id: int,
        approval: object,
        expected_version: int,
        expected_payload_hash: str,
        request_id: UUID,
        client_timezone: str,
        now: datetime | None = None,
    ) -> AppliedSuggestion:
        digest = approval_token_hash(approval)
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        suggestion = await _locked_suggestion(session, suggestion_id)
        nonce = await session.scalar(
            select(TaskSuggestionApprovalNonce)
            .where(TaskSuggestionApprovalNonce.token_hash == digest)
            .with_for_update()
        )
        if nonce is None or nonce.suggestion_id != suggestion_id:
            raise _error("approval_invalid")
        if (
            nonce.consumed_at is not None
            and nonce.kind == "approval"
            and nonce.issuance_path in {"command_prepare", "handoff_exchange"}
            and nonce.administrator_id == administrator_id
            and nonce.suggestion_version == expected_version
            and hmac.compare_digest(nonce.payload_hash, expected_payload_hash)
            and (
                (
                    nonce.issuance_path == "command_prepare"
                    and nonce.parent_nonce_id is None
                )
                or (
                    nonce.issuance_path == "handoff_exchange"
                    and nonce.parent_nonce_id is not None
                )
            )
            and suggestion.state == "applied"
            and suggestion.application_idempotency_key == request_id
            and suggestion.applied_task_id is not None
        ):
            task = await session.get(CRMTask, suggestion.applied_task_id)
            if task is None:
                raise _error("approval_replay_unavailable")
            return AppliedSuggestion(suggestion, task, request_id, True)
        if (
            nonce.kind != "approval"
            or nonce.issuance_path not in {"command_prepare", "handoff_exchange"}
            or nonce.administrator_id != administrator_id
            or nonce.consumed_at is not None
            or now >= nonce.expires_at
            or nonce.suggestion_version != expected_version
            or not hmac.compare_digest(nonce.payload_hash, expected_payload_hash)
            or (
                nonce.issuance_path == "command_prepare"
                and nonce.parent_nonce_id is not None
            )
            or (
                nonce.issuance_path == "handoff_exchange"
                and nonce.parent_nonce_id is None
            )
        ):
            raise _error("approval_invalid")
        _assert_current(
            suggestion,
            expected_version=expected_version,
            expected_payload_hash=expected_payload_hash,
        )
        suggestion.state = "approved"
        await session.flush()
        if suggestion.source_type == "gmail_message":
            try:
                payload = await CRMTaskSuggestionService.task_payload(
                    session=session,
                    suggestion=suggestion,
                    expected_version=expected_version,
                    expected_payload_hash=expected_payload_hash,
                )
            except CRMTaskSuggestionAuthorityError as error:
                raise _error(str(error)) from None
        elif suggestion.source_type == "sydney_chat":
            try:
                await CRMTaskSuggestionService.require_current_contact_authority(
                    session=session,
                    suggestion=suggestion,
                )
            except CRMTaskSuggestionAuthorityError as error:
                raise _error(str(error)) from None
            payload = CRMTaskSuggestionService.preview_payload(suggestion)
        else:
            raise _error("suggestion_authority_invalid")
        try:
            created = await crm_task_service.create(
                session,
                CreateTaskCommand(
                    **payload.model_dump(),
                    actor=TaskActor(type="admin", id=str(administrator_id)),
                    source=TaskSource(
                        type=suggestion.source_type,
                        id=str(suggestion.id),
                        key=suggestion.source_action_key,
                    ),
                    idempotency_scope="task_suggestion_approval",
                    idempotency_key=str(request_id),
                    client_timezone=client_timezone,
                ),
            )
        except TaskContactNotFound:
            raise _error("contact_authority_changed") from None
        except TaskIdempotencyConflict:
            raise _error("approval_request_id_conflict") from None
        except (TaskCommandValidationError, TaskCreationStateError, TaskSourceConflict):
            raise _error("task_application_invalid") from None
        nonce.consumed_at = now
        suggestion.state = "applied"
        suggestion.applied_task_id = created.task.id
        suggestion.application_idempotency_key = request_id
        suggestion.version += 1
        session.add_all(
            [
                CRMTaskSuggestionEvent(
                    suggestion_id=suggestion.id,
                    suggestion_version=expected_version,
                    event_type="approve",
                    actor_type="command_admin",
                    event_data_json=json.dumps(
                        {
                            "approval_nonce_id": str(nonce.id),
                            "request_id": str(request_id),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    created_at=now,
                ),
                CRMTaskSuggestionEvent(
                    suggestion_id=suggestion.id,
                    suggestion_version=suggestion.version,
                    event_type="apply",
                    actor_type="command_admin",
                    event_data_json=json.dumps(
                        {"request_id": str(request_id), "task_id": created.task.id},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    created_at=now,
                ),
            ]
        )
        await session.flush()
        return AppliedSuggestion(suggestion, created.task, request_id, created.replayed)


task_suggestion_approval_service = TaskSuggestionApprovalService()


def approval_link(*, suggestion_id: UUID, token: str) -> str:
    parse_approval_token(token)
    base_url = settings.COMMAND_PUBLIC_BASE_URL.rstrip("/")
    return (
        f"{base_url}/admin/command/task-suggestions?suggestion={suggestion_id}"
        f"#handoff={token}"
    )


__all__ = [
    "AppliedSuggestion",
    "IssuedApproval",
    "TaskSuggestionApprovalError",
    "TaskSuggestionApprovalService",
    "approval_link",
    "approval_token_hash",
    "parse_approval_token",
    "task_suggestion_approval_service",
]
