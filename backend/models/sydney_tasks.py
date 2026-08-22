"""Durable Sydney clarification, Telegram outbox, and approval evidence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.gmail_task_intake import _uuid_primary_key


class CRMTaskClarification(Base):
    __tablename__ = "crm_task_clarifications"
    __table_args__ = (
        UniqueConstraint(
            "suggestion_id",
            "suggestion_version",
            "field_name",
            name="uq_crm_task_clarifications_suggestion_version_field",
        ),
        UniqueConstraint(
            "suggestion_id",
            "round_number",
            name="uq_crm_task_clarifications_suggestion_round",
        ),
        UniqueConstraint(
            "code_hash",
            name="uq_crm_task_clarifications_code_hash",
        ),
        CheckConstraint(
            "suggestion_version > 0",
            name="ck_crm_task_clarifications_version_positive",
        ),
        CheckConstraint(
            "round_number BETWEEN 1 AND 5",
            name="ck_crm_task_clarifications_round",
        ),
        CheckConstraint(
            "field_name IN ('action_scope', 'contact', 'due_at', 'owner', "
            "'task_details')",
            name="ck_crm_task_clarifications_field",
        ),
        CheckConstraint(
            "state IN ('pending', 'answered', 'timed_out', 'superseded')",
            name="ck_crm_task_clarifications_state",
        ),
        CheckConstraint(
            "octet_length(code_hash) = 32",
            name="ck_crm_task_clarifications_code_hash_length",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "code_key_version BETWEEN 1 AND 32767",
            name="ck_crm_task_clarifications_key_version",
        ),
        CheckConstraint(
            "CASE WHEN telegram_chat_id ~ '^-?[1-9][0-9]*$' THEN "
            "telegram_chat_id::numeric > -4503599627370496 AND "
            "telegram_chat_id::numeric < 4503599627370496 ELSE false END",
            name="ck_crm_task_clarifications_chat_id",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(state = 'pending' AND resolved_at IS NULL AND answer_json IS NULL) "
            "OR (state = 'answered' AND resolved_at IS NOT NULL AND "
            "answer_json IS NOT NULL) OR (state IN ('timed_out', "
            "'superseded') AND resolved_at IS NOT NULL AND answer_json IS NULL)",
            name="ck_crm_task_clarifications_resolution_shape",
        ),
        CheckConstraint(
            "options_json IS JSON OBJECT WITH UNIQUE KEYS AND "
            "octet_length(options_json) <= 4096",
            name="ck_crm_task_clarifications_options_json",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "answer_json IS NULL OR (answer_json IS JSON OBJECT WITH UNIQUE "
            "KEYS AND octet_length(answer_json) <= 8192)",
            name="ck_crm_task_clarifications_answer_json",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "slot_deadline_at = deadline_anchored_at + interval '48 hours' "
            "AND ((deadline_anchor_kind = 'created' AND first_attempt_at IS "
            "NULL AND deadline_anchored_at = created_at) OR "
            "(deadline_anchor_kind = 'first_attempt' AND first_attempt_at IS "
            "NOT NULL AND deadline_anchored_at = first_attempt_at) OR "
            "(deadline_anchor_kind = 'initial_sent' AND first_attempt_at IS "
            "NOT NULL AND deadline_anchored_at >= first_attempt_at))",
            name="ck_crm_task_clarifications_deadline",
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_crm_task_clarifications_active_chat",
            "telegram_chat_id",
            unique=True,
            postgresql_where=text("state = 'pending'"),
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_crm_task_clarifications_active_suggestion",
            "suggestion_id",
            unique=True,
            postgresql_where=text("state = 'pending'"),
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_crm_task_clarifications_suggestion_field_state",
            "suggestion_id",
            "field_name",
            "state",
            "id",
        ),
        Index(
            "ix_crm_task_clarifications_due",
            "state",
            "slot_deadline_at",
            "id",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    suggestion_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "crm_task_suggestions.id",
            name="fk_crm_task_clarifications_suggestion_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    suggestion_version: Mapped[int] = mapped_column(Integer, nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_chat_id: Mapped[str] = mapped_column(String(32), nullable=False)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    code_key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    options_json: Mapped[str] = mapped_column(
        Text, default="{}", server_default="{}", nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    answer_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline_anchor_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    deadline_anchored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    slot_deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    first_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SydneyQuestionOutbox(Base):
    __tablename__ = "sydney_question_outbox"
    __table_args__ = (
        UniqueConstraint(
            "dedupe_key", name="uq_sydney_question_outbox_dedupe_key"
        ),
        UniqueConstraint(
            "clarification_id",
            "attempt_kind",
            "attempt_number",
            name="uq_sydney_question_outbox_attempt",
        ),
        UniqueConstraint(
            "id",
            "clarification_id",
            name="uq_sydney_question_outbox_id_clarification",
        ),
        ForeignKeyConstraint(
            ("parent_initial_attempt_id", "clarification_id"),
            (
                "sydney_question_outbox.id",
                "sydney_question_outbox.clarification_id",
            ),
            name="fk_sydney_question_outbox_parent_initial",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("reply_to_attempt_id", "clarification_id"),
            (
                "sydney_question_outbox.id",
                "sydney_question_outbox.clarification_id",
            ),
            name="fk_sydney_question_outbox_reply_to",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "attempt_kind IN ('initial', 'initial_retry', 'reminder')",
            name="ck_sydney_question_outbox_attempt_kind",
        ),
        CheckConstraint(
            "attempt_number > 0",
            name="ck_sydney_question_outbox_attempt_number",
        ),
        CheckConstraint(
            "template_id IN ('clarification_initial_v1', "
            "'clarification_reminder_v1')",
            name="ck_sydney_question_outbox_template",
        ),
        CheckConstraint(
            "(attempt_kind = 'reminder' AND template_id = "
            "'clarification_reminder_v1') OR (attempt_kind IN ('initial', "
            "'initial_retry') AND template_id = 'clarification_initial_v1')",
            name="ck_sydney_question_outbox_template_kind",
        ),
        CheckConstraint(
            "question_context_json IS JSON OBJECT WITH UNIQUE KEYS AND "
            "octet_length(question_context_json) <= 4096",
            name="ck_sydney_question_outbox_context",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "state IN ('pending', 'sending', 'sent', 'failed', "
            "'delivery_uncertain')",
            name="ck_sydney_question_outbox_state",
        ),
        CheckConstraint(
            "(attempt_kind = 'initial' AND attempt_number = 1 AND "
            "parent_initial_attempt_id IS NULL AND reply_to_attempt_id IS "
            "NULL) OR (attempt_kind = 'initial_retry' AND attempt_number > 0 "
            "AND parent_initial_attempt_id IS NOT NULL AND "
            "reply_to_attempt_id IS NULL) OR (attempt_kind = 'reminder' AND "
            "attempt_number = 1 AND parent_initial_attempt_id IS NULL AND "
            "reply_to_attempt_id IS NOT NULL)",
            name="ck_sydney_question_outbox_attempt_parent_shape",
        ),
        CheckConstraint(
            "rendered_payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sydney_question_outbox_rendered_hash",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "telegram_chat_id IS NULL OR CASE WHEN telegram_chat_id ~ "
            "'^-?[1-9][0-9]*$' THEN telegram_chat_id::numeric > "
            "-4503599627370496 AND telegram_chat_id::numeric < "
            "4503599627370496 ELSE false END",
            name="ck_sydney_question_outbox_chat_id",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "telegram_message_id IS NULL OR telegram_message_id ~ "
            "'^[1-9][0-9]*$'",
            name="ck_sydney_question_outbox_message_id",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(state = 'pending' AND attempted_at IS NULL AND sent_at IS NULL "
            "AND telegram_chat_id IS NULL AND telegram_message_id IS NULL "
            "AND failure_category IS NULL) OR (state = 'sending' AND "
            "attempted_at IS NOT NULL AND sent_at IS NULL AND "
            "telegram_chat_id IS NOT NULL AND telegram_message_id IS NULL "
            "AND failure_category IS NULL) OR (state = 'sent' AND "
            "attempted_at IS NOT NULL AND sent_at IS NOT NULL AND "
            "telegram_chat_id IS NOT NULL AND telegram_message_id IS NOT NULL "
            "AND failure_category IS NULL) OR (state = 'failed' AND "
            "failure_category IN ('pre_send_resolved', "
            "'pre_send_superseded', 'pre_send_expired') AND attempted_at IS "
            "NULL AND sent_at IS NULL AND telegram_chat_id IS NULL AND "
            "telegram_message_id IS NULL) OR (state IN ('failed', "
            "'delivery_uncertain') AND attempted_at IS NOT NULL AND sent_at IS "
            "NULL AND telegram_chat_id IS NOT NULL AND failure_category IS "
            "NOT NULL AND (telegram_message_id IS NULL OR reconciled_outcome "
            "= 'delivered'))",
            name="ck_sydney_question_outbox_delivery_shape",
        ),
        CheckConstraint(
            "(reconciled_outcome IS NULL AND reconciliation_reason IS NULL "
            "AND reconciliation_audit_id IS NULL AND reconciled_at IS NULL) OR "
            "(reconciliation_reason IS NOT NULL AND reconciliation_audit_id "
            "IS NOT NULL AND reconciled_at IS NOT NULL AND (((state = "
            "'failed' AND reconciled_outcome = 'not_delivered') OR (state = "
            "'delivery_uncertain' AND reconciled_outcome IN ('delivered', "
            "'not_delivered'))) AND ((reconciled_outcome = 'delivered' AND "
            "telegram_chat_id IS NOT NULL AND telegram_message_id IS NOT NULL) "
            "OR (reconciled_outcome = 'not_delivered' AND "
            "telegram_message_id IS NULL))))",
            name="ck_sydney_question_outbox_reconciliation_shape",
        ),
        Index(
            "ix_sydney_question_outbox_dispatch", "state", "created_at", "id"
        ),
        Index(
            "ix_sydney_question_outbox_delivery_correlation",
            "clarification_id",
            "state",
            "telegram_chat_id",
            "sent_at",
            "id",
        ),
        Index(
            "ix_sydney_question_outbox_reconciled_delivery",
            "clarification_id",
            "state",
            "reconciled_outcome",
            "telegram_chat_id",
            "reconciled_at",
            "id",
        ),
        Index(
            "ix_sydney_question_outbox_kind_history",
            "clarification_id",
            "attempt_kind",
            "state",
            "sent_at",
            "attempt_number",
            "id",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    clarification_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "crm_task_clarifications.id",
            name="fk_sydney_question_outbox_clarification_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    attempt_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_initial_attempt_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    reply_to_attempt_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    question_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    telegram_message_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reconciled_outcome: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    reconciliation_reason: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    reconciliation_audit_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "agent_action_audits.id",
            name="fk_sydney_question_outbox_reconciliation_audit",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TaskSuggestionApprovalNonce(Base):
    __tablename__ = "crm_task_suggestion_approval_nonces"
    __table_args__ = (
        UniqueConstraint(
            "token_hash",
            name="uq_crm_task_suggestion_approval_nonces_token_hash",
        ),
        UniqueConstraint(
            "parent_nonce_id",
            name="uq_crm_task_suggestion_approval_nonces_parent",
        ),
        UniqueConstraint(
            "id",
            "suggestion_id",
            "suggestion_version",
            "payload_hash",
            name="uq_crm_task_suggestion_approval_nonces_resource_identity",
        ),
        ForeignKeyConstraint(
            (
                "parent_nonce_id",
                "suggestion_id",
                "suggestion_version",
                "payload_hash",
            ),
            (
                "crm_task_suggestion_approval_nonces.id",
                "crm_task_suggestion_approval_nonces.suggestion_id",
                "crm_task_suggestion_approval_nonces.suggestion_version",
                "crm_task_suggestion_approval_nonces.payload_hash",
            ),
            name="fk_crm_task_suggestion_approval_nonces_parent_id",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "octet_length(token_hash) = 32",
            name="ck_crm_task_suggestion_approval_nonces_token_hash",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_crm_task_suggestion_approval_nonces_payload_hash",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(kind = 'handoff' AND issuance_path = 'approval_link' AND "
            "administrator_id IS NULL AND parent_nonce_id IS NULL AND "
            "expires_at = issued_at + interval '15 minutes') OR (kind = "
            "'approval' AND issuance_path = 'handoff_exchange' AND "
            "administrator_id IS NOT NULL AND parent_nonce_id IS NOT NULL AND "
            "expires_at = issued_at + interval '5 minutes') OR (kind = "
            "'approval' AND issuance_path = 'command_prepare' AND "
            "administrator_id IS NOT NULL AND parent_nonce_id IS NULL AND "
            "expires_at = issued_at + interval '5 minutes')",
            name="ck_crm_task_suggestion_approval_nonces_shape",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "consumed_at IS NULL OR (consumed_at >= issued_at AND "
            "consumed_at <= expires_at)",
            name="ck_crm_task_suggestion_approval_nonces_consumption",
        ),
        CheckConstraint(
            "suggestion_version > 0",
            name="ck_crm_task_suggestion_approval_nonces_version",
        ),
        CheckConstraint(
            "parent_nonce_id IS NULL OR parent_nonce_id <> id",
            name="ck_crm_task_suggestion_approval_nonces_not_self",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    suggestion_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "crm_task_suggestions.id",
            name="fk_crm_task_suggestion_approval_nonces_suggestion_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    suggestion_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    issuance_path: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    administrator_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "admin_users.id",
            name="fk_crm_task_suggestion_approval_nonces_administrator_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    parent_nonce_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CRMTaskSuggestionEvent(Base):
    __tablename__ = "crm_task_suggestion_events"
    __table_args__ = (
        CheckConstraint(
            "suggestion_version > 0",
            name="ck_crm_task_suggestion_events_version",
        ),
        CheckConstraint(
            "event_type IN ('edit', 'clarification_asked', "
            "'clarification_answered', 'clarification_timed_out', "
            "'clarification_superseded', 'clarification_delivery_retry', "
            "'dismiss', 'preview', 'approve', 'apply', 'reprocess', "
            "'dismiss_proposed')",
            name="ck_crm_task_suggestion_events_type",
        ),
        CheckConstraint(
            "actor_type IN ('system', 'sydney', 'command_admin', "
            "'untrusted_hermes_input')",
            name="ck_crm_task_suggestion_events_actor",
        ),
        CheckConstraint(
            "event_data_json IS JSON OBJECT WITH UNIQUE KEYS AND "
            "octet_length(event_data_json) <= 8192",
            name="ck_crm_task_suggestion_events_data",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    suggestion_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "crm_task_suggestions.id",
            name="fk_crm_task_suggestion_events_suggestion_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    suggestion_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_data_json: Mapped[str] = mapped_column(Text, nullable=False)
    action_audit_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "agent_action_audits.id",
            name="fk_crm_task_suggestion_events_action_audit_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "CRMTaskClarification",
    "CRMTaskSuggestionEvent",
    "SydneyQuestionOutbox",
    "TaskSuggestionApprovalNonce",
]
