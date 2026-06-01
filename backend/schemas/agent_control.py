from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AgentAction(BaseModel):
    id: str
    method: str
    path: str
    risk_tier: str
    side_effects: bool
    description: str


class AgentActionsResponse(BaseModel):
    actions: list[AgentAction]


class AgentStatusResponse(BaseModel):
    status: str
    service: str
    environment: str
    capabilities: list[str]
    risk_tier: str


class AgentLeadSummary(BaseModel):
    id: int
    name: str | None
    email: str | None
    phone: str | None
    source: str | None
    lead_type: str | None
    routing_status: str
    notes: str
    metadata: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None


class RecentLeadsResponse(BaseModel):
    leads: list[AgentLeadSummary]


class AgentBookingSummary(BaseModel):
    id: int
    lead_id: int | None
    name: str
    email: str | None
    phone: str | None
    meeting_type: str
    context: str
    location: str | None
    scheduled_at: datetime
    has_google_event: bool
    notes: str
    created_at: datetime | None


class RecentBookingsResponse(BaseModel):
    bookings: list[AgentBookingSummary]
