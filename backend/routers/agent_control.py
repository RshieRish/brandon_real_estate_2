import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.agent_control import require_agent_control
from models.booking import Booking
from models.gmail_task_intake import (
    GmailBackfillRequest,
    GmailMissingMessageIncident,
    GmailSyncRun,
)
from models.lead import Lead
from schemas.agent_control import (
    AgentAction,
    AgentActionsResponse,
    AgentBookingSummary,
    AgentLeadSummary,
    AgentStatusResponse,
    RecentBookingsResponse,
    RecentLeadsResponse,
    WorkspaceCalendarCreateEventRequest,
    WorkspaceCalendarCreateEventResponse,
    WorkspaceCalendarEventsRequest,
    WorkspaceCalendarEventsResponse,
    WorkspaceCalendarEventSummary,
    WorkspaceContactsSearchRequest,
    WorkspaceContactsSearchResponse,
    WorkspaceContactSummary,
    WorkspaceDocsCreateRequest,
    WorkspaceDocsCreateResponse,
    WorkspaceDriveFileReadRequest,
    WorkspaceDriveFileReadResponse,
    WorkspaceDriveFileSummary,
    WorkspaceDriveSearchRequest,
    WorkspaceDriveSearchResponse,
    WorkspaceGmailDraftRequest,
    WorkspaceGmailDraftResponse,
    WorkspaceGmailMessageSummary,
    WorkspaceGmailSearchRequest,
    WorkspaceGmailSearchResponse,
    WorkspaceGmailSendRequest,
    WorkspaceGmailSendResponse,
    WorkspaceGmailThreadMessage,
    WorkspaceGmailThreadRequest,
    WorkspaceGmailThreadResponse,
    WorkspaceSheetsAppendRequest,
    WorkspaceSheetsAppendResponse,
)
from schemas.gmail_task_intake import (
    GmailMissingMessageAcknowledgeRequest,
    GmailMissingMessageAcknowledgeResponse,
    GmailMissingMessageIncidentDetail,
)
from middleware.auth import AdminSubject
from services.agent_control_audit import write_agent_audit
from services.gmail_origin_service import (
    GmailSendConflict,
    send_agent_gmail_with_origin,
)
from services.gmail_history_service import (
    GmailMissingMessageAcknowledgementError,
    acknowledge_missing_message_incident,
)
from services.workspace_service import (
    append_sheet_values,
    create_gmail_draft,
    create_google_doc,
    create_workspace_calendar_event,
    get_gmail_thread,
    get_workspace_connection_status_bounded,
    list_calendar_events,
    read_drive_file,
    search_contacts,
    search_drive_files,
    search_gmail_messages,
    send_gmail_message,  # noqa: F401 - legacy patch seam proves route bypass
)
from routers.workspace import load_workspace_refresh_token_from_db

router = APIRouter()

