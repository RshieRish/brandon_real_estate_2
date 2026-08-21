"""add durable Gmail task intake persistence

Revision ID: 83c6f4e8a1b2
Revises: 82b5e3d7f0a1
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "83c6f4e8a1b2"
down_revision: Union[str, None] = "82b5e3d7f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_id() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _now(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "gmail_sync_accounts",
        _uuid_id(),
        sa.Column("workspace_email", sa.String(length=320), nullable=False),
        sa.Column("committed_history_id", sa.String(length=64), nullable=True),
        sa.Column("reseed_history_id", sa.String(length=64), nullable=True),
        sa.Column(
            "mode",
            sa.String(length=32),
            server_default="shadow",
            nullable=False,
        ),
        sa.Column("blocked_reason", sa.String(length=64), nullable=True),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint(
            "mode IN ('shadow', 'live')",
            name="ck_gmail_sync_accounts_mode",
        ),
        sa.CheckConstraint(
            "workspace_email = lower(trim(workspace_email)) AND "
            "workspace_email <> ''",
            name="ck_gmail_sync_accounts_workspace_email_canonical",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_email",
            name="uq_gmail_sync_accounts_workspace_email",
        ),
    )
    op.create_index(
        "ix_gmail_sync_accounts_blocked",
        "gmail_sync_accounts",
        ["blocked_reason", "id"],
        unique=False,
        postgresql_where=sa.text("blocked_reason IS NOT NULL"),
    )

    op.create_table(
        "gmail_sync_runs",
        _uuid_id(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("start_history_id", sa.String(length=64), nullable=False),
        sa.Column("terminal_history_id", sa.String(length=64), nullable=True),
        sa.Column("next_page_token", sa.String(length=1024), nullable=True),
        sa.Column("run_kind", sa.String(length=32), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default="running",
            nullable=False,
        ),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        _now("started_at"),
        _now("updated_at"),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "run_kind IN ('poll', 'backfill')",
            name="ck_gmail_sync_runs_kind",
        ),
        sa.CheckConstraint(
            "state IN ('running', 'discovered', 'completed', 'failed', "
            "'blocked_expired_cursor')",
            name="ck_gmail_sync_runs_state",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["gmail_sync_accounts.id"],
            name="fk_gmail_sync_runs_account_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "account_id",
            name="uq_gmail_sync_runs_id_account",
        ),
    )
    op.create_index(
        "uq_gmail_sync_runs_active_account",
        "gmail_sync_runs",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('running', 'discovered')"),
    )

    op.create_table(
        "gmail_sync_page_checkpoints",
        _uuid_id(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("request_page_token", sa.String(length=1024), nullable=True),
        sa.Column("next_page_token", sa.String(length=1024), nullable=True),
        sa.Column(
            "discovered_history_id_min",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "discovered_history_id_max",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "receipt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        _now("committed_at"),
        sa.CheckConstraint(
            "page_number > 0",
            name="ck_gmail_sync_page_checkpoints_page_positive",
        ),
        sa.CheckConstraint(
            "receipt_count >= 0",
            name="ck_gmail_sync_page_checkpoints_receipts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["gmail_sync_runs.id"],
            name="fk_gmail_sync_page_checkpoints_run_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "page_number",
            name="uq_gmail_sync_page_checkpoints_run_page",
        ),
    )

    op.create_table(
        "gmail_missing_message_incidents",
        _uuid_id(),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=False),
        sa.Column("start_history_id", sa.String(length=64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("request_page_token", sa.String(length=1024), nullable=True),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "alert_state",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("acknowledgement_reason", sa.String(length=500), nullable=True),
        sa.Column("action_audit_id", sa.Integer(), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending', 'acknowledged')",
            name="ck_gmail_missing_message_incidents_state",
        ),
        sa.CheckConstraint(
            "page_number > 0",
            name="ck_gmail_missing_message_incidents_page_positive",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_gmail_missing_message_incidents_version_positive",
        ),
        sa.CheckConstraint(
            "alert_state IN ('pending', 'sent') AND ((alert_state = 'pending' "
            "AND alerted_at IS NULL) OR (alert_state = 'sent' AND alerted_at "
            "IS NOT NULL))",
            name="ck_gmail_missing_message_incidents_alert_shape",
        ),
        sa.CheckConstraint(
            "(state = 'pending' AND acknowledged_by_admin_id IS NULL AND "
            "acknowledgement_reason IS NULL AND action_audit_id IS NULL AND "
            "acknowledged_at IS NULL) OR (state = 'acknowledged' AND "
            "acknowledged_by_admin_id IS NOT NULL AND acknowledgement_reason "
            "IS NOT NULL AND acknowledgement_reason = "
            "trim(acknowledgement_reason) AND acknowledgement_reason <> '' "
            "AND action_audit_id IS NOT NULL AND acknowledged_at IS NOT NULL "
            "AND alert_state = 'sent')",
            name="ck_gmail_missing_message_incidents_ack_shape",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["gmail_sync_accounts.id"],
            name="fk_gmail_missing_message_incidents_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "account_id"],
            ["gmail_sync_runs.id", "gmail_sync_runs.account_id"],
            name="fk_gmail_missing_message_incidents_run_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_admin_id"],
            ["admin_users.id"],
            name="fk_gmail_missing_message_incidents_admin_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["action_audit_id"],
            ["agent_action_audits.id"],
            name="fk_gmail_missing_message_incidents_audit_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "run_id",
            "gmail_message_id",
            "gmail_thread_id",
            "page_number",
            name="uq_gmail_missing_message_incidents_run_message_thread_page",
        ),
    )
    op.create_index(
        "ix_gmail_missing_message_incidents_pending",
        "gmail_missing_message_incidents",
        ["account_id", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("state = 'pending'"),
    )

    op.create_table(
        "gmail_message_receipts",
        _uuid_id(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sender_hmac", sa.String(length=64), nullable=True),
        sa.Column(
            "recipient_hmacs_json",
            sa.Text(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("subject_preview", sa.String(length=255), nullable=True),
        sa.Column("body_hash", sa.String(length=64), nullable=True),
        sa.Column("labels_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column(
            "processing_state",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("classification", sa.String(length=64), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint(
            "direction IN ('received', 'sent', 'self_copy')",
            name="ck_gmail_message_receipts_direction",
        ),
        sa.CheckConstraint(
            "processing_state IN ('pending', 'processing', 'processed', "
            "'ignored', 'failed')",
            name="ck_gmail_message_receipts_processing_state",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["gmail_sync_accounts.id"],
            name="fk_gmail_message_receipts_account_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "gmail_message_id",
            name="uq_gmail_message_receipts_account_message",
        ),
        sa.UniqueConstraint(
            "id",
            "account_id",
            "gmail_thread_id",
            "direction",
            name="uq_gmail_message_receipts_source_identity",
        ),
    )
    op.create_index(
        "ix_gmail_message_receipts_account_thread",
        "gmail_message_receipts",
        ["account_id", "gmail_thread_id"],
        unique=False,
    )
    op.create_index(
        "ix_gmail_message_receipts_pending",
        "gmail_message_receipts",
        ["processing_state", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text(
            "processing_state IN ('pending', 'failed')"
        ),
    )

    op.create_table(
        "gmail_message_origins",
        _uuid_id(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "retry_of_origin_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("canonical_send_hash", sa.String(length=64), nullable=True),
        sa.Column("canonical_envelope_hash", sa.String(length=64), nullable=True),
        sa.Column("canonical_body_hash", sa.String(length=64), nullable=True),
        sa.Column("intended_thread_id", sa.String(length=255), nullable=True),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=True),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=True),
        sa.Column("origin_kind", sa.String(length=32), nullable=False),
        sa.Column("delivery_state", sa.String(length=32), nullable=False),
        sa.Column("reconciled_outcome", sa.String(length=32), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("action_audit_id", sa.Integer(), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column("quarantine_category", sa.String(length=64), nullable=True),
        sa.Column("quarantine_evidence", sa.String(length=500), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint(
            "origin_kind IN ('sydney_client_send', 'human_send', "
            "'system_automation')",
            name="ck_gmail_message_origins_kind",
        ),
        sa.CheckConstraint(
            "delivery_state IN ('sending', 'succeeded', "
            "'delivery_uncertain')",
            name="ck_gmail_message_origins_delivery_state",
        ),
        sa.CheckConstraint(
            "reconciled_outcome IS NULL OR reconciled_outcome IN "
            "('delivered', 'not_delivered')",
            name="ck_gmail_message_origins_reconciled_outcome",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_gmail_message_origins_version_positive",
        ),
        sa.CheckConstraint(
            "(delivery_state = 'succeeded' AND gmail_message_id IS NOT NULL "
            "AND gmail_thread_id IS NOT NULL) OR (delivery_state IN "
            "('sending', 'delivery_uncertain') AND gmail_message_id IS NULL "
            "AND gmail_thread_id IS NULL)",
            name="ck_gmail_message_origins_provider_ids",
        ),
        sa.CheckConstraint(
            "(origin_kind = 'human_send' AND request_id IS NULL AND "
            "canonical_send_hash IS NULL AND canonical_envelope_hash IS NULL "
            "AND canonical_body_hash IS NULL AND action_audit_id IS NULL) OR "
            "(origin_kind IN ('sydney_client_send', 'system_automation') AND "
            "request_id IS NOT NULL AND canonical_send_hash IS NOT NULL AND "
            "canonical_envelope_hash IS NOT NULL AND canonical_body_hash IS "
            "NOT NULL AND action_audit_id IS NOT NULL)",
            name="ck_gmail_message_origins_intent_shape",
        ),
        sa.CheckConstraint(
            "origin_kind <> 'human_send' OR delivery_state = 'succeeded'",
            name="ck_gmail_message_origins_human_succeeded",
        ),
        sa.CheckConstraint(
            "reconciled_outcome IS NULL OR (reconciled_outcome = 'delivered' "
            "AND delivery_state = 'succeeded') OR (reconciled_outcome = "
            "'not_delivered' AND delivery_state IN ('sending', "
            "'delivery_uncertain'))",
            name="ck_gmail_message_origins_reconciliation_state",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["gmail_sync_accounts.id"],
            name="fk_gmail_message_origins_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_origin_id"],
            ["gmail_message_origins.id"],
            name="fk_gmail_message_origins_retry_of_origin_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["action_audit_id"],
            ["agent_action_audits.id"],
            name="fk_gmail_message_origins_action_audit_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "request_id",
            name="uq_gmail_message_origins_account_request",
        ),
        sa.UniqueConstraint(
            "retry_of_origin_id",
            name="uq_gmail_message_origins_retry_parent",
        ),
    )
    op.create_index(
        "ix_gmail_message_origins_account_thread",
        "gmail_message_origins",
        ["account_id", "gmail_thread_id"],
        unique=False,
    )
    op.create_index(
        "uq_gmail_message_origins_account_message",
        "gmail_message_origins",
        ["account_id", "gmail_message_id"],
        unique=True,
        postgresql_where=sa.text("gmail_message_id IS NOT NULL"),
    )
    op.create_index(
        "uq_gmail_message_origins_unresolved_send",
        "gmail_message_origins",
        ["account_id", "canonical_send_hash"],
        unique=True,
        postgresql_where=sa.text(
            "delivery_state IN ('sending', 'delivery_uncertain') AND "
            "reconciled_outcome IS DISTINCT FROM 'not_delivered'"
        ),
    )

    op.create_table(
        "gmail_extraction_attempts",
        _uuid_id(),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default="running",
            nullable=False,
        ),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        _now("started_at"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_gmail_extraction_attempts_number_positive",
        ),
        sa.CheckConstraint(
            "state IN ('running', 'succeeded', 'failed')",
            name="ck_gmail_extraction_attempts_state",
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["gmail_message_receipts.id"],
            name="fk_gmail_extraction_attempts_receipt_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "receipt_id",
            "schema_version",
            "attempt_number",
            name="uq_gmail_extraction_attempts_receipt_schema_attempt",
        ),
        sa.UniqueConstraint(
            "id",
            "receipt_id",
            name="uq_gmail_extraction_attempts_id_receipt",
        ),
    )

    op.create_table(
        "gmail_extracted_obligations",
        _uuid_id(),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "extraction_attempt_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("action_key", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "priority",
            sa.String(length=32),
            server_default="normal",
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone_basis", sa.String(length=64), nullable=True),
        sa.Column("requested_owner", sa.String(length=128), nullable=True),
        sa.Column("requested_link_type", sa.String(length=64), nullable=True),
        sa.Column("requested_link_id", sa.String(length=255), nullable=True),
        sa.Column("contact_hint", sa.String(length=255), nullable=True),
        sa.Column(
            "obligation_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            sa.Numeric(precision=5, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "evaluator_result_json",
            sa.Text(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "evidence_preview",
            sa.String(length=500),
            server_default="",
            nullable=False,
        ),
        _now("created_at"),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high')",
            name="ck_gmail_extracted_obligations_priority",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_gmail_extracted_obligations_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["gmail_message_receipts.id"],
            name="fk_gmail_extracted_obligations_receipt_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_attempt_id", "receipt_id"],
            ["gmail_extraction_attempts.id", "gmail_extraction_attempts.receipt_id"],
            name="fk_gmail_extracted_obligations_attempt_receipt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "receipt_id",
            "action_key",
            "schema_version",
            name="uq_gmail_extracted_obligations_source_action",
        ),
        sa.UniqueConstraint(
            "id",
            "receipt_id",
            name="uq_gmail_extracted_obligations_id_receipt",
        ),
    )

    op.create_table(
        "crm_task_suggestions",
        _uuid_id(),
        sa.Column(
            "gmail_account_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_scope_key", sa.String(length=512), nullable=False),
        sa.Column("source_action_key", sa.String(length=128), nullable=False),
        sa.Column(
            "source_request_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "duplicate_of_suggestion_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "priority",
            sa.String(length=32),
            server_default="normal",
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "task_status",
            sa.String(length=32),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default="pending_review",
            nullable=False,
        ),
        sa.Column(
            "clarification_state",
            sa.String(length=32),
            server_default="not_required",
            nullable=False,
        ),
        sa.Column(
            "blocker_codes",
            postgresql.ARRAY(sa.String(length=64)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "application_idempotency_key",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("applied_task_id", sa.Integer(), nullable=True),
        sa.Column("model_schema_version", sa.String(length=64), nullable=False),
        sa.Column(
            "obligation_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            sa.Numeric(precision=5, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "rationale",
            sa.String(length=500),
            server_default="",
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint(
            "source_type IN ('gmail_message', 'sydney_chat')",
            name="ck_crm_task_suggestions_source_type",
        ),
        sa.CheckConstraint(
            "(source_type = 'gmail_message' AND gmail_account_id IS NOT NULL "
            "AND gmail_thread_id IS NOT NULL AND source_request_id IS NULL) "
            "OR (source_type = 'sydney_chat' AND gmail_account_id IS NULL AND "
            "gmail_thread_id IS NULL AND source_request_id IS NOT NULL)",
            name="ck_crm_task_suggestions_source_shape",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high')",
            name="ck_crm_task_suggestions_priority",
        ),
        sa.CheckConstraint(
            "task_status = 'open'",
            name="ck_crm_task_suggestions_task_status",
        ),
        sa.CheckConstraint(
            "state IN ('needs_clarification', 'possible_duplicate', "
            "'pending_review', 'approved', 'dismissed', 'applied', 'failed')",
            name="ck_crm_task_suggestions_state",
        ),
        sa.CheckConstraint(
            "clarification_state IN ('not_required', 'pending', 'answered', "
            "'timed_out', 'manual_review_required')",
            name="ck_crm_task_suggestions_clarification_state",
        ),
        sa.CheckConstraint(
            "cardinality(blocker_codes) <= 8 AND blocker_codes <@ "
            "ARRAY['missing_required_field', 'ambiguous_due_at', "
            "'ambiguous_contact', 'multiple_actions', 'unsupported_owner', "
            "'unsupported_link']::varchar[]",
            name="ck_crm_task_suggestions_blocker_codes",
        ),
        sa.CheckConstraint(
            "cardinality(array_positions(blocker_codes, "
            "'missing_required_field')) <= 1 AND "
            "cardinality(array_positions(blocker_codes, "
            "'ambiguous_due_at')) <= 1 AND "
            "cardinality(array_positions(blocker_codes, "
            "'ambiguous_contact')) <= 1 AND "
            "cardinality(array_positions(blocker_codes, "
            "'multiple_actions')) <= 1 AND "
            "cardinality(array_positions(blocker_codes, "
            "'unsupported_owner')) <= 1 AND "
            "cardinality(array_positions(blocker_codes, "
            "'unsupported_link')) <= 1",
            name="ck_crm_task_suggestions_blocker_codes_unique",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_crm_task_suggestions_confidence",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_crm_task_suggestions_version_positive",
        ),
        sa.CheckConstraint(
            "(state = 'applied' AND applied_task_id IS NOT NULL AND "
            "application_idempotency_key IS NOT NULL) OR (state <> "
            "'applied' AND applied_task_id IS NULL)",
            name="ck_crm_task_suggestions_applied_result",
        ),
        sa.ForeignKeyConstraint(
            ["gmail_account_id"],
            ["gmail_sync_accounts.id"],
            name="fk_crm_task_suggestions_gmail_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_suggestion_id"],
            ["crm_task_suggestions.id"],
            name="fk_crm_task_suggestions_duplicate_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["crm_contacts.id"],
            name="fk_crm_task_suggestions_contact_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["applied_task_id"],
            ["crm_tasks.id"],
            name="fk_crm_task_suggestions_applied_task_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_idempotency_key",
            name="uq_crm_task_suggestions_application_key",
        ),
        sa.UniqueConstraint(
            "source_request_id",
            name="uq_crm_task_suggestions_source_request",
        ),
        sa.UniqueConstraint(
            "id",
            "gmail_account_id",
            "gmail_thread_id",
            name="uq_crm_task_suggestions_gmail_identity",
        ),
    )
    op.create_index(
        "ix_crm_task_suggestions_gmail_reconciliation",
        "crm_task_suggestions",
        ["gmail_account_id", "gmail_thread_id", "source_action_key", "id"],
        unique=False,
        postgresql_where=sa.text("source_type = 'gmail_message'"),
    )
    op.create_index(
        "ix_crm_task_suggestions_review_state",
        "crm_task_suggestions",
        ["state", "updated_at", "id"],
        unique=False,
    )

    op.create_table(
        "crm_task_suggestion_sources",
        _uuid_id(),
        sa.Column(
            "suggestion_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "obligation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "gmail_account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("source_label", sa.String(length=255), nullable=False),
        _now("created_at"),
        sa.CheckConstraint(
            "direction IN ('received', 'sent', 'self_copy')",
            name="ck_crm_task_suggestion_sources_direction",
        ),
        sa.ForeignKeyConstraint(
            ["suggestion_id", "gmail_account_id", "gmail_thread_id"],
            [
                "crm_task_suggestions.id",
                "crm_task_suggestions.gmail_account_id",
                "crm_task_suggestions.gmail_thread_id",
            ],
            name="fk_crm_task_suggestion_sources_suggestion_origin",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["obligation_id", "receipt_id"],
            [
                "gmail_extracted_obligations.id",
                "gmail_extracted_obligations.receipt_id",
            ],
            name="fk_crm_task_suggestion_sources_obligation_receipt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "receipt_id",
                "gmail_account_id",
                "gmail_thread_id",
                "direction",
            ],
            [
                "gmail_message_receipts.id",
                "gmail_message_receipts.account_id",
                "gmail_message_receipts.gmail_thread_id",
                "gmail_message_receipts.direction",
            ],
            name="fk_crm_task_suggestion_sources_receipt_origin",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "suggestion_id",
            "obligation_id",
            name="uq_crm_task_suggestion_sources_suggestion_obligation",
        ),
    )
    op.create_index(
        "ix_crm_task_suggestion_sources_receipt",
        "crm_task_suggestion_sources",
        ["receipt_id", "id"],
        unique=False,
    )

    op.create_table(
        "crm_task_suggestion_suppressions",
        _uuid_id(),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_scope_key", sa.String(length=512), nullable=False),
        sa.Column("source_action_key", sa.String(length=128), nullable=False),
        sa.Column(
            "obligation_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("dismissal_reason", sa.String(length=500), nullable=False),
        sa.Column("dismissed_by_admin_id", sa.Integer(), nullable=False),
        sa.Column("dismissal_audit_id", sa.Integer(), nullable=False),
        _now("dismissed_at"),
        sa.Column(
            "reprocess_override_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("reprocess_override_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("reprocess_override_audit_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('gmail_message', 'sydney_chat')",
            name="ck_crm_task_suggestion_suppressions_source_type",
        ),
        sa.CheckConstraint(
            "(reprocess_override_at IS NULL AND "
            "reprocess_override_by_admin_id IS NULL AND "
            "reprocess_override_audit_id IS NULL) OR "
            "(reprocess_override_at IS NOT NULL AND "
            "reprocess_override_by_admin_id IS NOT NULL AND "
            "reprocess_override_audit_id IS NOT NULL)",
            name="ck_crm_task_suggestion_suppressions_override_shape",
        ),
        sa.ForeignKeyConstraint(
            ["dismissed_by_admin_id"],
            ["admin_users.id"],
            name="fk_crm_task_suggestion_suppressions_admin_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dismissal_audit_id"],
            ["agent_action_audits.id"],
            name="fk_crm_task_suggestion_suppressions_audit_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reprocess_override_by_admin_id"],
            ["admin_users.id"],
            name="fk_crm_task_suggestion_suppressions_override_admin_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reprocess_override_audit_id"],
            ["agent_action_audits.id"],
            name="fk_crm_task_suggestion_suppressions_override_audit_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type",
            "source_scope_key",
            "source_action_key",
            "obligation_fingerprint",
            name="uq_crm_task_suggestion_suppressions_scope",
        ),
    )

    op.create_table(
        "gmail_backfill_requests",
        _uuid_id(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("administrator_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expired_history_id", sa.String(length=64), nullable=False),
        sa.Column("reseed_history_id", sa.String(length=64), nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default="requested",
            nullable=False,
        ),
        sa.Column("result_category", sa.String(length=64), nullable=True),
        sa.Column("result_message", sa.String(length=500), nullable=True),
        _now("created_at"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "window_end >= window_start AND window_end <= window_start + "
            "INTERVAL '7 days'",
            name="ck_gmail_backfill_requests_window",
        ),
        sa.CheckConstraint(
            "state IN ('requested', 'running', 'completed', 'failed')",
            name="ck_gmail_backfill_requests_state",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["gmail_sync_accounts.id"],
            name="fk_gmail_backfill_requests_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["administrator_id"],
            ["admin_users.id"],
            name="fk_gmail_backfill_requests_administrator_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audit_id"],
            ["agent_action_audits.id"],
            name="fk_gmail_backfill_requests_audit_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "account_id"],
            ["gmail_sync_runs.id", "gmail_sync_runs.account_id"],
            name="fk_gmail_backfill_requests_run_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "LOCK TABLE gmail_sync_accounts, gmail_sync_runs, "
            "gmail_sync_page_checkpoints, gmail_missing_message_incidents, "
            "gmail_message_receipts, "
            "gmail_message_origins, gmail_extraction_attempts, "
            "gmail_extracted_obligations, crm_task_suggestions, "
            "crm_task_suggestion_sources, "
            "crm_task_suggestion_suppressions, gmail_backfill_requests "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM gmail_sync_accounts LIMIT 1)
                    OR EXISTS (SELECT 1 FROM gmail_sync_runs LIMIT 1)
                    OR EXISTS (SELECT 1 FROM gmail_sync_page_checkpoints LIMIT 1)
                    OR EXISTS (SELECT 1 FROM gmail_missing_message_incidents LIMIT 1)
                    OR EXISTS (SELECT 1 FROM gmail_message_receipts LIMIT 1)
                    OR EXISTS (SELECT 1 FROM gmail_message_origins LIMIT 1)
                    OR EXISTS (SELECT 1 FROM gmail_extraction_attempts LIMIT 1)
                    OR EXISTS (SELECT 1 FROM gmail_extracted_obligations LIMIT 1)
                    OR EXISTS (SELECT 1 FROM crm_task_suggestions LIMIT 1)
                    OR EXISTS (SELECT 1 FROM crm_task_suggestion_sources LIMIT 1)
                    OR EXISTS (SELECT 1 FROM crm_task_suggestion_suppressions LIMIT 1)
                    OR EXISTS (SELECT 1 FROM gmail_backfill_requests LIMIT 1)
                THEN
                    RAISE EXCEPTION
                        'revision 83 downgrade refused: Gmail task intake evidence exists';
                END IF;
            END
            $$;
            """
        )
    )

    op.drop_table("gmail_backfill_requests")
    op.drop_table("crm_task_suggestion_suppressions")
    op.drop_index(
        "ix_crm_task_suggestion_sources_receipt",
        table_name="crm_task_suggestion_sources",
    )
    op.drop_table("crm_task_suggestion_sources")
    op.drop_index(
        "ix_crm_task_suggestions_review_state",
        table_name="crm_task_suggestions",
    )
    op.drop_index(
        "ix_crm_task_suggestions_gmail_reconciliation",
        table_name="crm_task_suggestions",
    )
    op.drop_table("crm_task_suggestions")
    op.drop_table("gmail_extracted_obligations")
    op.drop_table("gmail_extraction_attempts")
    op.drop_index(
        "uq_gmail_message_origins_unresolved_send",
        table_name="gmail_message_origins",
    )
    op.drop_index(
        "uq_gmail_message_origins_account_message",
        table_name="gmail_message_origins",
    )
    op.drop_index(
        "ix_gmail_message_origins_account_thread",
        table_name="gmail_message_origins",
    )
    op.drop_table("gmail_message_origins")
    op.drop_index(
        "ix_gmail_message_receipts_pending",
        table_name="gmail_message_receipts",
    )
    op.drop_index(
        "ix_gmail_message_receipts_account_thread",
        table_name="gmail_message_receipts",
    )
    op.drop_table("gmail_message_receipts")
    op.drop_index(
        "ix_gmail_missing_message_incidents_pending",
        table_name="gmail_missing_message_incidents",
    )
    op.drop_table("gmail_missing_message_incidents")
    op.drop_table("gmail_sync_page_checkpoints")
    op.drop_index(
        "uq_gmail_sync_runs_active_account",
        table_name="gmail_sync_runs",
    )
    op.drop_table("gmail_sync_runs")
    op.drop_index(
        "ix_gmail_sync_accounts_blocked",
        table_name="gmail_sync_accounts",
    )
    op.drop_table("gmail_sync_accounts")
