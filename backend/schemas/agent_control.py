from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


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


class WorkspaceGmailDraftRequest(BaseModel):
    to: list[str] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=300)
    body_text: str = Field(min_length=1, max_length=20000)
    cc: list[str] = Field(default_factory=list, max_length=20)
    bcc: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("to", "cc", "bcc")
    @classmethod
    def clean_recipients(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value and value.strip()]
        if not cleaned and values:
            raise ValueError("Recipient entries cannot be blank.")
        return cleaned


class WorkspaceGmailDraftResponse(BaseModel):
    draft_id: str
    message_id: str
    to_count: int
    subject: str


class WorkspaceGmailSendRequest(WorkspaceGmailDraftRequest):
    confirmed_by_brandon: bool = False
    confirmation_note: str = Field(default="", max_length=500)


class WorkspaceGmailSendResponse(BaseModel):
    message_id: str
    thread_id: str
    to_count: int
    subject: str


class WorkspaceDriveSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    page_size: int = Field(default=10, ge=1, le=100)


class WorkspaceDriveFileSummary(BaseModel):
    id: str
    name: str
    mime_type: str
    web_view_link: str
    modified_time: str


class WorkspaceDriveSearchResponse(BaseModel):
    files: list[WorkspaceDriveFileSummary]


class WorkspaceDocsCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body_text: str = Field(default="", max_length=50000)


class WorkspaceDocsCreateResponse(BaseModel):
    document_id: str
    title: str
    url: str


SheetCellValue = str | int | float | bool | None


class WorkspaceSheetsAppendRequest(BaseModel):
    spreadsheet_id: str = Field(min_length=1, max_length=300)
    range_name: str = Field(min_length=1, max_length=300)
    values: list[list[SheetCellValue]] = Field(min_length=1, max_length=100)

    @field_validator("values")
    @classmethod
    def limit_cells(cls, values: list[list[SheetCellValue]]) -> list[list[SheetCellValue]]:
        for row in values:
            if len(row) > 50:
                raise ValueError("Rows cannot contain more than 50 cells.")
        return values


class WorkspaceSheetsAppendResponse(BaseModel):
    spreadsheet_id: str
    updated_range: str
    updated_rows: int
    updated_columns: int
    updated_cells: int
