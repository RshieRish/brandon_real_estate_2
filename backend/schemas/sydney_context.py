"""Strict wire contracts for Sydney's durable context control plane."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

EventType = Literal[
    "user",
    "assistant",
    "tool_call",
    "tool_result",
    "approval",
    "error",
    "continuation",
    "attachment_reference",
]
RunState = Literal[
    "queued",
    "running",
    "waiting_retry",
    "succeeded",
    "blocked_side_effect",
    "terminal_failure",
]
ToolInvocationState = Literal[
    "started",
    "succeeded",
    "not_delivered",
    "delivery_uncertain",
    "failed",
]
SideEffectClass = Literal["read_only", "idempotent_write", "non_idempotent_write"]
CONTEXT_EVENT_BATCH_MAX_BYTES = 8 * 1024 * 1024
PreservedText = Annotated[str, StringConstraints(strip_whitespace=False)]


def _normalize_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UTCDateTime = Annotated[AwareDatetime, AfterValidator(_normalize_utc)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ContextEventInput(StrictModel):
    source_event_key: str = Field(min_length=1, max_length=512)
    event_type: EventType
    role: str | None = Field(default=None, max_length=32)
    occurred_at: UTCDateTime
    content: PreservedText = Field(max_length=1_000_000)
    tool_name: str | None = Field(default=None, max_length=128)
    tool_call_id: str | None = Field(default=None, max_length=255)
    provider_model: str | None = Field(default=None, max_length=128)
    token_metadata: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextEventBatchRequest(StrictModel):
    platform: str = Field(min_length=1, max_length=32)
    external_user_id: str = Field(min_length=1, max_length=255)
    external_chat_id: str = Field(min_length=1, max_length=255)
    display_label: str = Field(min_length=1, max_length=128)
    hermes_session_id: str = Field(min_length=1, max_length=255)
    logical_conversation_id: UUID
    parent_hermes_session_id: str | None = Field(default=None, max_length=255)
    continuation_reason: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    source_version: str | None = Field(default=None, max_length=128)
    events: list[ContextEventInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def bound_aggregate_wire_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
            if len(encoded) > CONTEXT_EVENT_BATCH_MAX_BYTES:
                raise ValueError("context_event_batch_too_large")
        return value


class ContextEventReceipt(StrictModel):
    event_id: UUID
    event_type: EventType
    occurred_at: UTCDateTime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContextEventBatchResponse(StrictModel):
    identity_id: UUID
    session_id: UUID
    logical_conversation_id: UUID
    event_ids: list[UUID]
    event_receipts: list[ContextEventReceipt]
    inserted_count: int = Field(ge=0)
    replayed_count: int = Field(ge=0)


class ContextSessionReconciliationRequest(StrictModel):
    identity_id: UUID
    hermes_session_id: str = Field(min_length=1, max_length=255)
    expected_event_count: int = Field(ge=0)
    expected_ordered_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContextSessionReconciliationResponse(StrictModel):
    identity_id: UUID
    session_id: UUID
    hermes_session_id: str
    event_count: int = Field(ge=0)
    ordered_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched: bool


class ContextSourceExcerpt(StrictModel):
    event_id: UUID
    logical_conversation_id: UUID | None = None
    event_type: EventType
    occurred_at: UTCDateTime
    content: PreservedText = Field(max_length=2_000)
    content_truncated: bool = False
    tool_name: str | None = None
    score: float | None = None


class ContextPacketSection(StrictModel):
    kind: Literal[
        "confirmed_facts",
        "active_state",
        "checkpoint",
        "recent_events",
        "relevant_events",
    ]
    text: PreservedText
    source_event_ids: list[UUID]
    estimated_tokens: int = Field(ge=0)


class ContextRetrieveRequest(StrictModel):
    identity_id: UUID
    logical_conversation_id: UUID
    hermes_session_id: str = Field(min_length=1, max_length=255)
    current_user_text: str = Field(min_length=1, max_length=20_000)
    token_budget: int = Field(default=16_000, ge=256, le=16_000)


class ContextPacket(StrictModel):
    identity_id: UUID
    logical_conversation_id: UUID
    rendered_context: PreservedText
    estimated_tokens: int = Field(ge=0, le=16_000)
    sections: list[ContextPacketSection]
    degraded: bool = False
    newest_event_id: UUID | None = None


class ContextHistorySearchRequest(StrictModel):
    identity_id: UUID
    query: str | None = Field(default=None, min_length=1, max_length=500)
    event_types: list[EventType] = Field(default_factory=list, max_length=8)
    started_at: UTCDateTime | None = None
    ended_at: UTCDateTime | None = None
    around_event_id: UUID | None = None
    recent_conversations: bool = False
    limit: int = Field(default=10, ge=1, le=25)
    window_size: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def require_one_search_mode(self) -> ContextHistorySearchRequest:
        if not (self.query or self.around_event_id or self.recent_conversations):
            raise ValueError("history search requires query, event, or recent mode")
        if self.started_at and self.ended_at and self.started_at > self.ended_at:
            raise ValueError("history search date range is invalid")
        return self


class ContextHistorySearchResponse(StrictModel):
    events: list[ContextSourceExcerpt]
    total: int = Field(ge=0)
    truncated: bool


class ContextRunStartRequest(StrictModel):
    identity_id: UUID
    platform_message_id: str = Field(min_length=1, max_length=255)
    inbound_event_id: UUID
    session_id: UUID
    logical_conversation_id: UUID
    terminal_deadline_at: UTCDateTime


class ContextRunUpdateRequest(StrictModel):
    run_id: UUID
    state: RunState
    lease_owner: str | None = Field(default=None, max_length=128)
    next_attempt_at: UTCDateTime | None = None
    provider_category: str | None = Field(default=None, max_length=64)
    error_code: str | None = Field(default=None, max_length=64)
    parsed_retry_delay_seconds: float | None = Field(default=None, ge=0, le=86_400)
    final_response_event_id: UUID | None = None


class ContextRunClaimRequest(StrictModel):
    lease_owner: str = Field(min_length=1, max_length=128)
    identity_id: UUID | None = None
    run_id: UUID | None = None
    limit: int = Field(default=1, ge=1, le=10)


class ContextRunLeaseRenewRequest(StrictModel):
    run_id: UUID
    lease_owner: str = Field(min_length=1, max_length=128)


class ContextRunSummary(StrictModel):
    id: UUID
    identity_id: UUID
    platform_message_id: str
    inbound_event_id: UUID
    session_id: UUID
    logical_conversation_id: UUID
    state: RunState
    attempt_count: int = Field(ge=0)
    lease_owner: str | None = None
    lease_expires_at: UTCDateTime | None = None
    next_attempt_at: UTCDateTime | None = None
    terminal_deadline_at: UTCDateTime
    provider_category: str | None = None
    error_code: str | None = None
    final_response_event_id: UUID | None = None


class ContextRunStartResponse(StrictModel):
    run: ContextRunSummary
    replayed: bool
    coalesced: bool


class ContextRunClaimResponse(StrictModel):
    runs: list[ContextRunSummary]


class ContextToolInvocationRequest(StrictModel):
    run_id: UUID
    lease_owner: str = Field(min_length=1, max_length=128)
    tool_call_id: str = Field(min_length=1, max_length=255)
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]
    side_effect_class: SideEffectClass
    caller_idempotency_key: str | None = Field(default=None, max_length=255)


class ContextToolInvocationUpdateRequest(StrictModel):
    run_id: UUID
    lease_owner: str = Field(min_length=1, max_length=128)
    tool_call_id: str = Field(min_length=1, max_length=255)
    state: ToolInvocationState
    result_event_id: UUID | None = None


class ContextToolInvocationResponse(StrictModel):
    invocation_id: UUID | None = None
    canonical_tool_call_id: str = Field(min_length=1, max_length=255)
    state: ToolInvocationState
    replay_decision: Literal[
        "execute",
        "repeat_read",
        "restore_result",
        "retry_not_delivered",
        "block_uncertain",
        "block_limit",
    ]
    result_content: PreservedText | None = Field(default=None, max_length=1_000_000)
    invocation_count: int | None = Field(default=None, ge=0, le=100)
    invocation_limit: int | None = Field(default=None, ge=1, le=100)
    limit_reached: bool = False

    @model_validator(mode="after")
    def validate_limit_receipt(self) -> ContextToolInvocationResponse:
        has_count = self.invocation_count is not None
        has_limit = self.invocation_limit is not None
        if has_count != has_limit:
            raise ValueError("context_tool_limit_receipt_incomplete")
        if self.limit_reached and not has_count:
            raise ValueError("context_tool_limit_receipt_missing")
        if self.replay_decision == "block_limit":
            if (
                self.invocation_id is not None
                or not self.limit_reached
                or self.invocation_count is None
                or self.invocation_limit is None
                or self.invocation_count < self.invocation_limit
            ):
                raise ValueError("context_tool_limit_receipt_invalid")
        elif self.invocation_id is None:
            raise ValueError("context_tool_invocation_id_required")
        return self


class ContextHealthResponse(StrictModel):
    status: Literal["disabled", "ready", "degraded"]
    flags: dict[str, bool]
    identity_count: int = Field(ge=0)
    session_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    run_states: dict[str, int]
    checkpoint_lag_events: int = Field(ge=0)
    oldest_eligible_run_age_seconds: float | None = Field(default=None, ge=0)
    reconciled_session_count: int = Field(default=0, ge=0)
    unreconciled_session_count: int = Field(default=0, ge=0)
    last_reconciled_at: UTCDateTime | None = None
    last_reconciled_event_count: int | None = Field(default=None, ge=0)


class ContextProjectionFactOperation(StrictModel):
    operation: Literal["upsert", "supersede"]
    canonical_key: str = Field(min_length=1, max_length=255)
    kind: Literal[
        "identity",
        "preference",
        "person",
        "project",
        "decision",
        "commitment",
        "constraint",
    ]
    value: dict[str, Any]
    confidence: float = Field(ge=0, le=1)
    source_event_ids: list[UUID] = Field(min_length=1, max_length=100)


class SydneyContextProjectionResult(StrictModel):
    schema_version: Literal["sydney-context-v1"]
    rolling_summary: str = Field(max_length=8_000)
    active_tasks: list[str] = Field(default_factory=list, max_length=50)
    commitments: list[str] = Field(default_factory=list, max_length=50)
    decisions: list[str] = Field(default_factory=list, max_length=50)
    constraints: list[str] = Field(default_factory=list, max_length=50)
    people_entities: list[str] = Field(default_factory=list, max_length=100)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=50)
    source_event_ids: list[UUID] = Field(min_length=1, max_length=100)
    fact_operations: list[ContextProjectionFactOperation] = Field(
        default_factory=list,
        max_length=100,
    )


__all__ = [name for name in globals() if name.startswith(("Context", "Sydney"))]
