from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


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
        for value in cleaned:
            if (
                len(value) > 320
                or any(character.isspace() for character in value)
                or value.count("@") != 1
                or value.startswith("@")
                or value.endswith("@")
                or any(character in value for character in "<>\r\n")
            ):
                raise ValueError("Recipient entries must be valid email addresses.")
        return cleaned

    @field_validator("subject")
    @classmethod
    def reject_subject_header_injection(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("Subject cannot contain line breaks.")
        normalized = value.strip()
        if not normalized:
            raise ValueError("Subject cannot be blank.")
        return normalized


class WorkspaceGmailDraftResponse(BaseModel):
    draft_id: str
    message_id: str
    to_count: int
    subject: str


class WorkspaceGmailSendRequest(WorkspaceGmailDraftRequest):
    request_id: UUID
    retry_of_request_id: UUID | None = None
    confirmed_by_brandon: bool = False
    confirmation_note: str = Field(default="", max_length=500)


class WorkspaceGmailSendResponse(BaseModel):
    request_id: UUID
    message_id: str
    thread_id: str
    delivery_state: str
    replayed: bool
    to_count: int
    subject: str


class WorkspaceGmailSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    page_size: int = Field(default=10, ge=1, le=100)


class WorkspaceGmailMessageSummary(BaseModel):
    id: str
    thread_id: str
    snippet: str
    subject: str
    from_email: str
    to_email: str
    date: str


class WorkspaceGmailSearchResponse(BaseModel):
    messages: list[WorkspaceGmailMessageSummary]


class WorkspaceGmailThreadRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=300)
    max_body_chars: int = Field(default=4000, ge=500, le=20000)


class WorkspaceGmailThreadMessage(WorkspaceGmailMessageSummary):
    body_text: str
    body_truncated: bool = False


class WorkspaceGmailThreadResponse(BaseModel):
    thread_id: str
    messages: list[WorkspaceGmailThreadMessage]


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


class WorkspaceDriveFileReadRequest(BaseModel):
    file_id: str = Field(min_length=1, max_length=300)
    max_chars: int = Field(default=4000, ge=500, le=20000)


class WorkspaceDriveFileReadResponse(BaseModel):
    id: str
    name: str
    mime_type: str
    web_view_link: str
    modified_time: str
    content_text: str
    truncated: bool


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


class WorkspaceCalendarEventsRequest(BaseModel):
    time_min: datetime
    time_max: datetime
    page_size: int = Field(default=10, ge=1, le=100)
    calendar_id: str = Field(default="primary", min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_time_window(self):
        if self.time_max <= self.time_min:
            raise ValueError("time_max must be after time_min.")
        return self


class WorkspaceCalendarEventSummary(BaseModel):
    id: str
    summary: str
    start: str
    end: str
    location: str
    html_link: str
    attendee_count: int


class WorkspaceCalendarEventsResponse(BaseModel):
    events: list[WorkspaceCalendarEventSummary]


class WorkspaceCalendarCreateEventRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=300)
    start: datetime
    end: datetime
    attendees: list[str] = Field(min_length=1, max_length=20)
    location: str = Field(default="", max_length=1000)
    description: str = Field(default="", max_length=10000)
    calendar_id: str = Field(default="primary", min_length=1, max_length=300)
    confirmed_by_brandon: bool = False
    confirmation_note: str = Field(default="", max_length=500)

    @field_validator("attendees")
    @classmethod
    def clean_attendees(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value and value.strip()]
        if not cleaned:
            raise ValueError("At least one attendee is required.")
        return cleaned

    @model_validator(mode="after")
    def validate_event_window(self):
        if self.end <= self.start:
            raise ValueError("end must be after start.")
        return self


class WorkspaceCalendarCreateEventResponse(BaseModel):
    event_id: str
    html_link: str
    attendee_count: int
    summary: str


class WorkspaceContactsSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    page_size: int = Field(default=10, ge=1, le=100)


class WorkspaceContactSummary(BaseModel):
    resource_name: str
    display_name: str
    email_addresses: list[str]
    phone_numbers: list[str]


class WorkspaceContactsSearchResponse(BaseModel):
    contacts: list[WorkspaceContactSummary]
