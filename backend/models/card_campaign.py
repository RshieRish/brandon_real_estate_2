"""Approval-gated physical-card campaign and immutable delivery evidence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from database import Base
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column


def _uuid_primary_key() -> Mapped[UUID]:
    return mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class CardProviderConnection(Base):
    __tablename__ = "card_provider_connections"
    __table_args__ = (
        CheckConstraint(
            "state IN ('disconnected', 'connected', 'error')",
            name="ck_card_provider_connections_state",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_card_provider_connections_version",
        ),
        CheckConstraint(
            "account_reference_hash IS NULL OR "
            "account_reference_hash ~ '^[0-9a-f]{64}$'",
            name="ck_card_provider_connections_account_hash",
        ).ddl_if(dialect="postgresql"),
    )

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(
        String(24), default="disconnected", server_default="disconnected"
    )
    account_reference_hash: Mapped[str | None] = mapped_column(String(64))
    display_label: Mapped[str | None] = mapped_column(String(120))
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CardCampaign(Base):
    __tablename__ = "card_campaigns"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_card_campaigns_request_id"),
        UniqueConstraint("send_request_id", name="uq_card_campaigns_send_request_id"),
        CheckConstraint(
            "month BETWEEN 1 AND 12",
            name="ck_card_campaigns_month",
        ),
        CheckConstraint(
            "include_birthdays OR include_home_anniversaries",
            name="ck_card_campaigns_selection",
        ),
        CheckConstraint(
            "status IN ('draft', 'needs_addresses', 'needs_connection', "
            "'ready_for_review', 'approved', 'sending', 'sent', "
            "'partially_sent', 'failed', 'delivery_uncertain')",
            name="ck_card_campaigns_status",
        ),
        CheckConstraint(
            "purpose = 'celebrations'",
            name="ck_card_campaigns_purpose",
        ),
        CheckConstraint(
            "draft_payload_hash ~ '^[0-9a-f]{64}$' AND "
            "audience_checksum ~ '^[0-9a-f]{64}$'",
            name="ck_card_campaigns_checksum",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "estimated_cost_cents IS NULL OR estimated_cost_cents >= 0",
            name="ck_card_campaigns_cost",
        ),
        CheckConstraint(
            "version > 0 AND (approved_version IS NULL OR "
            "(approved_version > 0 AND approved_version <= version))",
            name="ck_card_campaigns_version",
        ),
        CheckConstraint(
            "((status IN ('draft', 'needs_addresses', 'needs_connection', "
            "'ready_for_review') AND approved_by_actor IS NULL AND "
            "approved_at IS NULL AND approved_version IS NULL AND "
            "send_request_id IS NULL) OR "
            "(status IN ('approved', 'sending', 'sent', 'partially_sent', "
            "'failed', 'delivery_uncertain') AND approved_by_actor IS NOT NULL "
            "AND approved_at IS NOT NULL AND approved_version IS NOT NULL AND "
            "send_request_id IS NOT NULL))",
            name="ck_card_campaigns_approval_shape",
        ),
        Index("ix_card_campaigns_status_created", "status", "created_at", "id"),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    request_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    draft_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32),
        default="send_out_cards",
        server_default="send_out_cards",
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(32), default="celebrations", server_default="celebrations"
    )
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    include_birthdays: Mapped[bool] = mapped_column(Boolean, nullable=False)
    include_home_anniversaries: Mapped[bool] = mapped_column(Boolean, nullable=False)
    audience_ref: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    audience_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False
    )
    default_birthday_message: Mapped[str] = mapped_column(Text, nullable=False)
    default_anniversary_message: Mapped[str] = mapped_column(Text, nullable=False)
    birthday_design_key: Mapped[str] = mapped_column(String(120), nullable=False)
    anniversary_design_key: Mapped[str] = mapped_column(String(120), nullable=False)
    estimated_cost_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(
        String(3), default="USD", server_default="USD", nullable=False
    )
    approved_by_actor: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_version: Mapped[int | None] = mapped_column(Integer)
    send_request_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CardCampaignRecipient(Base):
    __tablename__ = "card_campaign_recipients"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "contact_id",
            "celebration_kind",
            name="uq_card_campaign_recipients_contact_kind",
        ),
        UniqueConstraint(
            "id",
            "campaign_id",
            name="uq_card_campaign_recipients_id_campaign",
        ),
        CheckConstraint(
            "celebration_kind IN ('birthday', 'home_anniversary') AND "
            "celebration_month BETWEEN 1 AND 12 AND "
            "celebration_day BETWEEN 1 AND 31 AND "
            "celebration_year_quality IN "
            "('verified', 'yearless', 'sentinel', 'unknown') AND "
            "celebration_origin IN ('internal_crm', 'recovered')",
            name="ck_card_campaign_recipients_celebration",
        ),
        CheckConstraint(
            "address_status IN ('ready', 'missing') AND "
            "((address_status = 'ready' AND address_id IS NOT NULL AND "
            "address_snapshot_json IS NOT NULL) OR "
            "(address_status = 'missing' AND address_id IS NULL AND "
            "address_snapshot_json IS NULL))",
            name="ck_card_campaign_recipients_address_shape",
        ),
        CheckConstraint(
            "address_snapshot_json IS NULL OR "
            "(address_snapshot_json IS JSON OBJECT WITH UNIQUE KEYS AND "
            "octet_length(address_snapshot_json) <= 4096)",
            name="ck_card_campaign_recipients_address_json",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "((excluded AND exclusion_reason IS NOT NULL) OR "
            "(NOT excluded AND exclusion_reason IS NULL))",
            name="ck_card_campaign_recipients_exclusion_shape",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_card_campaign_recipients_content_hash",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_card_campaign_recipients_campaign_status",
            "campaign_id",
            "excluded",
            "address_status",
            "id",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("card_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="RESTRICT"), nullable=False
    )
    celebration_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    celebration_month: Mapped[int] = mapped_column(Integer, nullable=False)
    celebration_day: Mapped[int] = mapped_column(Integer, nullable=False)
    celebration_year: Mapped[int | None] = mapped_column(Integer)
    celebration_year_quality: Mapped[str] = mapped_column(String(24), nullable=False)
    celebration_origin: Mapped[str] = mapped_column(String(24), nullable=False)
    display_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    message_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    design_key_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    address_status: Mapped[str] = mapped_column(String(24), nullable=False)
    address_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_contact_addresses.id", ondelete="RESTRICT")
    )
    address_snapshot_json: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    excluded: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    exclusion_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CardDeliveryAttempt(Base):
    __tablename__ = "card_delivery_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ("recipient_id", "campaign_id"),
            (
                "card_campaign_recipients.id",
                "card_campaign_recipients.campaign_id",
            ),
            name="fk_card_delivery_attempts_recipient_campaign",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "recipient_id",
            "request_id",
            name="uq_card_delivery_attempts_recipient_request",
        ),
        UniqueConstraint(
            "provider_idempotency_key",
            name="uq_card_delivery_attempts_provider_key",
        ),
        UniqueConstraint(
            "id",
            "campaign_id",
            "recipient_id",
            name="uq_card_delivery_attempts_identity",
        ),
        CheckConstraint(
            "attempt_number > 0",
            name="ck_card_delivery_attempts_number",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_card_delivery_attempts_content_hash",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_card_delivery_attempts_campaign_created",
            "campaign_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("card_campaigns.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recipient_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    request_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_idempotency_key: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intended_by_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class CardProviderReceipt(Base):
    __tablename__ = "card_provider_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ("attempt_id", "campaign_id", "recipient_id"),
            (
                "card_delivery_attempts.id",
                "card_delivery_attempts.campaign_id",
                "card_delivery_attempts.recipient_id",
            ),
            name="fk_card_provider_receipts_attempt_identity",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "attempt_id",
            name="uq_card_provider_receipts_attempt",
        ),
        CheckConstraint(
            "outcome IN ('confirmed', 'rejected', 'ambiguous')",
            name="ck_card_provider_receipts_outcome",
        ),
        CheckConstraint(
            "((provider_receipt_id IS NULL AND provider_receipt_hash IS NULL) OR "
            "(provider_receipt_id IS NOT NULL AND provider_receipt_hash ~ "
            "'^[0-9a-f]{64}$')) AND "
            "(outcome <> 'confirmed' OR provider_receipt_id IS NOT NULL)",
            name="ck_card_provider_receipts_provider_reference",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "details_json IS JSON OBJECT WITH UNIQUE KEYS AND "
            "octet_length(details_json) <= 4096",
            name="ck_card_provider_receipts_details_json",
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_card_provider_receipts_provider_reference",
            "provider",
            "provider_receipt_hash",
            unique=True,
            postgresql_where=text("provider_receipt_hash IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_card_provider_receipts_campaign_created",
            "campaign_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = _uuid_primary_key()
    attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    recipient_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_receipt_id: Mapped[str | None] = mapped_column(String(255))
    provider_receipt_hash: Mapped[str | None] = mapped_column(String(64))
    provider_status: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_code: Mapped[str | None] = mapped_column(String(120))
    details_json: Mapped[str] = mapped_column(
        Text, default="{}", server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = _created_at()


__all__ = [
    "CardCampaign",
    "CardCampaignRecipient",
    "CardDeliveryAttempt",
    "CardProviderConnection",
    "CardProviderReceipt",
]
