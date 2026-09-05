"""Bounded, review-only CRM capabilities for the Hermes agent bridge."""

from __future__ import annotations

import base64
import hashlib
import json
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.agent_control import require_agent_control
from models.command import CRMTask
from models.gmail_task_intake import CRMTaskSuggestion
from models.sydney_tasks import CRMTaskSuggestionEvent
from schemas.agent_control_crm import (
    AgentApprovalLinkRequest,
    AgentApprovalLinkResponse,
    AgentClarificationAnswerRequest,
    AgentClarificationAnswerResponse,
    AgentDismissProposalRequest,
    AgentDismissProposalResponse,
    AgentTaskDraftRequest,
    CRMTaskList,
    CRMTaskSummary,
    TaskSuggestionList,
    TaskSuggestionSummary,
)
from services.agent_control_audit import (
    write_agent_audit,
    write_agent_audit_transactional,
)
from services.crm_task_suggestion_service import (
    CRMTaskSuggestionAuthorityError,
    CRMTaskSuggestionService,
    canonical_task_payload_hash,
)
from services.sydney_clarification_service import (
    SydneyClarificationError,
    SydneyClarificationService,
)
from services.task_suggestion_approval_service import (
    TaskSuggestionApprovalError,
    approval_link,
    task_suggestion_approval_service,
)


router = APIRouter(dependencies=[Depends(require_agent_control)])

# Only explicit leading control labels identify fixtures. Ordinary words such
# as "water test" or "rollout testing" are valid business task titles.
_CONTROLLED_TASK_TITLE = (
    r"^\s*\[\s*(rollout[\s_-]+test|controlled[\s_-]+(rollout[\s_-]+)?test)\s*\]"
)