AGENT_ACTIONS = [
    AgentAction(
        id="status.read",
        method="GET",
        path="/api/v1/agent-control/status",
        risk_tier="auto_silent",
        side_effects=False,
        description="Read backend health and capability metadata.",
    ),
    AgentAction(
        id="leads.recent.read",
        method="GET",
        path="/api/v1/agent-control/leads/recent",
        risk_tier="auto_silent",
        side_effects=False,
        description="Read recent lead summaries for operational context.",
    ),
    AgentAction(
        id="bookings.recent.read",
        method="GET",
        path="/api/v1/agent-control/bookings/recent",
        risk_tier="auto_silent",
        side_effects=False,
        description="Read recent booking summaries for operational context.",
    ),
    AgentAction(
        id="workspace.status.read",
        method="GET",
        path="/api/v1/agent-control/workspace/status",
        risk_tier="auto_silent",
        side_effects=False,
        description="Read Google Workspace connection state.",
    ),
    AgentAction(
        id="workspace.drive.search",
        method="POST",
        path="/api/v1/agent-control/workspace/drive/search",
        risk_tier="auto_silent",
        side_effects=False,
        description="Search Brandon's Google Drive and return compact file summaries.",
    ),
    AgentAction(
        id="workspace.drive.file.read",
        method="POST",
        path="/api/v1/agent-control/workspace/drive/file",
        risk_tier="auto_silent",
        side_effects=False,
        description="Read text content from a supported Google Drive file.",
    ),
    AgentAction(
        id="workspace.gmail.search",
        method="POST",
        path="/api/v1/agent-control/workspace/gmail/search",
        risk_tier="auto_silent",
        side_effects=False,
        description="Search Brandon's Gmail and return compact message summaries.",
    ),
    AgentAction(
        id="workspace.gmail.thread.read",
        method="POST",
        path="/api/v1/agent-control/workspace/gmail/thread",
        risk_tier="auto_silent",
        side_effects=False,
        description="Read a Gmail thread body for approved Hermes context.",
    ),
    AgentAction(
        id="workspace.calendar.events.read",
        method="POST",
        path="/api/v1/agent-control/workspace/calendar/events",
        risk_tier="auto_silent",
        side_effects=False,
        description="Read Brandon's Google Calendar events in a bounded time window.",
    ),
    AgentAction(
        id="workspace.contacts.search",
        method="POST",
        path="/api/v1/agent-control/workspace/contacts/search",
        risk_tier="auto_silent",
        side_effects=False,
        description="Search Brandon's Google Contacts for recipient context.",
    ),
    AgentAction(
        id="workspace.gmail.draft.create",
        method="POST",
        path="/api/v1/agent-control/workspace/gmail/draft",
        risk_tier="operator_review",
        side_effects=True,
        description="Create a Gmail draft in Brandon's mailbox without sending it.",
    ),
    AgentAction(
        id="workspace.docs.create",
        method="POST",
        path="/api/v1/agent-control/workspace/docs/create",
        risk_tier="operator_review",
        side_effects=True,
        description="Create a Google Doc and insert supplied text.",
    ),
    AgentAction(
        id="workspace.sheets.append",
        method="POST",
        path="/api/v1/agent-control/workspace/sheets/append",
        risk_tier="operator_review",
        side_effects=True,
        description="Append rows to a Google Sheet.",
    ),
    AgentAction(
        id="workspace.gmail.send",
        method="POST",
        path="/api/v1/agent-control/workspace/gmail/send",
        risk_tier="human_confirm",
        side_effects=True,
        description="Send email from Brandon's mailbox only after explicit Brandon confirmation.",
    ),
    AgentAction(
        id="workspace.calendar.event.create",
        method="POST",
        path="/api/v1/agent-control/workspace/calendar/event/create",
        risk_tier="human_confirm",
        side_effects=True,
        description="Create a Google Calendar event only after explicit Brandon confirmation.",
    ),
    AgentAction(
        id="crm.tasks.read",
        method="GET",
        path="/api/v1/agent-control/crm/tasks",
        risk_tier="auto_silent",
        side_effects=False,
        description="Read active CRM task summaries.",
    ),
    AgentAction(
        id="crm.task_suggestions.read",
        method="GET",
        path="/api/v1/agent-control/crm/task-suggestions",
        risk_tier="auto_silent",
        side_effects=False,
        description="Read Sydney task suggestions awaiting review.",
    ),
    AgentAction(
        id="crm.task_clarifications.answer",
        method="POST",
        path="/api/v1/agent-control/crm/task-clarifications/answer",
        risk_tier="operator_review",
        side_effects=True,
        description="Answer one opaque Sydney clarification without approving a task.",
    ),
    AgentAction(
        id="crm.task_drafts.create",
        method="POST",
        path="/api/v1/agent-control/crm/task-drafts",
        risk_tier="operator_review",
        side_effects=True,
        description="Create a Brandon-owned task suggestion for later Command review.",
    ),
    AgentAction(
        id="crm.task_suggestions.approval_link",
        method="POST",
        path="/api/v1/agent-control/crm/task-suggestions/{suggestion_id}/approval-link",
        risk_tier="human_confirm",
        side_effects=True,
        description="Create a fragment-only handoff link for Brandon's authenticated review.",
    ),
    AgentAction(
        id="crm.task_suggestions.dismiss_proposal",
        method="POST",
        path="/api/v1/agent-control/crm/task-suggestions/{suggestion_id}/dismiss-proposal",
        risk_tier="operator_review",
        side_effects=True,
        description="Record a non-authoritative dismissal proposal for Brandon review.",
    ),
    AgentAction(
        id="context.events.ingest",
        method="POST",
        path="/api/v1/agent-control/context/events/batch",
        risk_tier="auto_silent",
        side_effects=True,
        description="Persist redacted Sydney conversation evidence idempotently.",
    ),
    AgentAction(
        id="context.sessions.reconcile",
        method="POST",
        path="/api/v1/agent-control/context/sessions/reconcile",
        risk_tier="auto_silent",
        side_effects=True,
        description="Verify content-free Sydney session counts and ordered hashes.",
    ),
    AgentAction(
        id="context.retrieve",
        method="POST",
        path="/api/v1/agent-control/context/retrieve",
        risk_tier="auto_silent",
        side_effects=False,
        description="Retrieve a bounded source-linked Sydney context packet.",
    ),
    AgentAction(
        id="context.history.search",
        method="POST",
        path="/api/v1/agent-control/context/history/search",
        risk_tier="auto_silent",
        side_effects=False,
        description="Search retained Sydney conversation evidence.",
    ),
    AgentAction(
        id="context.runs.start",
        method="POST",
        path="/api/v1/agent-control/context/runs/start",
        risk_tier="auto_silent",
        side_effects=True,
        description="Create or replay one durable Sydney continuation run.",
    ),
    AgentAction(
        id="context.runs.update",
        method="POST",
        path="/api/v1/agent-control/context/runs/update",
        risk_tier="auto_silent",
        side_effects=True,
        description="Record one validated Sydney continuation transition.",
    ),
    AgentAction(
        id="context.runs.claim",
        method="POST",
        path="/api/v1/agent-control/context/runs/claim",
        risk_tier="auto_silent",
        side_effects=True,
        description="Lease bounded eligible Sydney continuation runs.",
    ),
    AgentAction(
        id="context.tools.start",
        method="POST",
        path="/api/v1/agent-control/context/tools/start",
        risk_tier="auto_silent",
        side_effects=True,
        description="Record a hashed tool invocation before execution.",
    ),
    AgentAction(
        id="context.tools.update",
        method="POST",
        path="/api/v1/agent-control/context/tools/update",
        risk_tier="auto_silent",
        side_effects=True,
        description="Record the bounded outcome of a known tool invocation.",
    ),
    AgentAction(
        id="context.health.read",
        method="GET",
        path="/api/v1/agent-control/context/health",
        risk_tier="auto_silent",
        side_effects=False,
        description="Read content-free Sydney context health aggregates.",
    ),
    AgentAction(
        id="crm.command_contacts.search",
        method="POST",
        path="/api/v1/agent-control/crm/command-contacts/search",
        risk_tier="auto_silent",
        side_effects=False,
        description="Search Command contacts only; never Google Contacts or the admin UI.",
    ),
    AgentAction(
        id="crm.command_contact_audiences.preview",
        method="POST",
        path="/api/v1/agent-control/crm/command-contact-audiences/preview",
        risk_tier="auto_silent",
        side_effects=False,
        description="Preview a masked, checksum-bound Command contact audience without sending.",
    ),
]


