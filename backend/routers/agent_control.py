import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
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
)
from services.agent_control_audit import write_agent_audit

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
]


def _safe_limit(limit: int | None) -> int:
    default = settings.AGENT_CONTROL_RECENT_LIMIT
    return min(max(limit or default, 1), 25)


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
        risk_tier="read_only_foundation",
    )
    await _audit(
        db,
        request=request,
        actor=agent["actor"],
        action_id="status.read",
        response_meta={"capabilities": response.capabilities},
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
