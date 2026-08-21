"""Durable, sanitized persistence for Gmail-originated CRM task review."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.functions import FunctionElement

from database import Base


class _UUIDServerDefault(FunctionElement[UUID]):
    """Compile a database UUID default without breaking SQLite fixtures."""

    inherit_cache = True
    type = PostgreSQLUUID(as_uuid=True)


@compiles(_UUIDServerDefault)
@compiles(_UUIDServerDefault, "postgresql")
def _compile_postgresql_uuid_default(
    _element: _UUIDServerDefault,
    _compiler: object,
    **_kwargs: object,
) -> str:
    return "gen_random_uuid()"


@compiles(_UUIDServerDefault, "sqlite")
def _compile_sqlite_uuid_default(
    _element: _UUIDServerDefault,
    _compiler: object,
    **_kwargs: object,
) -> str:
    return (
        "(lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || "
        "'-4' || substr(lower(hex(randomblob(2))), 2) || '-' || "
        "substr('89ab', abs(random()) % 4 + 1, 1) || "
        "substr(lower(hex(randomblob(2))), 2) || '-' || "
        "lower(hex(randomblob(6))))"
    )


def _uuid_primary_key() -> Mapped[UUID]:
    return mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=_UUIDServerDefault(),
    )


class GmailSyncAccount(Base):
    __tablename__ = "gmail_sync_accounts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_email",
            name="uq_gmail_sync_accounts_workspace_email",
        ),
        CheckConstraint(
            "mode IN ('shadow', 'live')",
            name="ck_gmail_sync_accounts_mode",
        ),
        CheckConstraint(
            "workspace_email = lower(trim(workspace_email)) AND "
            "workspace_email <> ''",
            name="ck_gmail_sync_accounts_workspace_email_canonical",
        ),
        Index(
            "ix_gmail_sync_accounts_blocked",
            "blocked_reason",
            "id",
            postgresql_where=text("blocked_reason IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    workspace_email: Mapped[str] = mapped_column(String(320), nullable=False)
    committed_history_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    reseed_history_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    mode: Mapped[str] = mapped_column(
        String(32), default="shadow", server_default="shadow", nullable=False
    )
    blocked_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    last_succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    last_error_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class GmailSyncRun(Base):
    __tablename__ = "gmail_sync_runs"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "account_id",
            name="uq_gmail_sync_runs_id_account",
        ),
        CheckConstraint(
            "run_kind IN ('poll', 'backfill')",
            name="ck_gmail_sync_runs_kind",
        ),
        CheckConstraint(
            "state IN ('running', 'discovered', 'completed', 'failed', "
            "'blocked_expired_cursor')",
            name="ck_gmail_sync_runs_state",
        ),
        Index(
            "uq_gmail_sync_runs_active_account",
            "account_id",
            unique=True,
            postgresql_where=text("state IN ('running', 'discovered')"),
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "gmail_sync_accounts.id",
            name="fk_gmail_sync_runs_account_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    start_history_id: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal_history_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    next_page_token: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    run_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), default="running", server_default="running", nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    failure_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    discovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GmailSyncPageCheckpoint(Base):
    __tablename__ = "gmail_sync_page_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "page_number",
            name="uq_gmail_sync_page_checkpoints_run_page",
        ),
        CheckConstraint(
            "page_number > 0",
            name="ck_gmail_sync_page_checkpoints_page_positive",
        ),
        CheckConstraint(
            "receipt_count >= 0",
            name="ck_gmail_sync_page_checkpoints_receipts_nonnegative",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "gmail_sync_runs.id",
            name="fk_gmail_sync_page_checkpoints_run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    request_page_token: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    next_page_token: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    discovered_history_id_min: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    discovered_history_id_max: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    receipt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GmailMissingMessageIncident(Base):
    __tablename__ = "gmail_missing_message_incidents"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "run_id",
            "gmail_message_id",
            "gmail_thread_id",
            "page_number",
            name="uq_gmail_missing_message_incidents_run_message_thread_page",
        ),
        CheckConstraint(
            "state IN ('pending', 'acknowledged')",
            name="ck_gmail_missing_message_incidents_state",
        ),
        CheckConstraint(
            "page_number > 0",
            name="ck_gmail_missing_message_incidents_page_positive",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_gmail_missing_message_incidents_version_positive",
        ),
        CheckConstraint(
            "alert_state IN ('pending', 'sent') AND ((alert_state = 'pending' "
            "AND alerted_at IS NULL) OR (alert_state = 'sent' AND alerted_at "
            "IS NOT NULL))",
            name="ck_gmail_missing_message_incidents_alert_shape",
        ),
        CheckConstraint(
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
        ForeignKeyConstraint(
            ("run_id", "account_id"),
            ("gmail_sync_runs.id", "gmail_sync_runs.account_id"),
            name="fk_gmail_missing_message_incidents_run_account",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_gmail_missing_message_incidents_pending",
            "account_id",
            "created_at",
            "id",
            postgresql_where=text("state = 'pending'"),
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "gmail_sync_accounts.id",
            name="fk_gmail_missing_message_incidents_account_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    start_history_id: Mapped[str] = mapped_column(String(64), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    request_page_token: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    state: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    alert_state: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by_admin_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "admin_users.id",
            name="fk_gmail_missing_message_incidents_admin_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    acknowledgement_reason: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    action_audit_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "agent_action_audits.id",
            name="fk_gmail_missing_message_incidents_audit_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GmailMessageReceipt(Base):
    __tablename__ = "gmail_message_receipts"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "gmail_message_id",
            name="uq_gmail_message_receipts_account_message",
        ),
        UniqueConstraint(
            "id",
            "account_id",
            "gmail_thread_id",
            "direction",
            name="uq_gmail_message_receipts_source_identity",
        ),
        CheckConstraint(
            "direction IN ('received', 'sent', 'self_copy')",
            name="ck_gmail_message_receipts_direction",
        ),
        CheckConstraint(
            "processing_state IN ('pending', 'processing', 'processed', "
            "'ignored', 'failed')",
            name="ck_gmail_message_receipts_processing_state",
        ),
        Index(
            "ix_gmail_message_receipts_account_thread",
            "account_id",
            "gmail_thread_id",
        ),
        Index(
            "ix_gmail_message_receipts_pending",
            "processing_state",
            "created_at",
            "id",
            postgresql_where=text(
                "processing_state IN ('pending', 'failed')"
            ),
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "gmail_sync_accounts.id",
            name="fk_gmail_message_receipts_account_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sender_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_hmacs_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]", nullable=False
    )
    subject_preview: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    body_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    labels_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]", nullable=False
    )
    processing_state: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    classification: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    failure_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    failure_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class GmailMessageOrigin(Base):
    __tablename__ = "gmail_message_origins"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "request_id",
            name="uq_gmail_message_origins_account_request",
        ),
        UniqueConstraint(
            "retry_of_origin_id",
            name="uq_gmail_message_origins_retry_parent",
        ),
        CheckConstraint(
            "origin_kind IN ('sydney_client_send', 'human_send', "
            "'system_automation')",
            name="ck_gmail_message_origins_kind",
        ),
        CheckConstraint(
            "delivery_state IN ('sending', 'succeeded', "
            "'delivery_uncertain')",
            name="ck_gmail_message_origins_delivery_state",
        ),
        CheckConstraint(
            "reconciled_outcome IS NULL OR reconciled_outcome IN "
            "('delivered', 'not_delivered')",
            name="ck_gmail_message_origins_reconciled_outcome",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_gmail_message_origins_version_positive",
        ),
        CheckConstraint(
            "(delivery_state = 'succeeded' AND gmail_message_id IS NOT NULL "
            "AND gmail_thread_id IS NOT NULL) OR (delivery_state IN "
            "('sending', 'delivery_uncertain') AND gmail_message_id IS NULL "
            "AND gmail_thread_id IS NULL)",
            name="ck_gmail_message_origins_provider_ids",
        ),
        CheckConstraint(
            "(origin_kind = 'human_send' AND request_id IS NULL AND "
            "canonical_send_hash IS NULL AND canonical_envelope_hash IS NULL "
            "AND canonical_body_hash IS NULL AND action_audit_id IS NULL) OR "
            "(origin_kind IN ('sydney_client_send', 'system_automation') AND "
            "request_id IS NOT NULL AND canonical_send_hash IS NOT NULL AND "
            "canonical_envelope_hash IS NOT NULL AND canonical_body_hash IS "
            "NOT NULL AND action_audit_id IS NOT NULL)",
            name="ck_gmail_message_origins_intent_shape",
        ),
        CheckConstraint(
            "origin_kind <> 'human_send' OR delivery_state = 'succeeded'",
            name="ck_gmail_message_origins_human_succeeded",
        ),
        CheckConstraint(
            "reconciled_outcome IS NULL OR (reconciled_outcome = 'delivered' "
            "AND delivery_state = 'succeeded') OR (reconciled_outcome = "
            "'not_delivered' AND delivery_state IN ('sending', "
            "'delivery_uncertain'))",
            name="ck_gmail_message_origins_reconciliation_state",
        ),
        Index(
            "ix_gmail_message_origins_account_thread",
            "account_id",
            "gmail_thread_id",
        ),
        Index(
            "uq_gmail_message_origins_account_message",
            "account_id",
            "gmail_message_id",
            unique=True,
            postgresql_where=text("gmail_message_id IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_gmail_message_origins_unresolved_send",
            "account_id",
            "canonical_send_hash",
            unique=True,
            postgresql_where=text(
                "delivery_state IN ('sending', 'delivery_uncertain') AND "
                "reconciled_outcome IS DISTINCT FROM 'not_delivered'"
            ),
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "gmail_sync_accounts.id",
            name="fk_gmail_message_origins_account_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    request_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    retry_of_origin_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "gmail_message_origins.id",
            name="fk_gmail_message_origins_retry_of_origin_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    canonical_send_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    canonical_envelope_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    canonical_body_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    intended_thread_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    gmail_message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    gmail_thread_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    origin_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reconciled_outcome: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    action_audit_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "agent_action_audits.id",
            name="fk_gmail_message_origins_action_audit_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    failure_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    failure_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    quarantine_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    quarantine_evidence: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class GmailExtractionAttempt(Base):
    __tablename__ = "gmail_extraction_attempts"
    __table_args__ = (
        UniqueConstraint(
            "receipt_id",
            "schema_version",
            "attempt_number",
            name="uq_gmail_extraction_attempts_receipt_schema_attempt",
        ),
        UniqueConstraint(
            "id",
            "receipt_id",
            name="uq_gmail_extraction_attempts_id_receipt",
        ),
        CheckConstraint(
            "attempt_number > 0",
            name="ck_gmail_extraction_attempts_number_positive",
        ),
        CheckConstraint(
            "state IN ('running', 'succeeded', 'failed')",
            name="ck_gmail_extraction_attempts_state",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    receipt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "gmail_message_receipts.id",
            name="fk_gmail_extraction_attempts_receipt_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), default="running", server_default="running", nullable=False
    )
    error_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GmailExtractedObligation(Base):
    __tablename__ = "gmail_extracted_obligations"
    __table_args__ = (
        UniqueConstraint(
            "receipt_id",
            "action_key",
            "schema_version",
            name="uq_gmail_extracted_obligations_source_action",
        ),
        UniqueConstraint(
            "id",
            "receipt_id",
            name="uq_gmail_extracted_obligations_id_receipt",
        ),
        ForeignKeyConstraint(
            ("extraction_attempt_id", "receipt_id"),
            ("gmail_extraction_attempts.id", "gmail_extraction_attempts.receipt_id"),
            name="fk_gmail_extracted_obligations_attempt_receipt",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high')",
            name="ck_gmail_extracted_obligations_priority",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_gmail_extracted_obligations_confidence",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    receipt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "gmail_message_receipts.id",
            name="fk_gmail_extracted_obligations_receipt_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    extraction_attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    action_key: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(
        Text, default="", server_default="", nullable=False
    )
    priority: Mapped[str] = mapped_column(
        String(32), default="normal", server_default="normal", nullable=False
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timezone_basis: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    requested_owner: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    requested_link_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    requested_link_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    contact_hint: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    obligation_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    confidence: Mapped[float] = mapped_column(
        Numeric(5, 4), default=0, server_default="0", nullable=False
    )
    evaluator_result_json: Mapped[str] = mapped_column(
        Text, default="{}", server_default="{}", nullable=False
    )
    evidence_preview: Mapped[str] = mapped_column(
        String(500), default="", server_default="", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CRMTaskSuggestion(Base):
    __tablename__ = "crm_task_suggestions"
    __table_args__ = (
        UniqueConstraint(
            "application_idempotency_key",
            name="uq_crm_task_suggestions_application_key",
        ),
        UniqueConstraint(
            "source_request_id",
            name="uq_crm_task_suggestions_source_request",
        ),
        UniqueConstraint(
            "id",
            "gmail_account_id",
            "gmail_thread_id",
            name="uq_crm_task_suggestions_gmail_identity",
        ),
        CheckConstraint(
            "source_type IN ('gmail_message', 'sydney_chat')",
            name="ck_crm_task_suggestions_source_type",
        ),
        CheckConstraint(
            "(source_type = 'gmail_message' AND gmail_account_id IS NOT NULL "
            "AND gmail_thread_id IS NOT NULL AND source_request_id IS NULL) "
            "OR (source_type = 'sydney_chat' AND gmail_account_id IS NULL AND "
            "gmail_thread_id IS NULL AND source_request_id IS NOT NULL)",
            name="ck_crm_task_suggestions_source_shape",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high')",
            name="ck_crm_task_suggestions_priority",
        ),
        CheckConstraint(
            "task_status = 'open'",
            name="ck_crm_task_suggestions_task_status",
        ),
        CheckConstraint(
            "state IN ('needs_clarification', 'possible_duplicate', "
            "'pending_review', 'approved', 'dismissed', 'applied', 'failed')",
            name="ck_crm_task_suggestions_state",
        ),
        CheckConstraint(
            "clarification_state IN ('not_required', 'pending', 'answered', "
            "'timed_out', 'manual_review_required')",
            name="ck_crm_task_suggestions_clarification_state",
        ),
        CheckConstraint(
            "cardinality(blocker_codes) <= 8 AND blocker_codes <@ "
            "ARRAY['missing_required_field', 'ambiguous_due_at', "
            "'ambiguous_contact', 'multiple_actions', 'unsupported_owner', "
            "'unsupported_link']::varchar[]",
            name="ck_crm_task_suggestions_blocker_codes",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
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
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_crm_task_suggestions_confidence",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_crm_task_suggestions_version_positive",
        ),
        CheckConstraint(
            "(state = 'applied' AND applied_task_id IS NOT NULL AND "
            "application_idempotency_key IS NOT NULL) OR (state <> "
            "'applied' AND applied_task_id IS NULL)",
            name="ck_crm_task_suggestions_applied_result",
        ),
        Index(
            "ix_crm_task_suggestions_review_state",
            "state",
            "updated_at",
            "id",
        ),
        Index(
            "ix_crm_task_suggestions_gmail_reconciliation",
            "gmail_account_id",
            "gmail_thread_id",
            "source_action_key",
            "id",
            postgresql_where=text("source_type = 'gmail_message'"),
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    gmail_account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "gmail_sync_accounts.id",
            name="fk_crm_task_suggestions_gmail_account_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    gmail_thread_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_scope_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_action_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_request_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    duplicate_of_suggestion_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "crm_task_suggestions.id",
            name="fk_crm_task_suggestions_duplicate_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    contact_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "crm_contacts.id",
            name="fk_crm_task_suggestions_contact_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(
        Text, default="", server_default="", nullable=False
    )
    priority: Mapped[str] = mapped_column(
        String(32), default="normal", server_default="normal", nullable=False
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    task_status: Mapped[str] = mapped_column(
        String(32), default="open", server_default="open", nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(32),
        default="pending_review",
        server_default="pending_review",
        nullable=False,
    )
    clarification_state: Mapped[str] = mapped_column(
        String(32),
        default="not_required",
        server_default="not_required",
        nullable=False,
    )
    blocker_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)).with_variant(JSON(), "sqlite"),
        default=list,
        server_default="{}",
        nullable=False,
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    application_idempotency_key: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    applied_task_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "crm_tasks.id",
            name="fk_crm_task_suggestions_applied_task_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    model_schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    obligation_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    confidence: Mapped[float] = mapped_column(
        Numeric(5, 4), default=0, server_default="0", nullable=False
    )
    rationale: Mapped[str] = mapped_column(
        String(500), default="", server_default="", nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CRMTaskSuggestionSource(Base):
    __tablename__ = "crm_task_suggestion_sources"
    __table_args__ = (
        UniqueConstraint(
            "suggestion_id",
            "obligation_id",
            name="uq_crm_task_suggestion_sources_suggestion_obligation",
        ),
        ForeignKeyConstraint(
            ("suggestion_id", "gmail_account_id", "gmail_thread_id"),
            (
                "crm_task_suggestions.id",
                "crm_task_suggestions.gmail_account_id",
                "crm_task_suggestions.gmail_thread_id",
            ),
            name="fk_crm_task_suggestion_sources_suggestion_origin",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("obligation_id", "receipt_id"),
            (
                "gmail_extracted_obligations.id",
                "gmail_extracted_obligations.receipt_id",
            ),
            name="fk_crm_task_suggestion_sources_obligation_receipt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            (
                "receipt_id",
                "gmail_account_id",
                "gmail_thread_id",
                "direction",
            ),
            (
                "gmail_message_receipts.id",
                "gmail_message_receipts.account_id",
                "gmail_message_receipts.gmail_thread_id",
                "gmail_message_receipts.direction",
            ),
            name="fk_crm_task_suggestion_sources_receipt_origin",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "direction IN ('received', 'sent', 'self_copy')",
            name="ck_crm_task_suggestion_sources_direction",
        ),
        Index(
            "ix_crm_task_suggestion_sources_receipt",
            "receipt_id",
            "id",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    suggestion_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    obligation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    receipt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    gmail_account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    source_label: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CRMTaskSuggestionSuppression(Base):
    __tablename__ = "crm_task_suggestion_suppressions"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_scope_key",
            "source_action_key",
            "obligation_fingerprint",
            name="uq_crm_task_suggestion_suppressions_scope",
        ),
        CheckConstraint(
            "source_type IN ('gmail_message', 'sydney_chat')",
            name="ck_crm_task_suggestion_suppressions_source_type",
        ),
        CheckConstraint(
            "(reprocess_override_at IS NULL AND "
            "reprocess_override_by_admin_id IS NULL AND "
            "reprocess_override_audit_id IS NULL) OR "
            "(reprocess_override_at IS NOT NULL AND "
            "reprocess_override_by_admin_id IS NOT NULL AND "
            "reprocess_override_audit_id IS NOT NULL)",
            name="ck_crm_task_suggestion_suppressions_override_shape",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_scope_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_action_key: Mapped[str] = mapped_column(String(128), nullable=False)
    obligation_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    dismissal_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    dismissed_by_admin_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "admin_users.id",
            name="fk_crm_task_suggestion_suppressions_admin_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    dismissal_audit_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "agent_action_audits.id",
            name="fk_crm_task_suggestion_suppressions_audit_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reprocess_override_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reprocess_override_by_admin_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "admin_users.id",
            name="fk_crm_task_suggestion_suppressions_override_admin_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    reprocess_override_audit_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "agent_action_audits.id",
            name="fk_crm_task_suggestion_suppressions_override_audit_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )


class GmailBackfillRequest(Base):
    __tablename__ = "gmail_backfill_requests"
    __table_args__ = (
        CheckConstraint(
            "window_end >= window_start AND window_end <= window_start + "
            "INTERVAL '7 days'",
            name="ck_gmail_backfill_requests_window",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "state IN ('requested', 'running', 'completed', 'failed')",
            name="ck_gmail_backfill_requests_state",
        ),
        ForeignKeyConstraint(
            ("run_id", "account_id"),
            ("gmail_sync_runs.id", "gmail_sync_runs.account_id"),
            name="fk_gmail_backfill_requests_run_account",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "gmail_sync_accounts.id",
            name="fk_gmail_backfill_requests_account_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    administrator_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "admin_users.id",
            name="fk_gmail_backfill_requests_administrator_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expired_history_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reseed_history_id: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "agent_action_audits.id",
            name="fk_gmail_backfill_requests_audit_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    # Task 3 must verify run_kind == "backfill" before promoting a cursor;
    # SQL CHECK constraints cannot inspect the referenced run row.
    run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    state: Mapped[str] = mapped_column(
        String(32),
        default="requested",
        server_default="requested",
        nullable=False,
    )
    result_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    result_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = [
    "CRMTaskSuggestion",
    "CRMTaskSuggestionSource",
    "CRMTaskSuggestionSuppression",
    "GmailBackfillRequest",
    "GmailExtractedObligation",
    "GmailExtractionAttempt",
    "GmailMessageOrigin",
    "GmailMessageReceipt",
    "GmailMissingMessageIncident",
    "GmailSyncAccount",
    "GmailSyncPageCheckpoint",
    "GmailSyncRun",
]
