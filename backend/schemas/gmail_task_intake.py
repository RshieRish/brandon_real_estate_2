"""Strict public shapes for Gmail-originated task review payloads."""

from datetime import datetime
import re
from typing import Annotated, Literal, TypeAlias

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


__all__ = [
    "BlockerCode",
    "ClarificationState",
    "GmailTaskPayload",
    "SuggestionState",
    "TaskPriority",
]
