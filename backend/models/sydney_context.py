"""Canonical durable conversation, context, run, and tool evidence for Sydney."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.gmail_task_intake import _uuid_primary_key

_JSONB = JSONB().with_variant(JSON(), "sqlite")
_UUID_ARRAY = ARRAY(PostgreSQLUUID(as_uuid=True)).with_variant(JSON(), "sqlite")
_TSVECTOR = TSVECTOR().with_variant(Text(), "sqlite")


class AgentConversationIdentity(Base):
    __tablename__ = "agent_conversation_identities"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "external_user_id",
            "external_chat_id",
            name="uq_agent_conversation_identities_external",
        ),
        CheckConstraint(
            "retention_mode = 'indefinite'",
            name="ck_agent_conversation_identities_retention",
        ),
        Index("ix_agent_conversation_identities_enabled", "enabled", "id"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_chat_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_label: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    retention_mode: Mapped[str] = mapped_column(
        String(32), default="indefinite", server_default="indefinite", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentConversationSession(Base):
    __tablename__ = "agent_conversation_sessions"
    __table_args__ = (
        CheckConstraint(
            "source_event_count >= 0",
            name="ck_agent_conversation_sessions_event_count",
        ),
        CheckConstraint(
            "reconciliation_hash IS NULL OR reconciliation_hash ~ '^[0-9a-f]{64}$'",
            name="ck_agent_conversation_sessions_reconciliation_hash",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_agent_conversation_sessions_lineage",
            "identity_id",
            "logical_conversation_id",
            "started_at",
            "id",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    identity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "agent_conversation_identities.id",
            name="fk_agent_conversation_sessions_identity",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    hermes_session_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    logical_conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    parent_session_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "agent_conversation_sessions.id",
            name="fk_agent_conversation_sessions_parent",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    continuation_reason: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    source_version: Mapped[str | None] = mapped_column(String(128))
    source_event_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    reconciliation_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentConversationEvent(Base):
    __tablename__ = "agent_conversation_events"
    __table_args__ = (
        UniqueConstraint(
            "identity_id",
            "source_event_key",
            name="uq_agent_conversation_events_source",
        ),
        UniqueConstraint(
            "ingestion_sequence",
            name="uq_agent_conversation_events_ingestion_sequence",
        ),
        CheckConstraint(
            "event_type IN ('user', 'assistant', 'tool_call', 'tool_result', "
            "'approval', 'error', 'continuation', 'attachment_reference')",
            name="ck_agent_conversation_events_type",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_agent_conversation_events_content_hash",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "redaction_status IN ('unchanged', 'redacted')",
            name="ck_agent_conversation_events_redaction",
        ),
        Index(
            "ix_agent_conversation_events_recent",
            "identity_id",
            "occurred_at",
            "id",
        ),
        Index(
            "ix_agent_conversation_events_session_order",
            "session_id",
            "occurred_at",
            "id",
        ),
        Index(
            "ix_agent_conversation_events_projection",
            "identity_id",
            "ingestion_sequence",
        ),
        Index(
            "ix_agent_conversation_events_search",
            "search_vector",
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    ingestion_sequence: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        nullable=False,
    )
    identity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "agent_conversation_identities.id",
            name="fk_agent_conversation_events_identity",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "agent_conversation_sessions.id",
            name="fk_agent_conversation_events_session",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str | None] = mapped_column(String(32))
    tool_name: Mapped[str | None] = mapped_column(String(128))
    tool_call_id: Mapped[str | None] = mapped_column(String(255))
    provider_model: Mapped[str | None] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    token_metadata_json: Mapped[dict[str, int]] = mapped_column(
        _JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        _JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    redaction_status: Mapped[str] = mapped_column(String(16), nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[object] = mapped_column(
        _TSVECTOR,
        server_default=FetchedValue(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentConversationEventSegment(Base):
    __tablename__ = "agent_conversation_event_segments"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "ordinal", name="uq_agent_conversation_event_segments_order"
        ),
        CheckConstraint(
            "ordinal >= 0", name="ck_agent_conversation_event_segments_ordinal"
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_agent_conversation_event_segments_hash",
        ).ddl_if(dialect="postgresql"),
        Index("ix_agent_conversation_event_segments_event", "event_id", "ordinal"),
        Index(
            "ix_agent_conversation_event_segments_search",
            "search_vector",
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "agent_conversation_events.id",
            name="fk_agent_conversation_event_segments_event",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    search_vector: Mapped[object] = mapped_column(
        _TSVECTOR,
        server_default=FetchedValue(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentContextCheckpoint(Base):
    __tablename__ = "agent_context_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "identity_id",
            "logical_conversation_id",
            "source_boundary_event_id",
            "source_boundary_char_offset",
            "schema_version",
            name="uq_agent_context_checkpoints_boundary",
        ),
        CheckConstraint(
            "source_boundary_char_offset >= 0",
            name="ck_agent_context_checkpoints_boundary_offset",
        ),
        CheckConstraint(
            "cardinality(source_event_ids) > 0",
            name="ck_agent_context_checkpoints_sources",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "covered_range_hash ~ '^[0-9a-f]{64}$'",
            name="ck_agent_context_checkpoints_hash",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_agent_context_checkpoints_latest",
            "identity_id",
            "logical_conversation_id",
            "produced_at",
            "id",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    identity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_conversation_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    logical_conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    parent_checkpoint_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "agent_context_checkpoints.id",
            name="fk_agent_context_checkpoints_parent",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    source_boundary_event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_conversation_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_boundary_char_offset: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rolling_summary: Mapped[str] = mapped_column(Text, nullable=False)
    active_state_json: Mapped[dict[str, object]] = mapped_column(_JSONB, nullable=False)
    source_event_ids: Mapped[list[UUID]] = mapped_column(_UUID_ARRAY, nullable=False)
    covered_range_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentContextProjectionClaim(Base):
    __tablename__ = "agent_context_projection_claims"
    __table_args__ = (
        UniqueConstraint(
            "identity_id",
            "logical_conversation_id",
            name="uq_agent_context_projection_claims_conversation",
        ),
        CheckConstraint(
            "source_boundary_char_offset >= 0",
            name="ck_agent_context_projection_claims_boundary_offset",
        ),
        CheckConstraint(
            "range_hash ~ '^[0-9a-f]{64}$'",
            name="ck_agent_context_projection_claims_range_hash",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_agent_context_projection_claims_expiry",
            "lease_expires_at",
            "id",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    identity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "agent_conversation_identities.id",
            name="fk_agent_context_projection_claims_identity",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    logical_conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    source_boundary_event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "agent_conversation_events.id",
            name="fk_agent_context_projection_claims_boundary",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_boundary_char_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    range_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    lease_token: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, unique=True
    )
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentMemoryFact(Base):
    __tablename__ = "agent_memory_facts"
    __table_args__ = (
        UniqueConstraint(
            "identity_id",
            "canonical_key",
            "projection_version",
            name="uq_agent_memory_facts_projection_key",
        ),
        CheckConstraint(
            "kind IN ('identity', 'preference', 'person', 'project', 'decision', "
            "'commitment', 'constraint')",
            name="ck_agent_memory_facts_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded', 'rejected')",
            name="ck_agent_memory_facts_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_agent_memory_facts_confidence",
        ),
        CheckConstraint(
            "cardinality(source_event_ids) > 0",
            name="ck_agent_memory_facts_sources",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_agent_memory_facts_active",
            "identity_id",
            "kind",
            "canonical_key",
            postgresql_where=text("status = 'active'"),
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    identity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_conversation_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    logical_conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    canonical_key: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value_json: Mapped[dict[str, object]] = mapped_column(_JSONB, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_ids: Mapped[list[UUID]] = mapped_column(_UUID_ARRAY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentRunJob(Base):
    __tablename__ = "agent_run_jobs"
    __table_args__ = (
        UniqueConstraint(
            "identity_id",
            "platform_message_id",
            name="uq_agent_run_jobs_platform_message",
        ),
        CheckConstraint(
            "state IN ('queued', 'running', 'waiting_retry', 'succeeded', "
            "'blocked_side_effect', 'terminal_failure')",
            name="ck_agent_run_jobs_state",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_agent_run_jobs_attempts"),
        CheckConstraint(
            "parsed_retry_delay_seconds IS NULL OR parsed_retry_delay_seconds >= 0",
            name="ck_agent_run_jobs_retry_delay",
        ),
        Index(
            "ix_agent_run_jobs_fifo_claim",
            "identity_id",
            "state",
            "next_attempt_at",
            "created_at",
            "id",
        ),
        Index("ix_agent_run_jobs_lease", "state", "lease_expires_at", "id"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    identity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_conversation_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    inbound_event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_conversation_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_conversation_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    logical_conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(32), default="queued", server_default="queued", nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_category: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    parsed_retry_delay_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    terminal_deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    final_response_event_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_conversation_events.id", ondelete="RESTRICT"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentToolInvocation(Base):
    __tablename__ = "agent_tool_invocations"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "tool_call_id", name="uq_agent_tool_invocations_call"
        ),
        CheckConstraint(
            "side_effect_class IN ('read_only', 'idempotent_write', "
            "'non_idempotent_write')",
            name="ck_agent_tool_invocations_side_effect",
        ),
        CheckConstraint(
            "state IN ('started', 'succeeded', 'not_delivered', "
            "'delivery_uncertain', 'failed')",
            name="ck_agent_tool_invocations_state",
        ),
        CheckConstraint(
            "arguments_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_agent_tool_invocations_arguments_hash",
        ).ddl_if(dialect="postgresql"),
        Index("ix_agent_tool_invocations_run", "run_id", "started_at", "id"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_run_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    side_effect_class: Mapped[str] = mapped_column(String(32), nullable=False)
    caller_idempotency_key: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(
        String(32), default="started", server_default="started", nullable=False
    )
    result_event_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_conversation_events.id", ondelete="RESTRICT"),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "AgentContextCheckpoint",
    "AgentConversationEvent",
    "AgentConversationEventSegment",
    "AgentConversationIdentity",
    "AgentConversationSession",
    "AgentMemoryFact",
    "AgentRunJob",
    "AgentToolInvocation",
]