def _safe_limit(limit: int | None) -> int:
    default = settings.AGENT_CONTROL_RECENT_LIMIT
    return min(max(limit or default, 1), 25)


def _safe_page_size(page_size: int) -> int:
    return min(max(page_size, 1), 25)


def _mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    _, domain = email.split("@", 1)
    return f"***@{domain}"


def _mask_phone(phone: str | None) -> str | None:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return phone
    return f"***-***-{digits[-4:]}"


def _truncate_text(value: str | None, max_length: int = 1000) -> str:
    if not value:
        return ""
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 3]}..."


def _safe_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): _sanitize_metadata_value(value) for key, value in parsed.items()}


def _sanitize_metadata_value(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate_text(value, max_length=500)
    if isinstance(value, dict):
        return {
            str(key): _sanitize_metadata_value(inner) for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_metadata_value(item) for item in value[:20]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _truncate_text(str(value), max_length=500)


async def _audit(
    db: AsyncSession,
    *,
    request: Request,
    actor: str,
    action_id: str,
    request_meta: dict[str, Any] | None = None,
    response_meta: dict[str, Any] | None = None,
) -> None:
    await write_agent_audit(
        db,
        request=request,
        actor=actor,
        action_id=action_id,
        status_code=200,
        allowed=True,
        request_meta=request_meta or {},
        response_meta=response_meta or {},
    )


@router.get("/status", response_model=AgentStatusResponse)
async def agent_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> AgentStatusResponse:
    response = AgentStatusResponse(
        status="ok",
        service="brandon-re-api",
        environment="production",
        capabilities=[action.id for action in AGENT_ACTIONS],
        risk_tier="workspace_action_foundation",
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="status.read",
        response_meta={"capabilities": response.capabilities},
    )
    return response


@router.get("/workspace/status")
async def workspace_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
):
    await load_workspace_refresh_token_from_db(db)
    response = await get_workspace_connection_status_bounded(
        deadline_seconds=settings.INTEGRATION_PROVIDER_DEADLINE_SECONDS,
        socket_timeout_seconds=(settings.INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS),
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.status.read",
        response_meta={
            "configured": bool(response.get("configured")),
            "connected": bool(response.get("connected")),
        },
    )
    return response


@router.post("/workspace/gmail/search", response_model=WorkspaceGmailSearchResponse)
async def workspace_gmail_search(
    payload: WorkspaceGmailSearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceGmailSearchResponse:
    await load_workspace_refresh_token_from_db(db)
    safe_page_size = _safe_page_size(payload.page_size)
    messages = search_gmail_messages(payload.query, page_size=safe_page_size)
    response = WorkspaceGmailSearchResponse(
        messages=[WorkspaceGmailMessageSummary(**item) for item in messages]
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.gmail.search",
        request_meta={"query_length": len(payload.query), "page_size": safe_page_size},
        response_meta={
            "count": len(response.messages),
            "message_ids": [item.id for item in response.messages],
            "thread_ids": [item.thread_id for item in response.messages],
        },
    )
    return response


@router.post("/workspace/gmail/thread", response_model=WorkspaceGmailThreadResponse)
async def workspace_gmail_thread(
    payload: WorkspaceGmailThreadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceGmailThreadResponse:
    await load_workspace_refresh_token_from_db(db)
    result = get_gmail_thread(payload.thread_id, max_body_chars=payload.max_body_chars)
    response = WorkspaceGmailThreadResponse(
        thread_id=result.get("thread_id", payload.thread_id),
        messages=[
            WorkspaceGmailThreadMessage(**item) for item in result.get("messages", [])
        ],
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.gmail.thread.read",
        request_meta={
            "thread_id": payload.thread_id,
            "max_body_chars": payload.max_body_chars,
        },
        response_meta={
            "thread_id": response.thread_id,
            "count": len(response.messages),
            "message_ids": [item.id for item in response.messages],
            "body_lengths": [len(item.body_text) for item in response.messages],
            "truncated_count": sum(
                1 for item in response.messages if item.body_truncated
            ),
        },
    )
    return response


@router.post("/workspace/gmail/draft", response_model=WorkspaceGmailDraftResponse)
async def workspace_gmail_draft(
    payload: WorkspaceGmailDraftRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceGmailDraftResponse:
    await load_workspace_refresh_token_from_db(db)
    result = create_gmail_draft(
        to=payload.to,
        subject=payload.subject,
        body_text=payload.body_text,
        cc=payload.cc,
        bcc=payload.bcc,
    )
    response = WorkspaceGmailDraftResponse(
        draft_id=result.get("id", ""),
        message_id=result.get("message_id", ""),
        to_count=len(payload.to),
        subject=payload.subject,
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.gmail.draft.create",
        request_meta={
            "to_count": len(payload.to),
            "cc_count": len(payload.cc),
            "bcc_count": len(payload.bcc),
            "subject_length": len(payload.subject),
            "body_length": len(payload.body_text),
        },
        response_meta={
            "draft_id": response.draft_id,
            "message_id": response.message_id,
        },
    )
    return response


@router.post("/workspace/gmail/send", response_model=WorkspaceGmailSendResponse)
async def workspace_gmail_send(
    payload: WorkspaceGmailSendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceGmailSendResponse:
    if not payload.confirmed_by_brandon:
        raise HTTPException(
            status_code=422,
            detail="Direct Gmail send requires confirmed_by_brandon=true.",
        )

    try:
        result = await send_agent_gmail_with_origin(
            db=db,
            payload=payload,
            request=request,
            actor=agent["actor"],
        )
    except GmailSendConflict as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.category,
        ) from None
    except RuntimeError as error:
        if str(error) == "gmail_send_delivery_uncertain":
            raise HTTPException(
                status_code=503,
                detail="gmail_send_delivery_uncertain",
            ) from None
        raise
    response = WorkspaceGmailSendResponse(
        request_id=result.request_id,
        message_id=result.message_id or "",
        thread_id=result.thread_id or "",
        delivery_state=result.delivery_state,
        replayed=result.replayed,
        to_count=len(payload.to),
        subject=payload.subject,
    )
    return response


@router.post(
    "/gmail/missing-message/acknowledge",
    response_model=GmailMissingMessageAcknowledgeResponse,
)
async def acknowledge_gmail_missing_message(
    payload: GmailMissingMessageAcknowledgeRequest,
    request: Request,
    administrator_subject: AdminSubject,
    db: AsyncSession = Depends(get_db),
) -> GmailMissingMessageAcknowledgeResponse:
    try:
        incident = await acknowledge_missing_message_incident(
            db,
            request=request,
            administrator_id=int(administrator_subject),
            incident_id=payload.incident_id,
            account_id=payload.account_id,
            run_id=payload.run_id,
            gmail_message_id=payload.gmail_message_id,
            gmail_thread_id=payload.gmail_thread_id,
            expected_start_history_id=payload.expected_start_history_id,
            expected_page_number=payload.expected_page_number,
            expected_request_page_token=payload.expected_request_page_token,
            expected_version=payload.expected_version,
            reason=payload.reason,
            backfill_request_id=payload.backfill_request_id,
            expected_reseed_history_id=payload.expected_reseed_history_id,
        )
    except GmailMissingMessageAcknowledgementError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.category,
        ) from None
    return GmailMissingMessageAcknowledgeResponse(
        incident_id=incident.id,
        state="acknowledged",
        version=incident.version,
        run_id=incident.run_id,
    )


@router.get(
    "/gmail/missing-message/incidents/{incident_id}",
    response_model=GmailMissingMessageIncidentDetail,
)
async def get_gmail_missing_message_incident(
    incident_id: UUID,
    _administrator_subject: AdminSubject,
    db: AsyncSession = Depends(get_db),
) -> GmailMissingMessageIncidentDetail:
    incident = await db.scalar(
        select(GmailMissingMessageIncident).where(
            GmailMissingMessageIncident.id == incident_id,
            GmailMissingMessageIncident.state == "pending",
        )
    )
    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="gmail_missing_message_incident_not_found",
        )
    run = await db.scalar(
        select(GmailSyncRun).where(
            GmailSyncRun.id == incident.run_id,
            GmailSyncRun.account_id == incident.account_id,
        )
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail="gmail_missing_message_incident_not_found",
        )
    backfill_request = None
    if run.run_kind == "backfill":
        backfill_request = await db.scalar(
            select(GmailBackfillRequest).where(
                GmailBackfillRequest.run_id == run.id,
                GmailBackfillRequest.account_id == incident.account_id,
            )
        )
        if backfill_request is None:
            raise HTTPException(
                status_code=404,
                detail="gmail_missing_message_incident_not_found",
            )
    return GmailMissingMessageIncidentDetail(
        incident_id=incident.id,
        account_id=incident.account_id,
        run_id=incident.run_id,
        gmail_message_id=incident.gmail_message_id,
        gmail_thread_id=incident.gmail_thread_id,
        expected_start_history_id=incident.start_history_id,
        expected_page_number=incident.page_number,
        expected_request_page_token=incident.request_page_token,
        expected_version=incident.version,
        backfill_request_id=(
            backfill_request.id if backfill_request is not None else None
        ),
        expected_reseed_history_id=(
            backfill_request.reseed_history_id if backfill_request is not None else None
        ),
    )


@router.post("/workspace/drive/search", response_model=WorkspaceDriveSearchResponse)
async def workspace_drive_search(
    payload: WorkspaceDriveSearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceDriveSearchResponse:
    await load_workspace_refresh_token_from_db(db)
    safe_page_size = _safe_page_size(payload.page_size)
    files = search_drive_files(payload.query, page_size=safe_page_size)
    response = WorkspaceDriveSearchResponse(
        files=[WorkspaceDriveFileSummary(**item) for item in files]
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.drive.search",
        request_meta={"query_length": len(payload.query), "page_size": safe_page_size},
        response_meta={
            "count": len(response.files),
            "ids": [item.id for item in response.files],
        },
    )
    return response


@router.post("/workspace/drive/file", response_model=WorkspaceDriveFileReadResponse)
async def workspace_drive_file_read(
    payload: WorkspaceDriveFileReadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceDriveFileReadResponse:
    await load_workspace_refresh_token_from_db(db)
    result = read_drive_file(payload.file_id, max_chars=payload.max_chars)
    response = WorkspaceDriveFileReadResponse(**result)
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.drive.file.read",
        request_meta={"file_id": payload.file_id, "max_chars": payload.max_chars},
        response_meta={
            "file_id": response.id,
            "mime_type": response.mime_type,
            "content_length": len(response.content_text),
            "truncated": response.truncated,
        },
    )
    return response


@router.post("/workspace/docs/create", response_model=WorkspaceDocsCreateResponse)
async def workspace_docs_create(
    payload: WorkspaceDocsCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceDocsCreateResponse:
    await load_workspace_refresh_token_from_db(db)
    result = create_google_doc(payload.title, payload.body_text)
    response = WorkspaceDocsCreateResponse(**result)
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.docs.create",
        request_meta={
            "title_length": len(payload.title),
            "body_length": len(payload.body_text),
        },
        response_meta={"document_id": response.document_id},
    )
    return response


@router.post(
    "/workspace/calendar/events", response_model=WorkspaceCalendarEventsResponse
)
async def workspace_calendar_events(
    payload: WorkspaceCalendarEventsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceCalendarEventsResponse:
    await load_workspace_refresh_token_from_db(db)
    safe_page_size = _safe_page_size(payload.page_size)
    events = list_calendar_events(
        payload.time_min,
        payload.time_max,
        page_size=safe_page_size,
        calendar_id=payload.calendar_id,
    )
    response = WorkspaceCalendarEventsResponse(
        events=[WorkspaceCalendarEventSummary(**item) for item in events]
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.calendar.events.read",
        request_meta={
            "time_min": payload.time_min.isoformat(),
            "time_max": payload.time_max.isoformat(),
            "page_size": safe_page_size,
            "calendar_id": payload.calendar_id,
        },
        response_meta={
            "count": len(response.events),
            "ids": [item.id for item in response.events],
        },
    )
    return response


@router.post(
    "/workspace/calendar/event/create",
    response_model=WorkspaceCalendarCreateEventResponse,
)
async def workspace_calendar_event_create(
    payload: WorkspaceCalendarCreateEventRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceCalendarCreateEventResponse:
    if not payload.confirmed_by_brandon:
        raise HTTPException(
            status_code=422,
            detail="Calendar event creation requires confirmed_by_brandon=true.",
        )

    await load_workspace_refresh_token_from_db(db)
    result = create_workspace_calendar_event(
        summary=payload.summary,
        start=payload.start,
        end=payload.end,
        attendees=payload.attendees,
        location=payload.location,
        description=payload.description,
        calendar_id=payload.calendar_id,
    )
    response = WorkspaceCalendarCreateEventResponse(
        event_id=result.get("event_id", ""),
        html_link=result.get("html_link", ""),
        attendee_count=len(payload.attendees),
        summary=payload.summary,
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.calendar.event.create",
        request_meta={
            "summary_length": len(payload.summary),
            "start": payload.start.isoformat(),
            "end": payload.end.isoformat(),
            "attendee_count": len(payload.attendees),
            "location_length": len(payload.location),
            "description_length": len(payload.description),
            "calendar_id": payload.calendar_id,
            "confirmed_by_brandon": payload.confirmed_by_brandon,
            "confirmation_note_length": len(payload.confirmation_note),
        },
        response_meta={"event_id": response.event_id},
    )
    return response


@router.post(
    "/workspace/contacts/search", response_model=WorkspaceContactsSearchResponse
)
async def workspace_contacts_search(
    payload: WorkspaceContactsSearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceContactsSearchResponse:
    await load_workspace_refresh_token_from_db(db)
    safe_page_size = _safe_page_size(payload.page_size)
    contacts = search_contacts(payload.query, page_size=safe_page_size)
    response = WorkspaceContactsSearchResponse(
        contacts=[WorkspaceContactSummary(**item) for item in contacts]
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.contacts.search",
        request_meta={"query_length": len(payload.query), "page_size": safe_page_size},
        response_meta={
            "count": len(response.contacts),
            "resource_names": [item.resource_name for item in response.contacts],
        },
    )
    return response


@router.post("/workspace/sheets/append", response_model=WorkspaceSheetsAppendResponse)
async def workspace_sheets_append(
    payload: WorkspaceSheetsAppendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> WorkspaceSheetsAppendResponse:
    await load_workspace_refresh_token_from_db(db)
    result = append_sheet_values(
        spreadsheet_id=payload.spreadsheet_id,
        range_name=payload.range_name,
        values=payload.values,
    )
    response = WorkspaceSheetsAppendResponse(**result)
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.sheets.append",
        request_meta={
            "spreadsheet_id": payload.spreadsheet_id,
            "range_name": payload.range_name,
            "row_count": len(payload.values),
            "cell_count": sum(len(row) for row in payload.values),
        },
        response_meta={
            "updated_range": response.updated_range,
            "updated_rows": response.updated_rows,
            "updated_cells": response.updated_cells,
        },
    )
    return response


@router.get("/actions", response_model=AgentActionsResponse)
async def list_agent_actions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> AgentActionsResponse:
    response = AgentActionsResponse(actions=AGENT_ACTIONS)
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="actions.read",
        response_meta={
            "count": len(response.actions),
            "ids": [action.id for action in response.actions],
        },
    )
    return response


@router.get("/leads/recent", response_model=RecentLeadsResponse)
async def recent_leads(
    request: Request,
    limit: int | None = Query(default=None, ge=1),
    lead_type: str | None = None,
    routing_status: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> RecentLeadsResponse:
    safe_limit = _safe_limit(limit)
    statement = select(Lead).order_by(desc(Lead.created_at)).limit(safe_limit)
    if lead_type:
        statement = statement.where(Lead.lead_type == lead_type)
    if routing_status:
        statement = statement.where(Lead.routing_status == routing_status)

    result = await db.execute(statement)
    leads = result.scalars().all()
    response = RecentLeadsResponse(
        leads=[
            AgentLeadSummary(
                id=lead.id,
                name=lead.name,
                email=_mask_email(lead.email),
                phone=_mask_phone(lead.phone),
                source=lead.source,
                lead_type=lead.lead_type,
                routing_status=lead.routing_status,
                notes=_truncate_text(lead.notes),
                metadata=_safe_metadata(lead.metadata_json),
                created_at=lead.created_at,
                updated_at=lead.updated_at,
            )
            for lead in leads
        ]
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="leads.recent.read",
        request_meta={
            "limit": safe_limit,
            "lead_type": lead_type,
            "routing_status": routing_status,
        },
        response_meta={
            "count": len(response.leads),
            "ids": [lead.id for lead in response.leads],
        },
    )
    return response


@router.get("/bookings/recent", response_model=RecentBookingsResponse)
async def recent_bookings(
    request: Request,
    limit: int | None = Query(default=None, ge=1),
    meeting_type: str | None = None,
    context: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: dict = Depends(require_agent_control),
) -> RecentBookingsResponse:
    safe_limit = _safe_limit(limit)
    statement = select(Booking).order_by(desc(Booking.created_at)).limit(safe_limit)
    if meeting_type:
        statement = statement.where(Booking.meeting_type == meeting_type)
    if context:
        statement = statement.where(Booking.context == context)

    result = await db.execute(statement)
    bookings = result.scalars().all()
    response = RecentBookingsResponse(
        bookings=[
            AgentBookingSummary(
                id=booking.id,
                lead_id=booking.lead_id,
                name=booking.name,
                email=_mask_email(booking.email),
                phone=_mask_phone(booking.phone),
                meeting_type=booking.meeting_type,
                context=booking.context,
                location=_truncate_text(booking.location, max_length=500),
                scheduled_at=booking.scheduled_at,
                has_google_event=bool(booking.google_event_id),
                notes=_truncate_text(booking.notes),
                created_at=booking.created_at,
            )
            for booking in bookings
        ]
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="bookings.recent.read",
        request_meta={
            "limit": safe_limit,
            "meeting_type": meeting_type,
            "context": context,
        },
        response_meta={
            "count": len(response.bookings),
            "ids": [booking.id for booking in response.bookings],
        },
    )
    return response
