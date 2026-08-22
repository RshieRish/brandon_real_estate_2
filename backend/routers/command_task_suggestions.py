"""Authenticated Command review and approval routes for Sydney task drafts."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import AdminSubject, require_admin
from models.gmail_task_intake import (
    CRMTaskSuggestion,
    CRMTaskSuggestionSuppression,
    GmailExtractedObligation,
)
from models.sydney_tasks import CRMTaskSuggestionEvent
from schemas.agent_control_crm import (
    ApprovalPrepareResponse,
    ApprovalRequest,
    ApprovalResponse,
    DismissSuggestionRequest,
    HandoffExchangeRequest,
    SuggestionVersion,
    TaskSuggestionEditRequest,
    TaskSuggestionList,
    TaskSuggestionPreviewRequest,
    TaskSuggestionPreviewResponse,
    TaskSuggestionSummary,
)
from services.crm_task_suggestion_service import (
    CRMTaskSuggestionAuthorityError,
    CRMTaskSuggestionService,
    canonical_task_payload_hash,
)
from services.agent_control_audit import write_agent_audit_transactional
from services.sydney_clarification_service import supersede_locked_clarification
from services.integration_advisory_locks import transaction_advisory_lock
from services.task_suggestion_approval_service import (
    TaskSuggestionApprovalError,
    task_suggestion_approval_service,
)


router = APIRouter(dependencies=[Depends(require_admin)])

_BLOCKER_ORDER = (
    "missing_required_field",
    "ambiguous_due_at",
    "ambiguous_contact",
    "multiple_actions",
    "unsupported_owner",
    "unsupported_link",
)
_RESOLUTION_FIELDS = {
    "resolve_owner_as_brandon",
    "create_without_unsupported_link",
    "accept_current_task_details",
    "treat_as_single_action",
    "confirm_not_duplicate",
}


def _ordered_blockers(blockers: set[str]) -> list[str]:
    return [code for code in _BLOCKER_ORDER if code in blockers]


def _suppression_instance_digest(row: CRMTaskSuggestion) -> str:
    if row.primary_instance_digest is not None:
        return row.primary_instance_digest
    return hashlib.sha256(
        (
            f"{row.source_type}\0{row.source_scope_key}\0"
            f"{row.source_action_key}\0{row.obligation_fingerprint}"
        ).encode("utf-8")
    ).hexdigest()


async def _suppression_instance_digests(
    db: AsyncSession,
    row: CRMTaskSuggestion,
) -> list[str]:
    if row.source_type != "gmail_message":
        return [_suppression_instance_digest(row)]
    digests = set(
        (
            await db.scalars(
                select(GmailExtractedObligation.identity_instance_digest)
                .where(GmailExtractedObligation.reconciled_suggestion_id == row.id)
                .with_for_update()
            )
        ).all()
    )
    if row.primary_instance_digest is not None:
        digests.add(row.primary_instance_digest)
    if not digests:
        raise HTTPException(409, "suggestion_suppression_identity_invalid")
    return sorted(digests)


async def _locked_suggestion(
    db: AsyncSession,
    suggestion_id: UUID,
) -> CRMTaskSuggestion | None:
    identity = (
        await db.execute(
            select(
                CRMTaskSuggestion.source_type,
                CRMTaskSuggestion.gmail_account_id,
                CRMTaskSuggestion.gmail_thread_id,
            ).where(CRMTaskSuggestion.id == suggestion_id)
        )
    ).one_or_none()
    if identity is None:
        return None
    if identity.source_type == "gmail_message":
        if identity.gmail_account_id is None or identity.gmail_thread_id is None:
            raise HTTPException(409, "suggestion_authority_invalid")
        await transaction_advisory_lock(
            await db.connection(),
            identity.gmail_account_id,
            identity.gmail_thread_id,
        )
    return await db.scalar(
        select(CRMTaskSuggestion)
        .where(CRMTaskSuggestion.id == suggestion_id)
        .with_for_update()
    )


async def _has_live_conflicting_sibling(
    db: AsyncSession,
    row: CRMTaskSuggestion,
) -> bool:
    if (
        row.source_type != "gmail_message"
        or row.gmail_account_id is None
        or row.gmail_thread_id is None
    ):
        return False
    return (
        await db.scalar(
            select(CRMTaskSuggestion.id)
            .where(
                CRMTaskSuggestion.id != row.id,
                CRMTaskSuggestion.source_type == "gmail_message",
                CRMTaskSuggestion.gmail_account_id == row.gmail_account_id,
                CRMTaskSuggestion.gmail_thread_id == row.gmail_thread_id,
                CRMTaskSuggestion.source_action_key == row.source_action_key,
                CRMTaskSuggestion.obligation_fingerprint != row.obligation_fingerprint,
                CRMTaskSuggestion.state.in_(
                    (
                        "pending_review",
                        "needs_clarification",
                        "possible_duplicate",
                    )
                ),
            )
            .limit(1)
        )
        is not None
    )


def _summary(row: CRMTaskSuggestion) -> TaskSuggestionSummary:
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
        payload_hash=row.payload_hash,
        version=row.version,
        applied_task_id=row.applied_task_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _approval_error(error: TaskSuggestionApprovalError) -> HTTPException:
    return HTTPException(
        error.status_code,
        error.category,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )


def _no_secret_query(request: Request) -> None:
    forbidden = {"handoff", "approval", "token", "nonce"}
    if forbidden.intersection(key.casefold() for key in request.query_params):
        raise HTTPException(422, "approval_secrets_must_use_request_body")


def _protect_secret_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


@router.get("/task-suggestions", response_model=TaskSuggestionList)
async def list_task_suggestions(
    state: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> TaskSuggestionList:
    query = select(CRMTaskSuggestion)
    if state is not None:
        query = query.where(CRMTaskSuggestion.state == state)
    rows = list(
        (
            await db.scalars(
                query.order_by(
                    CRMTaskSuggestion.updated_at.desc(),
                    CRMTaskSuggestion.id,
                ).limit(limit)
            )
        ).all()
    )
    return TaskSuggestionList(suggestions=[_summary(row) for row in rows])


@router.get(
    "/task-suggestions/{suggestion_id}",
    response_model=TaskSuggestionSummary,
)
async def get_task_suggestion(
    suggestion_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> TaskSuggestionSummary:
    row = await db.get(CRMTaskSuggestion, suggestion_id)
    if row is None:
        raise HTTPException(404, "suggestion_not_found")
    return _summary(row)


@router.patch(
    "/task-suggestions/{suggestion_id}",
    response_model=TaskSuggestionSummary,
)
async def edit_task_suggestion(
    suggestion_id: UUID,
    payload: TaskSuggestionEditRequest,
    request: Request,
    actor_subject: AdminSubject,
    db: AsyncSession = Depends(get_db),
) -> TaskSuggestionSummary:
    async with db.begin():
        row = await _locked_suggestion(db, suggestion_id)
        if row is None:
            raise HTTPException(404, "suggestion_not_found")
        if not CRMTaskSuggestionService.is_current(
            row,
            expected_version=payload.expected_version,
            expected_payload_hash=payload.expected_payload_hash,
        ):
            raise HTTPException(409, "suggestion_stale")
        if row.state not in {
            "pending_review",
            "needs_clarification",
            "possible_duplicate",
        }:
            raise HTTPException(409, "suggestion_not_editable")
        old_version = row.version
        old_hash = row.payload_hash
        choices = {field: bool(getattr(payload, field)) for field in _RESOLUTION_FIELDS}
        blockers = set(row.blocker_codes)
        duplicate_resolution_required = (
            row.state == "possible_duplicate"
            or await _has_live_conflicting_sibling(db, row)
        )
        applicability = {
            "resolve_owner_as_brandon": (
                "unsupported_owner" in blockers or row.owner_clarification_pending
            ),
            "create_without_unsupported_link": "unsupported_link" in blockers,
            "accept_current_task_details": row.task_details_clarification_pending,
            "treat_as_single_action": "multiple_actions" in blockers,
            "confirm_not_duplicate": duplicate_resolution_required,
        }
        if any(choices[name] and not applicability[name] for name in choices):
            raise HTTPException(409, "blocker_resolution_not_applicable")
        changes = payload.model_dump(
            exclude_unset=True,
            exclude={
                "expected_version",
                "expected_payload_hash",
                *_RESOLUTION_FIELDS,
            },
        )
        if "contact_id" in changes:
            try:
                (
                    resolution_state,
                    resolution_hash,
                ) = await CRMTaskSuggestionService.resolve_contact_authority(
                    session=db,
                    contact_id=changes["contact_id"],
                )
            except CRMTaskSuggestionAuthorityError:
                raise HTTPException(422, "suggestion_contact_invalid") from None
            row.contact_resolution_state = resolution_state
            row.contact_resolution_hash = resolution_hash
            blockers.discard("ambiguous_contact")
        if "due_at" in changes:
            blockers.discard("ambiguous_due_at")
        if choices["resolve_owner_as_brandon"]:
            blockers.discard("unsupported_owner")
            row.owner_clarification_pending = False
        if choices["create_without_unsupported_link"]:
            blockers.discard("unsupported_link")
        if choices["accept_current_task_details"]:
            row.task_details_clarification_pending = False
        if choices["treat_as_single_action"]:
            blockers.discard("multiple_actions")
        if not (
            row.owner_clarification_pending or row.task_details_clarification_pending
        ):
            blockers.discard("missing_required_field")
        for name, value in changes.items():
            setattr(row, name, value)
        row.version += 1
        row.payload_hash = canonical_task_payload_hash(
            title=row.title,
            description=row.description,
            priority=row.priority,
            due_at=row.due_at,
            contact_id=row.contact_id,
            status=row.task_status,
        )
        row.blocker_codes = _ordered_blockers(blockers)
        clarification_blocked = bool(
            blockers.intersection(
                {
                    "missing_required_field",
                    "ambiguous_due_at",
                    "ambiguous_contact",
                    "multiple_actions",
                }
            )
        )
        if duplicate_resolution_required and not choices["confirm_not_duplicate"]:
            row.state = "possible_duplicate"
        elif clarification_blocked:
            row.state = "needs_clarification"
        else:
            row.state = "pending_review"
        row.clarification_state = (
            "manual_review_required" if clarification_blocked else "not_required"
        )
        await supersede_locked_clarification(
            session=db,
            suggestion=row,
            previous_version=old_version,
            now=datetime.now(timezone.utc),
        )
        audit = await write_agent_audit_transactional(
            db,
            request=request,
            actor=f"command_admin:{actor_subject}",
            action_id="command.task_suggestions.edit",
            status_code=200,
            allowed=True,
            request_meta={
                "suggestion_id": str(row.id),
                "expected_version": payload.expected_version,
                "explicit_resolutions": sorted(
                    name for name, selected in choices.items() if selected
                ),
            },
            response_meta={"suggestion_version": row.version},
        )
        db.add(
            CRMTaskSuggestionEvent(
                suggestion_id=row.id,
                suggestion_version=row.version,
                event_type="edit",
                actor_type="command_admin",
                event_data_json=json.dumps(
                    {
                        "administrator_id": int(actor_subject),
                        "changed_fields": sorted(changes),
                        "explicit_resolutions": sorted(
                            name for name, selected in choices.items() if selected
                        ),
                        "remaining_blockers": row.blocker_codes,
                        "old_payload_hash": old_hash,
                        "old_version": old_version,
                        "new_payload_hash": row.payload_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                action_audit_id=audit.id,
            )
        )
        await db.flush()
        await db.refresh(row)
        result = _summary(row)
    return result


@router.post(
    "/task-suggestions/{suggestion_id}/preview",
    response_model=TaskSuggestionPreviewResponse,
)
async def preview_task_suggestion(
    suggestion_id: UUID,
    payload: TaskSuggestionPreviewRequest,
    actor_subject: AdminSubject,
    db: AsyncSession = Depends(get_db),
) -> TaskSuggestionPreviewResponse:
    async with db.begin():
        row = await _locked_suggestion(db, suggestion_id)
        if row is None:
            raise HTTPException(404, "suggestion_not_found")
        if not CRMTaskSuggestionService.is_current(
            row,
            expected_version=payload.expected_version,
            expected_payload_hash=payload.expected_payload_hash,
        ):
            raise HTTPException(409, "suggestion_stale")
        task = CRMTaskSuggestionService.preview_payload(row)
        db.add(
            CRMTaskSuggestionEvent(
                suggestion_id=row.id,
                suggestion_version=row.version,
                event_type="preview",
                actor_type="command_admin",
                event_data_json=json.dumps(
                    {
                        "administrator_id": int(actor_subject),
                        "payload_hash": row.payload_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
    return TaskSuggestionPreviewResponse(
        suggestion_id=row.id,
        suggestion_version=row.version,
        payload_hash=row.payload_hash,
        task=task,
    )


async def _prepare_response(
    *,
    suggestion_id: UUID,
    payload: SuggestionVersion,
    actor_subject: str,
    db: AsyncSession,
    response: Response,
) -> ApprovalPrepareResponse:
    try:
        async with db.begin():
            row, issued = await task_suggestion_approval_service.prepare(
                db,
                suggestion_id=suggestion_id,
                administrator_id=int(actor_subject),
                expected_version=payload.expected_version,
                expected_payload_hash=payload.expected_payload_hash,
            )
    except TaskSuggestionApprovalError as error:
        raise _approval_error(error) from None
    _protect_secret_response(response)
    return ApprovalPrepareResponse(
        suggestion_id=row.id,
        suggestion_version=row.version,
        payload_hash=row.payload_hash,
        task=CRMTaskSuggestionService.preview_payload(row),
        approval=issued.token,
        expires_at=issued.nonce.expires_at,
    )


@router.post(
    "/task-suggestions/{suggestion_id}/approval/prepare",
    response_model=ApprovalPrepareResponse,
)
async def prepare_task_suggestion_approval(
    suggestion_id: UUID,
    payload: SuggestionVersion,
    request: Request,
    response: Response,
    actor_subject: AdminSubject,
    db: AsyncSession = Depends(get_db),
) -> ApprovalPrepareResponse:
    _no_secret_query(request)
    return await _prepare_response(
        suggestion_id=suggestion_id,
        payload=payload,
        actor_subject=actor_subject,
        db=db,
        response=response,
    )


@router.post(
    "/task-suggestions/{suggestion_id}/handoff/exchange",
    response_model=ApprovalPrepareResponse,
)
async def exchange_task_suggestion_handoff(
    suggestion_id: UUID,
    payload: HandoffExchangeRequest,
    request: Request,
    response: Response,
    actor_subject: AdminSubject,
    db: AsyncSession = Depends(get_db),
) -> ApprovalPrepareResponse:
    _no_secret_query(request)
    try:
        async with db.begin():
            row, issued = await task_suggestion_approval_service.exchange_handoff(
                db,
                suggestion_id=suggestion_id,
                administrator_id=int(actor_subject),
                handoff=payload.handoff,
                expected_version=payload.expected_version,
                expected_payload_hash=payload.expected_payload_hash,
            )
    except TaskSuggestionApprovalError as error:
        raise _approval_error(error) from None
    _protect_secret_response(response)
    return ApprovalPrepareResponse(
        suggestion_id=row.id,
        suggestion_version=row.version,
        payload_hash=row.payload_hash,
        task=CRMTaskSuggestionService.preview_payload(row),
        approval=issued.token,
        expires_at=issued.nonce.expires_at,
    )


@router.post(
    "/task-suggestions/{suggestion_id}/approve",
    response_model=ApprovalResponse,
)
async def approve_task_suggestion(
    suggestion_id: UUID,
    payload: ApprovalRequest,
    request: Request,
    response: Response,
    actor_subject: AdminSubject,
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    _no_secret_query(request)
    try:
        async with db.begin():
            result = await task_suggestion_approval_service.approve(
                db,
                suggestion_id=suggestion_id,
                administrator_id=int(actor_subject),
                approval=payload.approval,
                expected_version=payload.expected_version,
                expected_payload_hash=payload.expected_payload_hash,
                request_id=payload.request_id,
                client_timezone=payload.client_timezone,
            )
            if not result.replayed:
                await write_agent_audit_transactional(
                    db,
                    request=request,
                    actor=f"command_admin:{actor_subject}",
                    action_id="command.task_suggestions.approve",
                    status_code=200,
                    allowed=True,
                    request_meta={
                        "request_id": str(payload.request_id),
                        "suggestion_id": str(suggestion_id),
                        "expected_version": payload.expected_version,
                    },
                    response_meta={"task_id": result.task.id},
                )
    except TaskSuggestionApprovalError as error:
        raise _approval_error(error) from None
    _protect_secret_response(response)
    return ApprovalResponse(
        suggestion_id=result.suggestion.id,
        suggestion_version=result.suggestion.version,
        task_id=result.task.id,
        request_id=result.request_id,
        replayed=result.replayed,
    )


@router.post(
    "/task-suggestions/{suggestion_id}/dismiss",
    response_model=TaskSuggestionSummary,
)
async def dismiss_task_suggestion(
    suggestion_id: UUID,
    payload: DismissSuggestionRequest,
    request: Request,
    actor_subject: AdminSubject,
    db: AsyncSession = Depends(get_db),
) -> TaskSuggestionSummary:
    async with db.begin():
        row = await _locked_suggestion(db, suggestion_id)
        if row is None:
            raise HTTPException(404, "suggestion_not_found")
        if not CRMTaskSuggestionService.is_current(
            row,
            expected_version=payload.expected_version,
            expected_payload_hash=payload.expected_payload_hash,
        ):
            raise HTTPException(409, "suggestion_stale")
        if row.state in {"approved", "applied", "dismissed"}:
            raise HTTPException(409, "suggestion_not_dismissible")
        instance_digests = await _suppression_instance_digests(db, row)
        existing_suppression = await db.scalar(
            select(CRMTaskSuggestionSuppression)
            .where(
                CRMTaskSuggestionSuppression.source_type == row.source_type,
                CRMTaskSuggestionSuppression.source_scope_key == row.source_scope_key,
                CRMTaskSuggestionSuppression.source_action_key == row.source_action_key,
                CRMTaskSuggestionSuppression.obligation_fingerprint
                == row.obligation_fingerprint,
                CRMTaskSuggestionSuppression.identity_instance_digest.in_(
                    instance_digests
                ),
            )
            .with_for_update()
        )
        if existing_suppression is not None:
            raise HTTPException(409, "suggestion_already_suppressed")
        previous_version = row.version
        row.state = "dismissed"
        row.version += 1
        row.clarification_state = "not_required"
        now = datetime.now(timezone.utc)
        await supersede_locked_clarification(
            session=db,
            suggestion=row,
            previous_version=previous_version,
            now=now,
        )
        audit = await write_agent_audit_transactional(
            db,
            request=request,
            actor=f"command_admin:{actor_subject}",
            action_id="command.task_suggestions.dismiss",
            status_code=200,
            allowed=True,
            request_meta={
                "suggestion_id": str(row.id),
                "expected_version": payload.expected_version,
            },
            response_meta={"suggestion_version": row.version},
        )
        suppressions = [
            CRMTaskSuggestionSuppression(
                id=uuid4(),
                source_type=row.source_type,
                source_scope_key=row.source_scope_key,
                source_action_key=row.source_action_key,
                obligation_fingerprint=row.obligation_fingerprint,
                identity_instance_digest=instance_digest,
                dismissal_reason=payload.reason,
                dismissed_by_admin_id=int(actor_subject),
                dismissal_audit_id=audit.id,
                dismissed_at=now,
            )
            for instance_digest in instance_digests
        ]
        db.add_all(suppressions)
        db.add(
            CRMTaskSuggestionEvent(
                suggestion_id=row.id,
                suggestion_version=row.version,
                event_type="dismiss",
                actor_type="command_admin",
                event_data_json=json.dumps(
                    {
                        "administrator_id": int(actor_subject),
                        "reason": payload.reason,
                        "suppression_ids": [
                            str(suppression.id) for suppression in suppressions
                        ],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                action_audit_id=audit.id,
                created_at=now,
            )
        )
        await db.flush()
        await db.refresh(row)
        result = _summary(row)
    return result


__all__ = ["router"]
