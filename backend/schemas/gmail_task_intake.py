"""Strict public shapes for Gmail-originated task review payloads."""

from datetime import datetime
import re
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


_RFC3339_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
DatabaseInteger: TypeAlias = Annotated[
    int,
    Field(ge=1, le=2_147_483_647, strict=True),
]
TaskPriority: TypeAlias = Literal["low", "normal", "high"]
SuggestionState: TypeAlias = Literal[
    "needs_clarification",
    "possible_duplicate",
    "pending_review",
    "approved",
    "dismissed",
    "applied",
    "failed",
]
ClarificationState: TypeAlias = Literal[
    "not_required",
    "pending",
    "answered",
    "timed_out",
    "manual_review_required",
]
BlockerCode: TypeAlias = Literal[
    "missing_required_field",
    "ambiguous_due_at",
    "ambiguous_contact",
    "multiple_actions",
    "unsupported_owner",
    "unsupported_link",
]


class GmailTaskPayload(BaseModel):
    """The only initial task shape eligible for authenticated CRM review."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    priority: TaskPriority = "normal"
    due_at: datetime | None = None
    contact_id: DatabaseInteger | None = None
    status: Literal["open"] = "open"

    @field_validator("title")
    @classmethod
    def require_visible_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title cannot be blank")
        return title

    @field_validator("due_at", mode="before")
    @classmethod
    def reject_non_rfc3339_due_input(cls, value: object) -> object:
        if value is None or isinstance(value, datetime):
            return value
        if type(value) is str and _RFC3339_DATETIME_PATTERN.fullmatch(value):
            return value
        raise ValueError("due_at must be an RFC 3339 datetime")

    @field_validator("due_at")
    @classmethod
    def require_due_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("due_at must include a UTC offset")
        return value


class GmailMissingMessageAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    account_id: UUID
    run_id: UUID
    gmail_message_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[!-~]+$",
    )
    gmail_thread_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[!-~]+$",
    )
    expected_start_history_id: str = Field(
        min_length=1,
        max_length=20,
        pattern=r"^[1-9][0-9]*$",
    )
    expected_page_number: int = Field(ge=1, le=1_000_000, strict=True)
    expected_request_page_token: str | None = Field(
        min_length=1,
        max_length=1024,
        pattern=r"^[!-~]+$",
    )
    expected_version: int = Field(ge=1, le=2_147_483_647, strict=True)
    backfill_request_id: UUID | None = None
    expected_reseed_history_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        pattern=r"^[1-9][0-9]*$",
    )
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def require_acknowledgement_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("reason cannot be blank")
        return reason


class GmailMissingMessageAcknowledgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    state: Literal["acknowledged"]
    version: int
    run_id: UUID


class GmailMissingMessageIncidentDetail(BaseModel):
    """Body-free values required to acknowledge one exact incident."""

    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    account_id: UUID
    run_id: UUID
    gmail_message_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[!-~]+$",
    )
    gmail_thread_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[!-~]+$",
    )
    expected_start_history_id: str = Field(
        min_length=1,
        max_length=20,
        pattern=r"^[1-9][0-9]*$",
    )
    expected_page_number: int = Field(ge=1, le=1_000_000, strict=True)
    expected_request_page_token: str | None = Field(
        min_length=1,
        max_length=1024,
        pattern=r"^[!-~]+$",
    )
    expected_version: int = Field(ge=1, le=2_147_483_647, strict=True)
    backfill_request_id: UUID | None = None
    expected_reseed_history_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        pattern=r"^[1-9][0-9]*$",
    )


__all__ = [
    "BlockerCode",
    "ClarificationState",
    "GmailTaskPayload",
    "GmailMissingMessageAcknowledgeRequest",
    "GmailMissingMessageAcknowledgeResponse",
    "GmailMissingMessageIncidentDetail",
    "SuggestionState",
    "TaskPriority",
]
