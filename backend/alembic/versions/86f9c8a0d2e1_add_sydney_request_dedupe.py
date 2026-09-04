"""add Sydney active-request dedupe receipts

Revision ID: 86f9c8a0d2e1
Revises: 85e8b7c9d4f1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "86f9c8a0d2e1"
down_revision: str | None = "85e8b7c9d4f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ACTIVE_STATES = "('queued', 'running', 'waiting_retry')"
_MIGRATION_COALESCED_ERROR = "coalesced_by_request_dedupe"


def upgrade() -> None:
    op.add_column(
        "agent_run_jobs",
        sa.Column("request_fingerprint_sha256", sa.String(64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE agent_run_jobs AS run SET request_fingerprint_sha256 = "
            "encode(digest(convert_to('sydney-request-v1', 'UTF8') || "
            "decode('00', 'hex') || convert_to("
            "lower(btrim(regexp_replace(normalize(coalesce(event.search_text, ''), "
            "NFKC), '[[:space:]]+', ' ', 'g'))), 'UTF8'), 'sha256'), 'hex') "
            "FROM agent_conversation_events AS event "
            "WHERE event.id = run.inbound_event_id"
        )
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM agent_run_jobs "
            "WHERE request_fingerprint_sha256 IS NULL) THEN RAISE EXCEPTION "
            "'revision 86 request fingerprint backfill incomplete'; END IF; END $$;"
        )
    )
    op.execute(
        sa.text(
            "WITH ranked AS ("
            "SELECT id, row_number() OVER (PARTITION BY identity_id, "
            "logical_conversation_id, request_fingerprint_sha256 "
            "ORDER BY created_at, id) AS request_rank "
            "FROM agent_run_jobs WHERE state IN "
            + _ACTIVE_STATES
            + ") UPDATE agent_run_jobs AS run SET state = 'terminal_failure', "
            "lease_owner = NULL, lease_expires_at = NULL, next_attempt_at = NULL, "
            "provider_category = 'request_dedupe', error_code = '"
            + _MIGRATION_COALESCED_ERROR
            + "', updated_at = now() FROM ranked "
            "WHERE ranked.id = run.id AND ranked.request_rank > 1"
        )
    )
    op.alter_column(
        "agent_run_jobs",
        "request_fingerprint_sha256",
        existing_type=sa.String(64),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_agent_run_jobs_request_fingerprint",
        "agent_run_jobs",
        "request_fingerprint_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_index(
        "uq_agent_run_jobs_active_request",
        "agent_run_jobs",
        ["identity_id", "logical_conversation_id", "request_fingerprint_sha256"],
        unique=True,
        postgresql_where=sa.text("state IN " + _ACTIVE_STATES),
    )

    op.create_table(
        "agent_run_request_receipts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform_message_id", sa.String(255), nullable=False),
        sa.Column("inbound_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "logical_conversation_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("request_fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("disposition", sa.String(16), nullable=False),
        sa.Column("terminal_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_run_request_receipts"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_run_jobs.id"],
            name="fk_agent_run_request_receipts_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["agent_conversation_identities.id"],
            name="fk_agent_run_request_receipts_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inbound_event_id"],
            ["agent_conversation_events.id"],
            name="fk_agent_run_request_receipts_inbound_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_conversation_sessions.id"],
            name="fk_agent_run_request_receipts_session",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "identity_id",
            "platform_message_id",
            name="uq_agent_run_request_receipts_platform_message",
        ),
        sa.UniqueConstraint(
            "inbound_event_id",
            name="uq_agent_run_request_receipts_inbound_event",
        ),
        sa.CheckConstraint(
            "request_fingerprint_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_agent_run_request_receipts_fingerprint",
        ),
        sa.CheckConstraint(
            "disposition IN ('primary', 'coalesced')",
            name="ck_agent_run_request_receipts_disposition",
        ),
    )
    op.create_index(
        "ix_agent_run_request_receipts_run",
        "agent_run_request_receipts",
        ["run_id", "created_at", "id"],
    )
    op.execute(
        sa.text(
            "WITH resolved AS ("
            "SELECT run.*, CASE WHEN run.error_code = '"
            + _MIGRATION_COALESCED_ERROR
            + "' THEN (SELECT canonical.id FROM agent_run_jobs AS canonical "
            "WHERE canonical.identity_id = run.identity_id AND "
            "canonical.logical_conversation_id = run.logical_conversation_id AND "
            "canonical.request_fingerprint_sha256 = run.request_fingerprint_sha256 "
            "AND canonical.state IN " + _ACTIVE_STATES + " "
            "AND canonical.error_code IS DISTINCT FROM '"
            + _MIGRATION_COALESCED_ERROR
            + "' ORDER BY canonical.created_at, canonical.id LIMIT 1) "
            "ELSE run.id END AS receipt_run_id FROM agent_run_jobs AS run) "
            "INSERT INTO agent_run_request_receipts (run_id, identity_id, "
            "platform_message_id, inbound_event_id, session_id, "
            "logical_conversation_id, request_fingerprint_sha256, disposition, "
            "terminal_deadline_at, created_at) SELECT coalesce(receipt_run_id, id), "
            "identity_id, platform_message_id, inbound_event_id, session_id, "
            "logical_conversation_id, request_fingerprint_sha256, CASE WHEN "
            "receipt_run_id IS DISTINCT FROM id THEN 'coalesced' ELSE 'primary' END, "
            "terminal_deadline_at, created_at FROM resolved"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_agent_run_request_receipts_append_only "
            "BEFORE UPDATE OR DELETE ON agent_run_request_receipts FOR EACH ROW "
            "EXECUTE FUNCTION sydney_context_reject_append_only_mutation()"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "LOCK TABLE agent_run_request_receipts, agent_run_jobs "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM agent_run_request_receipts "
            "WHERE disposition = 'coalesced' LIMIT 1) THEN RAISE EXCEPTION "
            "'revision 86 downgrade refused: coalesced request evidence exists'; "
            "END IF; END $$;"
        )
    )
    op.execute(
        sa.text(
            "DROP TRIGGER trg_agent_run_request_receipts_append_only "
            "ON agent_run_request_receipts"
        )
    )
    op.drop_index(
        "ix_agent_run_request_receipts_run",
        table_name="agent_run_request_receipts",
    )
    op.drop_table("agent_run_request_receipts")
    op.drop_index("uq_agent_run_jobs_active_request", table_name="agent_run_jobs")
    op.drop_constraint(
        "ck_agent_run_jobs_request_fingerprint",
        "agent_run_jobs",
        type_="check",
    )
    op.drop_column("agent_run_jobs", "request_fingerprint_sha256")
