"""add Sydney durable conversation context

Revision ID: 85e8b7c9d4f1
Revises: 84d7a5f9b2c3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "85e8b7c9d4f1"
down_revision: str | None = "84d7a5f9b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OWNED_TABLES = (
    "agent_conversation_identities",
    "agent_conversation_sessions",
    "agent_conversation_events",
    "agent_conversation_event_segments",
    "agent_context_checkpoints",
    "agent_memory_facts",
    "agent_run_jobs",
    "agent_tool_invocations",
)


def _id() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "agent_conversation_identities",
        _id(),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("external_chat_id", sa.String(255), nullable=False),
        sa.Column("display_label", sa.String(128), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "retention_mode",
            sa.String(32),
            server_default=sa.text("'indefinite'"),
            nullable=False,
        ),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_conversation_identities"),
        sa.UniqueConstraint(
            "platform",
            "external_user_id",
            "external_chat_id",
            name="uq_agent_conversation_identities_external",
        ),
        sa.CheckConstraint(
            "retention_mode = 'indefinite'",
            name="ck_agent_conversation_identities_retention",
        ),
    )
    op.create_index(
        "ix_agent_conversation_identities_enabled",
        "agent_conversation_identities",
        ["enabled", "id"],
    )

    op.create_table(
        "agent_conversation_sessions",
        _id(),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hermes_session_id", sa.String(255), nullable=False),
        sa.Column(
            "logical_conversation_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("parent_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("continuation_reason", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("source_version", sa.String(128), nullable=True),
        sa.Column(
            "source_event_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("reconciliation_hash", sa.String(64), nullable=True),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_conversation_sessions"),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["agent_conversation_identities.id"],
            name="fk_agent_conversation_sessions_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_session_id"],
            ["agent_conversation_sessions.id"],
            name="fk_agent_conversation_sessions_parent",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "hermes_session_id", name="uq_agent_conversation_sessions_hermes"
        ),
        sa.CheckConstraint(
            "source_event_count >= 0",
            name="ck_agent_conversation_sessions_event_count",
        ),
        sa.CheckConstraint(
            "reconciliation_hash IS NULL OR reconciliation_hash ~ '^[0-9a-f]{64}$'",
            name="ck_agent_conversation_sessions_reconciliation_hash",
        ),
    )
    op.create_index(
        "ix_agent_conversation_sessions_lineage",
        "agent_conversation_sessions",
        ["identity_id", "logical_conversation_id", "started_at", "id"],
    )

    op.create_table(
        "agent_conversation_events",
        _id(),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_key", sa.String(512), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("role", sa.String(32), nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=True),
        sa.Column("tool_call_id", sa.String(255), nullable=True),
        sa.Column("provider_model", sa.String(128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "token_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("redaction_status", sa.String(16), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(search_text, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_agent_conversation_events"),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["agent_conversation_identities.id"],
            name="fk_agent_conversation_events_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_conversation_sessions.id"],
            name="fk_agent_conversation_events_session",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "identity_id",
            "source_event_key",
            name="uq_agent_conversation_events_source",
        ),
        sa.CheckConstraint(
            "event_type IN ('user', 'assistant', 'tool_call', 'tool_result', "
            "'approval', 'error', 'continuation', 'attachment_reference')",
            name="ck_agent_conversation_events_type",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_agent_conversation_events_content_hash",
        ),
        sa.CheckConstraint(
            "redaction_status IN ('unchanged', 'redacted')",
            name="ck_agent_conversation_events_redaction",
        ),
    )
    op.create_index(
        "ix_agent_conversation_events_recent",
        "agent_conversation_events",
        ["identity_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_agent_conversation_events_session_order",
        "agent_conversation_events",
        ["session_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_agent_conversation_events_search",
        "agent_conversation_events",
        ["search_vector"],
        postgresql_using="gin",
    )

    op.create_table(
        "agent_conversation_event_segments",
        _id(),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_agent_conversation_event_segments"),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["agent_conversation_events.id"],
            name="fk_agent_conversation_event_segments_event",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "event_id", "ordinal", name="uq_agent_conversation_event_segments_order"
        ),
        sa.CheckConstraint(
            "ordinal >= 0", name="ck_agent_conversation_event_segments_ordinal"
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_agent_conversation_event_segments_hash",
        ),
    )
    op.create_index(
        "ix_agent_conversation_event_segments_event",
        "agent_conversation_event_segments",
        ["event_id", "ordinal"],
    )

    op.create_table(
        "agent_context_checkpoints",
        _id(),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "logical_conversation_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "source_boundary_event_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("rolling_summary", sa.Text(), nullable=False),
        sa.Column("active_state_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "source_event_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("covered_range_hash", sa.String(64), nullable=False),
        sa.Column(
            "produced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_context_checkpoints"),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["agent_conversation_identities.id"],
            name="fk_agent_context_checkpoints_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_boundary_event_id"],
            ["agent_conversation_events.id"],
            name="fk_agent_context_checkpoints_boundary",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "identity_id",
            "logical_conversation_id",
            "source_boundary_event_id",
            "schema_version",
            name="uq_agent_context_checkpoints_boundary",
        ),
        sa.CheckConstraint(
            "cardinality(source_event_ids) > 0",
            name="ck_agent_context_checkpoints_sources",
        ),
        sa.CheckConstraint(
            "covered_range_hash ~ '^[0-9a-f]{64}$'",
            name="ck_agent_context_checkpoints_hash",
        ),
    )
    op.create_index(
        "ix_agent_context_checkpoints_latest",
        "agent_context_checkpoints",
        ["identity_id", "logical_conversation_id", "produced_at", "id"],
    )

    op.create_table(
        "agent_memory_facts",
        _id(),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "logical_conversation_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("canonical_key", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("value_json", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("projection_version", sa.String(64), nullable=False),
        sa.Column(
            "source_event_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_agent_memory_facts"),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["agent_conversation_identities.id"],
            name="fk_agent_memory_facts_identity",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "identity_id",
            "canonical_key",
            "projection_version",
            name="uq_agent_memory_facts_projection_key",
        ),
        sa.CheckConstraint(
            "kind IN ('identity', 'preference', 'person', 'project', 'decision', "
            "'commitment', 'constraint')",
            name="ck_agent_memory_facts_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'rejected')",
            name="ck_agent_memory_facts_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_agent_memory_facts_confidence",
        ),
        sa.CheckConstraint(
            "cardinality(source_event_ids) > 0",
            name="ck_agent_memory_facts_sources",
        ),
    )
    op.create_index(
        "ix_agent_memory_facts_active",
        "agent_memory_facts",
        ["identity_id", "kind", "canonical_key"],
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "agent_run_jobs",
        _id(),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform_message_id", sa.String(255), nullable=False),
        sa.Column("inbound_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "logical_conversation_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "state", sa.String(32), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_category", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("parsed_retry_delay_seconds", sa.Numeric(12, 3), nullable=True),
        sa.Column("terminal_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "final_response_event_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_run_jobs"),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["agent_conversation_identities.id"],
            name="fk_agent_run_jobs_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inbound_event_id"],
            ["agent_conversation_events.id"],
            name="fk_agent_run_jobs_inbound_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_conversation_sessions.id"],
            name="fk_agent_run_jobs_session",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["final_response_event_id"],
            ["agent_conversation_events.id"],
            name="fk_agent_run_jobs_final_event",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "identity_id",
            "platform_message_id",
            name="uq_agent_run_jobs_platform_message",
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'waiting_retry', 'succeeded', "
            "'blocked_side_effect', 'terminal_failure')",
            name="ck_agent_run_jobs_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_agent_run_jobs_attempts"),
        sa.CheckConstraint(
            "parsed_retry_delay_seconds IS NULL OR parsed_retry_delay_seconds >= 0",
            name="ck_agent_run_jobs_retry_delay",
        ),
    )
    op.create_index(
        "ix_agent_run_jobs_fifo_claim",
        "agent_run_jobs",
        ["identity_id", "state", "next_attempt_at", "created_at", "id"],
    )
    op.create_index(
        "ix_agent_run_jobs_lease",
        "agent_run_jobs",
        ["state", "lease_expires_at", "id"],
    )

    op.create_table(
        "agent_tool_invocations",
        _id(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", sa.String(255), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("arguments_sha256", sa.String(64), nullable=False),
        sa.Column("side_effect_class", sa.String(32), nullable=False),
        sa.Column("caller_idempotency_key", sa.String(255), nullable=True),
        sa.Column(
            "state",
            sa.String(32),
            server_default=sa.text("'started'"),
            nullable=False,
        ),
        sa.Column("result_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_tool_invocations"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_run_jobs.id"],
            name="fk_agent_tool_invocations_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_event_id"],
            ["agent_conversation_events.id"],
            name="fk_agent_tool_invocations_result_event",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "run_id", "tool_call_id", name="uq_agent_tool_invocations_call"
        ),
        sa.CheckConstraint(
            "side_effect_class IN ('read_only', 'idempotent_write', "
            "'non_idempotent_write')",
            name="ck_agent_tool_invocations_side_effect",
        ),
        sa.CheckConstraint(
            "state IN ('started', 'succeeded', 'not_delivered', "
            "'delivery_uncertain', 'failed')",
            name="ck_agent_tool_invocations_state",
        ),
        sa.CheckConstraint(
            "arguments_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_agent_tool_invocations_arguments_hash",
        ),
    )
    op.create_index(
        "ix_agent_tool_invocations_run",
        "agent_tool_invocations",
        ["run_id", "started_at", "id"],
    )

    op.execute(
        sa.text(
            "CREATE FUNCTION sydney_context_reject_append_only_mutation() "
            "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'sydney_context_append_only' USING ERRCODE = '23514'; "
            "END; $$"
        )
    )
    for table in (
        "agent_conversation_events",
        "agent_conversation_event_segments",
        "agent_context_checkpoints",
    ):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE "
                f"ON {table} FOR EACH ROW EXECUTE FUNCTION "
                "sydney_context_reject_append_only_mutation()"
            )
        )


def downgrade() -> None:
    op.execute(
        sa.text("LOCK TABLE " + ", ".join(_OWNED_TABLES) + " IN ACCESS EXCLUSIVE MODE")
    )
    predicates = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} LIMIT 1)" for table in _OWNED_TABLES
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN IF "
            + predicates
            + " THEN RAISE EXCEPTION 'revision 85 downgrade refused: Sydney "
            "durable context evidence exists'; END IF; END $$;"
        )
    )
    for table in (
        "agent_context_checkpoints",
        "agent_conversation_event_segments",
        "agent_conversation_events",
    ):
        op.execute(sa.text(f"DROP TRIGGER trg_{table}_append_only ON {table}"))
    op.execute(sa.text("DROP FUNCTION sydney_context_reject_append_only_mutation()"))

    op.drop_index("ix_agent_tool_invocations_run", table_name="agent_tool_invocations")
    op.drop_table("agent_tool_invocations")
    op.drop_index("ix_agent_run_jobs_lease", table_name="agent_run_jobs")
    op.drop_index("ix_agent_run_jobs_fifo_claim", table_name="agent_run_jobs")
    op.drop_table("agent_run_jobs")
    op.drop_index("ix_agent_memory_facts_active", table_name="agent_memory_facts")
    op.drop_table("agent_memory_facts")
    op.drop_index(
        "ix_agent_context_checkpoints_latest", table_name="agent_context_checkpoints"
    )
    op.drop_table("agent_context_checkpoints")
    op.drop_index(
        "ix_agent_conversation_event_segments_event",
        table_name="agent_conversation_event_segments",
    )
    op.drop_table("agent_conversation_event_segments")
    op.drop_index(
        "ix_agent_conversation_events_search", table_name="agent_conversation_events"
    )
    op.drop_index(
        "ix_agent_conversation_events_session_order",
        table_name="agent_conversation_events",
    )
    op.drop_index(
        "ix_agent_conversation_events_recent", table_name="agent_conversation_events"
    )
    op.drop_table("agent_conversation_events")
    op.drop_index(
        "ix_agent_conversation_sessions_lineage",
        table_name="agent_conversation_sessions",
    )
    op.drop_table("agent_conversation_sessions")
    op.drop_index(
        "ix_agent_conversation_identities_enabled",
        table_name="agent_conversation_identities",
    )
    op.drop_table("agent_conversation_identities")
