import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.agent_control import require_agent_control
from models.booking import Booking
from models.lead import Lead
from schemas.agent_control import (
    AgentAction,
    AgentActionsResponse,
    AgentBookingSummary,
    AgentLeadSummary,
    AgentStatusResponse,
    RecentBookingsResponse,
    RecentLeadsResponse,
    WorkspaceDocsCreateRequest,
    WorkspaceDocsCreateResponse,
    WorkspaceDriveFileSummary,
    WorkspaceDriveSearchRequest,
    WorkspaceDriveSearchResponse,
    WorkspaceGmailDraftRequest,
    WorkspaceGmailDraftResponse,
    WorkspaceGmailSendRequest,
    WorkspaceGmailSendResponse,
    WorkspaceSheetsAppendRequest,
    WorkspaceSheetsAppendResponse,
)
from services.agent_control_audit import write_agent_audit
from services.workspace_service import (
    append_sheet_values,
    create_gmail_draft,
    create_google_doc,
    get_workspace_connection_status,
    search_drive_files,
    send_gmail_message,
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
        return {str(key): _sanitize_metadata_value(inner) for key, inner in value.items()}
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
    response = get_workspace_connection_status()
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
        response_meta={"draft_id": response.draft_id, "message_id": response.message_id},
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

    await load_workspace_refresh_token_from_db(db)
    result = send_gmail_message(
        to=payload.to,
        subject=payload.subject,
        body_text=payload.body_text,
        cc=payload.cc,
        bcc=payload.bcc,
    )
    response = WorkspaceGmailSendResponse(
        message_id=result.get("id", ""),
        thread_id=result.get("thread_id", ""),
        to_count=len(payload.to),
        subject=payload.subject,
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="workspace.gmail.send",
        request_meta={
            "to_count": len(payload.to),
            "cc_count": len(payload.cc),
            "bcc_count": len(payload.bcc),
            "subject_length": len(payload.subject),
            "body_length": len(payload.body_text),
            "confirmed_by_brandon": payload.confirmed_by_brandon,
            "confirmation_note_length": len(payload.confirmation_note),
        },
        response_meta={"message_id": response.message_id, "thread_id": response.thread_id},
    )
    return response


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
        response_meta={"count": len(response.files), "ids": [item.id for item in response.files]},
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
        request_meta={"title_length": len(payload.title), "body_length": len(payload.body_text)},
        response_meta={"document_id": response.document_id},
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
        response_meta={"count": len(response.actions), "ids": [action.id for action in response.actions]},
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
        request_meta={"limit": safe_limit, "lead_type": lead_type, "routing_status": routing_status},
        response_meta={"count": len(response.leads), "ids": [lead.id for lead in response.leads]},
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
        request_meta={"limit": safe_limit, "meeting_type": meeting_type, "context": context},
        response_meta={"count": len(response.bookings), "ids": [booking.id for booking in response.bookings]},
    )
    return response
