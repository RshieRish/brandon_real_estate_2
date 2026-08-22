"""Strict HTTP contracts for Sydney CRM task review surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.gmail_task_intake import GmailTaskPayload


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SuggestionVersion(StrictModel):
    expected_version: int = Field(ge=1, le=2_147_483_647, strict=True)
    expected_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaskSuggestionSummary(StrictModel):
    id: UUID
    source_type: Literal["gmail_message", "sydney_chat"]
    title: str
    description: str
    priority: Literal["low", "normal", "high"]
    due_at: datetime | None
    contact_id: int | None
    status: Literal["open"]
    state: Literal[
        "needs_clarification",
        "possible_duplicate",
        "pending_review",
        "approved",
        "dismissed",
        "applied",
        "failed",
    ]
    clarification_state: Literal[
        "not_required",
        "pending",
        "answered",
        "timed_out",
        "manual_review_required",
    ]
    blocker_codes: list[str]
    payload_hash: str
    version: int
    applied_task_id: int | None
    created_at: datetime
    updated_at: datetime


class TaskSuggestionList(StrictModel):
    suggestions: list[TaskSuggestionSummary]


class CRMTaskSummary(StrictModel):
    id: int
    contact_id: int | None
    title: str
    description: str
    status: str
    priority: str
    due_at: datetime | None
    version: int
    created_at: datetime | None
    updated_at: datetime | None


class CRMTaskList(StrictModel):
    tasks: list[CRMTaskSummary]


class TaskSuggestionEditRequest(SuggestionVersion):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    priority: Literal["low", "normal", "high"] | None = None
    due_at: datetime | None = None
    contact_id: int | None = Field(default=None, ge=1, le=2_147_483_647, strict=True)
    resolve_owner_as_brandon: bool = Field(default=False, strict=True)
    create_without_unsupported_link: bool = Field(default=False, strict=True)
    accept_current_task_details: bool = Field(default=False, strict=True)
    treat_as_single_action: bool = Field(default=False, strict=True)
    confirm_not_duplicate: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def require_change(self):
        task_fields = {"title", "description", "priority", "due_at", "contact_id"}
        choices = {
            "resolve_owner_as_brandon",
            "create_without_unsupported_link",
            "accept_current_task_details",
            "treat_as_single_action",
            "confirm_not_duplicate",
        }
        if not (
            self.model_fields_set.intersection(task_fields)
            or any(getattr(self, field) for field in choices)
        ):
            raise ValueError("at least one task field is required")
        for field in {"title", "description", "priority"}:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    @field_validator("title")
    @classmethod
    def visible_title(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("due_at")
    @classmethod
    def aware_due_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include a UTC offset")
        return value


class TaskSuggestionPreviewRequest(SuggestionVersion):
    pass


class TaskSuggestionPreviewResponse(StrictModel):
    suggestion_id: UUID
    suggestion_version: int
    payload_hash: str
    task: GmailTaskPayload


class ApprovalPrepareResponse(TaskSuggestionPreviewResponse):
    approval: str
    expires_at: datetime


class HandoffExchangeRequest(SuggestionVersion):
    handoff: object


class ApprovalRequest(SuggestionVersion):
    approval: object
    request_id: UUID
    client_timezone: str = Field(default="UTC", min_length=1, max_length=64)


class ApprovalResponse(StrictModel):
    suggestion_id: UUID
    suggestion_version: int
    task_id: int
    request_id: UUID
    replayed: bool


class DismissSuggestionRequest(SuggestionVersion):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason cannot be blank")
        return value


class AgentClarificationAnswerRequest(StrictModel):
    code: object
    expected_version: int = Field(ge=1, le=2_147_483_647, strict=True)
    answer: dict[str, Any] = Field(max_length=12)


class AgentClarificationAnswerResponse(StrictModel):
    suggestion_id: UUID
    suggestion_version: int
    next_clarification_id: UUID | None
    approval_link: str | None


class AgentTaskDraftRequest(StrictModel):
    request_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    priority: Literal["low", "normal", "high"] = "normal"
    due_at: datetime | None = None
    contact_id: int | None = Field(default=None, ge=1, le=2_147_483_647, strict=True)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title cannot be blank")
        return value

    @field_validator("due_at")
    @classmethod
    def aware_due_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include a UTC offset")
        return value


class AgentApprovalLinkRequest(SuggestionVersion):
    pass


class AgentApprovalLinkResponse(StrictModel):
    suggestion_id: UUID
    suggestion_version: int
    approval_link: str
    expires_at: datetime


class AgentDismissProposalRequest(StrictModel):
    request_id: UUID
    expected_version: int = Field(ge=1, le=2_147_483_647, strict=True)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_proposal_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason cannot be blank")
        return value


class AgentDismissProposalResponse(StrictModel):
    suggestion_id: UUID
    suggestion_version: int
    request_id: UUID
    replayed: bool


class GmailTaskBackfillRequest(StrictModel):
    account_id: UUID
    reason: str = Field(min_length=1, max_length=500)
    window_start: datetime
    window_end: datetime

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason cannot be blank")
        return value

    @model_validator(mode="after")
    def bounded_window(self):
        from datetime import timedelta

        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("backfill bounds must include UTC offsets")
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        if self.window_end - self.window_start > timedelta(days=7):
            raise ValueError("backfill window cannot exceed seven days")
        return self


class GmailTaskReprocessRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=500)
    suppression_id: UUID | None = None

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason cannot be blank")
        return value


class GmailSendIntentReconcileRequest(StrictModel):
    account_id: UUID
    expected_state: Literal["delivery_uncertain"]
    expected_version: int = Field(ge=1, le=2_147_483_647, strict=True)
    outcome: Literal["delivered", "not_delivered"]
    reason: str = Field(min_length=1, max_length=500)
    candidate_message_id: str | None = Field(default=None, min_length=1, max_length=255)
    candidate_thread_id: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason cannot be blank")
        return value

    @model_validator(mode="after")
    def provider_ids_only_for_delivery(self):
        provided = (
            self.candidate_message_id is not None
            or self.candidate_thread_id is not None
        )
        if self.outcome == "delivered" and (
            self.candidate_message_id is None or self.candidate_thread_id is None
        ):
            raise ValueError("delivered reconciliation requires both provider IDs")
        if self.outcome == "not_delivered" and provided:
            raise ValueError("not_delivered reconciliation cannot include provider IDs")
        return self


class TelegramReconcileRequest(StrictModel):
    expected_state: Literal["failed", "delivery_uncertain"]
    outcome: Literal["delivered", "not_delivered"]
    reason: str = Field(min_length=1, max_length=500)
    observed_chat_id: str | None = Field(default=None, min_length=1, max_length=32)
    observed_message_id: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason cannot be blank")
        return value

    @model_validator(mode="after")
    def observed_ids_only_for_delivery(self):
        provided = (
            self.observed_chat_id is not None or self.observed_message_id is not None
        )
        if self.outcome == "delivered" and (
            self.observed_chat_id is None or self.observed_message_id is None
        ):
            raise ValueError("delivered reconciliation requires observed IDs")
        if self.outcome == "not_delivered" and provided:
            raise ValueError("not_delivered reconciliation cannot include observed IDs")
        return self


class TelegramRetryRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason cannot be blank")
        return value


__all__ = [name for name in globals() if name[0].isupper()]