def _suggestion(row: CRMTaskSuggestion) -> TaskSuggestionSummary:
    blockers = set(row.blocker_codes)
    resolution_requirements = []
    if "unsupported_owner" in blockers or row.owner_clarification_pending:
        resolution_requirements.append("resolve_owner_as_brandon")
    if "unsupported_link" in blockers:
        resolution_requirements.append("create_without_unsupported_link")
    if row.task_details_clarification_pending:
        resolution_requirements.append("accept_current_task_details")
    if "multiple_actions" in blockers:
        resolution_requirements.append("treat_as_single_action")
    if row.state == "possible_duplicate":
        resolution_requirements.append("confirm_not_duplicate")
    return TaskSuggestionSummary(
        id=row.id,
        source_type=row.source_type,
        title=row.title,
        description=row.description,
        priority=row.priority,
        due_at=row.due_at,
        contact_id=row.contact_id,
        status=row.task_status,
        state=row.state,
        clarification_state=row.clarification_state,
        blocker_codes=list(row.blocker_codes),
        resolution_requirements=resolution_requirements,
        confidence=float(row.confidence),
        rationale=row.rationale,
        model_schema_version=row.model_schema_version,
        payload_hash=row.payload_hash,
        version=row.version,
        applied_task_id=row.applied_task_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _task(row: CRMTask) -> CRMTaskSummary:
    return CRMTaskSummary(
        id=row.id,
        contact_id=row.contact_id,
        title=row.title,
        description=row.description,
        status=row.status,
        priority=row.priority,
        due_at=row.due_at,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class _NoopTransaction(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _BorrowedSession:
    """Let a legacy session-owning service participate in the caller transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    def begin(self) -> _NoopTransaction:
        return _NoopTransaction()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


class _BorrowedSessionFactory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> _BorrowedSession:
        return _BorrowedSession(self._session)


def _clarification_service(db: AsyncSession) -> SydneyClarificationService:
    try:
        raw = json.loads(settings.SYDNEY_CLARIFICATION_CODE_KEYS_JSON)
        if not isinstance(raw, dict):
            raise ValueError
        keys = {
            int(version): base64.b64decode(value, validate=True)
            for version, value in raw.items()
        }
        return SydneyClarificationService(
            sessionmaker=_BorrowedSessionFactory(db),  # type: ignore[arg-type]
            brandon_chat_id=settings.SYDNEY_TELEGRAM_BRANDON_CHAT_ID,
            clarification_code_keys=keys,
            active_code_key_version=settings.SYDNEY_CLARIFICATION_ACTIVE_KEY_VERSION,
        )
    except (KeyError, TypeError, ValueError, SydneyClarificationError):
        raise HTTPException(503, "sydney_clarifications_not_configured") from None


async def _contact_authority(
    db: AsyncSession,
    contact_id: int | None,
) -> tuple[str, str | None]:
    try:
        return await CRMTaskSuggestionService.resolve_contact_authority(
            session=db,
            contact_id=contact_id,
            none_state="not_provided",
        )
    except CRMTaskSuggestionAuthorityError:
        raise HTTPException(422, "task_draft_contact_invalid") from None


def _draft_replay_matches(
    existing: CRMTaskSuggestion,
    *,
    request_id: UUID,
    original_payload_hash: str,
) -> bool:
    return (
        existing.source_type == "sydney_chat"
        and existing.source_scope_key == f"sydney:agent-control:{request_id}"
        and existing.source_action_key == f"agent-draft:{request_id.hex}"
        and existing.obligation_fingerprint == original_payload_hash
    )


@router.get("/crm/tasks", response_model=CRMTaskList)
async def list_crm_tasks(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
    *,
    task_mode: Annotated[
        Literal["active", "history"],
        Query(
            description="Active by default; history includes all nonarchived statuses, including completed and cancelled tasks."
        ),
    ] = "active",
    include_controlled_tests: Annotated[
        bool,
        Query(
            description="Explicitly include labelled controlled rollout/test tasks; false by default."
        ),
    ] = False,
) -> CRMTaskList:
    statement = select(CRMTask).where(CRMTask.archived_at.is_(None))
    if task_mode == "active":
        statement = statement.where(CRMTask.status.in_(("open", "in_progress")))
    if not include_controlled_tests:
        statement = statement.where(
            ~CRMTask.title.regexp_match(_CONTROLLED_TASK_TITLE, flags="i")
        )
    rows = list(
        (
            await db.scalars(
                statement.order_by(CRMTask.updated_at.desc(), CRMTask.id.desc()).limit(
                    limit
                )
            )
        ).all()
    )
    response = CRMTaskList(tasks=[_task(row) for row in rows])
    await write_agent_audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="crm.tasks.read",
        status_code=200,
        allowed=True,
        response_meta={
            "count": len(rows),
            "task_mode": task_mode,
            "include_controlled_tests": include_controlled_tests,
        },
    )
    return response


@router.get("/crm/task-suggestions", response_model=TaskSuggestionList)
async def list_crm_task_suggestions(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> TaskSuggestionList:
    rows = list(
        (
            await db.scalars(
                select(CRMTaskSuggestion)
                .order_by(CRMTaskSuggestion.updated_at.desc(), CRMTaskSuggestion.id)
                .limit(limit)
            )
        ).all()
    )
    response = TaskSuggestionList(suggestions=[_suggestion(row) for row in rows])
    await write_agent_audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="crm.task_suggestions.read",
        status_code=200,
        allowed=True,
        response_meta={"count": len(rows)},
    )
    return response


@router.post(
    "/crm/task-clarifications/answer",
    response_model=AgentClarificationAnswerResponse,
)
async def answer_task_clarification(
    payload: AgentClarificationAnswerRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> AgentClarificationAnswerResponse:
    service = _clarification_service(db)
    try:
        async with db.begin():
            result = await service.answer(
                code=payload.code,
                expected_suggestion_version=payload.expected_version,
                answer=payload.answer,
                now=datetime.now(timezone.utc),
            )
            await write_agent_audit_transactional(
                db,
                request=request,
                actor=agent["actor"],
                action_id="crm.task_clarifications.answer",
                status_code=200,
                allowed=True,
                request_meta={"expected_version": payload.expected_version},
                response_meta={"suggestion_id": str(result.suggestion_id)},
            )
    except SydneyClarificationError as error:
        raise HTTPException(409, str(error)) from None
    if result.handoff_link is not None:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
    return AgentClarificationAnswerResponse(
        suggestion_id=result.suggestion_id,
        suggestion_version=result.suggestion_version,
        next_clarification_id=result.next_clarification_id,
        approval_link=result.handoff_link,
    )


@router.post("/crm/task-drafts", response_model=TaskSuggestionSummary)
async def create_task_draft(
    payload: AgentTaskDraftRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> TaskSuggestionSummary:
    async with db.begin():
        existing = await db.scalar(
            select(CRMTaskSuggestion)
            .where(CRMTaskSuggestion.source_request_id == payload.request_id)
            .with_for_update()
        )
        payload_hash = canonical_task_payload_hash(
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            due_at=payload.due_at,
            contact_id=payload.contact_id,
            status="open",
        )
        if existing is not None:
            if not _draft_replay_matches(
                existing,
                request_id=payload.request_id,
                original_payload_hash=payload_hash,
            ):
                raise HTTPException(409, "task_draft_idempotency_mismatch")
            return _suggestion(existing)
        resolution_state, resolution_hash = await _contact_authority(
            db, payload.contact_id
        )
        source_scope = f"sydney:agent-control:{payload.request_id}"
        task_details_pending = not payload.description.strip()
        blocker_codes = ["missing_required_field"] if task_details_pending else []
        row = CRMTaskSuggestion(
            source_type="sydney_chat",
            source_scope_key=source_scope,
            source_action_key=f"agent-draft:{payload.request_id.hex}",
            source_request_id=payload.request_id,
            contact_id=payload.contact_id,
            contact_resolution_state=resolution_state,
            contact_resolution_hash=resolution_hash,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            due_at=payload.due_at,
            task_status="open",
            state=("needs_clarification" if task_details_pending else "pending_review"),
            clarification_state=("pending" if task_details_pending else "not_required"),
            blocker_codes=blocker_codes,
            owner_clarification_pending=False,
            task_details_clarification_pending=task_details_pending,
            payload_hash=payload_hash,
            model_schema_version="sydney-agent-draft-v1",
            obligation_fingerprint=payload_hash,
            primary_instance_digest=hashlib.sha256(
                f"agent-draft-instance:{payload.request_id}".encode("ascii")
            ).hexdigest(),
            confidence=1,
            rationale="Submitted by Hermes for Brandon review.",
            version=1,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            existing = await db.scalar(
                select(CRMTaskSuggestion)
                .where(CRMTaskSuggestion.source_request_id == payload.request_id)
                .with_for_update()
            )
            if existing is None:
                raise HTTPException(503, "task_draft_persistence_invalid")
            if not _draft_replay_matches(
                existing,
                request_id=payload.request_id,
                original_payload_hash=payload_hash,
            ):
                raise HTTPException(409, "task_draft_idempotency_mismatch")
            return _suggestion(existing)
        await write_agent_audit_transactional(
            db,
            request=request,
            actor=agent["actor"],
            action_id="crm.task_drafts.create",
            status_code=200,
            allowed=True,
            request_meta={"request_id": str(payload.request_id)},
            response_meta={"suggestion_id": str(row.id), "state": row.state},
        )
    return _suggestion(row)


@router.post(
    "/crm/task-suggestions/{suggestion_id}/approval-link",
    response_model=AgentApprovalLinkResponse,
)
async def create_task_suggestion_approval_link(
    suggestion_id: UUID,
    payload: AgentApprovalLinkRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> AgentApprovalLinkResponse:
    try:
        async with db.begin():
            row, issued = await task_suggestion_approval_service.issue_handoff(
                db,
                suggestion_id=suggestion_id,
                expected_version=payload.expected_version,
                expected_payload_hash=payload.expected_payload_hash,
            )
            await write_agent_audit_transactional(
                db,
                request=request,
                actor=agent["actor"],
                action_id="crm.task_suggestions.approval_link",
                status_code=200,
                allowed=True,
                request_meta={
                    "expected_version": payload.expected_version,
                },
                response_meta={"suggestion_id": str(row.id)},
            )
    except TaskSuggestionApprovalError as error:
        raise HTTPException(error.status_code, error.category) from None
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return AgentApprovalLinkResponse(
        suggestion_id=row.id,
        suggestion_version=row.version,
        approval_link=approval_link(suggestion_id=row.id, token=issued.token),
        expires_at=issued.nonce.expires_at,
    )


@router.post(
    "/crm/task-suggestions/{suggestion_id}/dismiss-proposal",
    response_model=AgentDismissProposalResponse,
)
async def propose_task_suggestion_dismissal(
    suggestion_id: UUID,
    payload: AgentDismissProposalRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> AgentDismissProposalResponse:
    async with db.begin():
        row = await db.scalar(
            select(CRMTaskSuggestion)
            .where(CRMTaskSuggestion.id == suggestion_id)
            .with_for_update()
        )
        if row is None:
            raise HTTPException(404, "suggestion_not_found")
        prior_events = list(
            (
                await db.scalars(
                    select(CRMTaskSuggestionEvent)
                    .where(
                        CRMTaskSuggestionEvent.suggestion_id == row.id,
                        CRMTaskSuggestionEvent.event_type == "dismiss_proposed",
                        CRMTaskSuggestionEvent.actor_type == "untrusted_hermes_input",
                    )
                    .order_by(
                        CRMTaskSuggestionEvent.created_at,
                        CRMTaskSuggestionEvent.id,
                    )
                    .limit(101)
                )
            ).all()
        )
        for event in prior_events:
            try:
                event_data = json.loads(event.event_data_json)
            except (TypeError, json.JSONDecodeError):
                continue
            if event_data.get("request_id") == str(payload.request_id):
                if event_data.get("reason") != payload.reason:
                    raise HTTPException(409, "dismiss_proposal_idempotency_mismatch")
                return AgentDismissProposalResponse(
                    suggestion_id=row.id,
                    suggestion_version=event.suggestion_version,
                    request_id=payload.request_id,
                    replayed=True,
                )
        if len(prior_events) >= 100:
            raise HTTPException(409, "dismiss_proposal_history_limit")
        if row.version != payload.expected_version:
            raise HTTPException(409, "suggestion_stale")
        audit = await write_agent_audit_transactional(
            db,
            request=request,
            actor=agent["actor"],
            action_id="crm.task_suggestions.dismiss_proposal",
            status_code=200,
            allowed=True,
            request_meta={"request_id": str(payload.request_id)},
            response_meta={"suggestion_id": str(row.id)},
        )
        db.add(
            CRMTaskSuggestionEvent(
                suggestion_id=row.id,
                suggestion_version=row.version,
                event_type="dismiss_proposed",
                actor_type="untrusted_hermes_input",
                event_data_json=json.dumps(
                    {"reason": payload.reason, "request_id": str(payload.request_id)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                action_audit_id=audit.id,
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.flush()
    return AgentDismissProposalResponse(
        suggestion_id=row.id,
        suggestion_version=row.version,
        request_id=payload.request_id,
        replayed=False,
    )


__all__ = ["router"]
