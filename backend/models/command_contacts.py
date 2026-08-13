"""Additive contact evidence and profile entities for the Command workspace."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.command import Timestamped


CONTACT_SECTIONS = (
    "timeline",
    "opportunities",
    "smart_plans",
    "notes",
    "saved_searches",
    "tasks_to_do",
    "tasks_completed",
    "tasks_archived",
)

CAPTURE_QUALITIES = ("complete", "partial", "shell", "error")
YEAR_QUALITIES = ("verified", "yearless", "sentinel", "unknown")

_SOURCE_CONTACT_HEX_REMAINDER = "source_contact_id"
for _hex_character in "0123456789abcdef":
    _SOURCE_CONTACT_HEX_REMAINDER = (
        f"replace({_SOURCE_CONTACT_HEX_REMAINDER}, '{_hex_character}', '')"
    )


def canonical_json_text(value: object) -> str:
    """Return deterministic JSON text for contact-domain JSON columns."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


class CRMContactProfile(Timestamped, Base):
    __tablename__ = "crm_contact_profiles"
    __table_args__ = (
        CheckConstraint(
            "health_score IS NULL OR health_score BETWEEN 0 AND 100",
            name="ck_crm_contact_profile_health_score",
        ),
        CheckConstraint(
            "birth_month IS NULL OR birth_month BETWEEN 1 AND 12",
            name="ck_crm_contact_profile_birth_month",
        ),
        CheckConstraint(
            "birth_day IS NULL OR birth_day BETWEEN 1 AND 31",
            name="ck_crm_contact_profile_birth_day",
        ),
        CheckConstraint(
            "anniversary_month IS NULL OR anniversary_month BETWEEN 1 AND 12",
            name="ck_crm_contact_profile_anniversary_month",
        ),
        CheckConstraint(
            "anniversary_day IS NULL OR anniversary_day BETWEEN 1 AND 31",
            name="ck_crm_contact_profile_anniversary_day",
        ),
        CheckConstraint(
            "birth_year_quality IN ('verified', 'yearless', 'sentinel', 'unknown')",
            name="ck_crm_contact_profile_birth_year_quality",
        ),
        CheckConstraint(
            "anniversary_year_quality IN "
            "('verified', 'yearless', 'sentinel', 'unknown')",
            name="ck_crm_contact_profile_anniversary_year_quality",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE"), unique=True
    )
    recovered_identity_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True
    )
    legal_name: Mapped[str | None] = mapped_column(String(255))
    preferred_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    lead_source: Mapped[str | None] = mapped_column(String(255))
    account_name: Mapped[str | None] = mapped_column(String(255))
    health_score: Mapped[int | None] = mapped_column(Integer)
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_interaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    birth_month: Mapped[int | None] = mapped_column(Integer)
    birth_day: Mapped[int | None] = mapped_column(Integer)
    birth_year: Mapped[int | None] = mapped_column(Integer)
    birth_year_quality: Mapped[str] = mapped_column(String(24), default="unknown")
    birth_raw: Mapped[str | None] = mapped_column(String(64))
    anniversary_month: Mapped[int | None] = mapped_column(Integer)
    anniversary_day: Mapped[int | None] = mapped_column(Integer)
    anniversary_year: Mapped[int | None] = mapped_column(Integer)
    anniversary_year_quality: Mapped[str] = mapped_column(
        String(24), default="unknown"
    )
    anniversary_raw: Mapped[str | None] = mapped_column(String(64))


class CRMContactMethod(Timestamped, Base):
    __tablename__ = "crm_contact_methods"
    __table_args__ = (
        UniqueConstraint(
            "contact_id", "source_key", name="uq_crm_contact_method_source_key"
        ),
        CheckConstraint(
            "kind IN ('email', 'phone')", name="ck_crm_contact_method_kind"
        ),
        Index(
            "ix_crm_contact_methods_kind_normalized", "kind", "normalized_value"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="RESTRICT")
    )
    source_key: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(24))
    label: Mapped[str | None] = mapped_column(String(120))
    raw_value: Mapped[str | None] = mapped_column(String(500))
    normalized_value: Mapped[str | None] = mapped_column(String(500))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class CRMContactAddress(Timestamped, Base):
    __tablename__ = "crm_contact_addresses"
    __table_args__ = (
        UniqueConstraint(
            "contact_id", "source_key", name="uq_crm_contact_address_source_key"
        ),
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_crm_contact_address_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_crm_contact_address_longitude",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="RESTRICT")
    )
    source_key: Mapped[str] = mapped_column(String(500))
    address_type: Mapped[str | None] = mapped_column(String(64))
    line1: Mapped[str | None] = mapped_column(String(255))
    line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(120))
    formatted: Mapped[str | None] = mapped_column(String(500))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class CRMContactNeighborhood(Timestamped, Base):
    __tablename__ = "crm_contact_neighborhoods"
    __table_args__ = (
        UniqueConstraint(
            "contact_id",
            "source_key",
            name="uq_crm_contact_neighborhood_source_key",
        ),
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_crm_contact_neighborhood_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_crm_contact_neighborhood_longitude",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="RESTRICT")
    )
    source_key: Mapped[str] = mapped_column(String(500))
    name: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))


class CRMContactOwnership(Timestamped, Base):
    __tablename__ = "crm_contact_ownerships"
    __table_args__ = (
        UniqueConstraint(
            "contact_id", "source_key", name="uq_crm_contact_ownership_source_key"
        ),
        CheckConstraint(
            "role IN ('owner', 'assignee', 'collaborator')",
            name="ck_crm_contact_ownership_role",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="RESTRICT")
    )
    source_key: Mapped[str] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(24))
    provider_actor_id: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class CRMContactRelationship(Timestamped, Base):
    __tablename__ = "crm_contact_relationships"
    __table_args__ = (
        UniqueConstraint(
            "contact_id",
            "source_key",
            name="uq_crm_contact_relationship_source_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="RESTRICT")
    )
    source_key: Mapped[str] = mapped_column(String(500))
    relationship_type: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str | None] = mapped_column(String(255))
    related_source_contact_id: Mapped[str | None] = mapped_column(String(24))
    related_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="SET NULL")
    )


class CRMContactPreference(Timestamped, Base):
    __tablename__ = "crm_contact_preferences"
    __table_args__ = (
        UniqueConstraint(
            "contact_id",
            "source_key",
            name="uq_crm_contact_preference_source_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="RESTRICT")
    )
    source_key: Mapped[str] = mapped_column(String(500))
    preference_key: Mapped[str] = mapped_column(String(255))
    value_json: Mapped[str] = mapped_column(Text, default="{}")


class CRMContactCapturePosition(Timestamped, Base):
    __tablename__ = "crm_contact_capture_positions"
    __table_args__ = (
        UniqueConstraint(
            "bundle_fingerprint",
            "capture_ordinal",
            name="uq_crm_contact_capture_bundle_ordinal",
        ),
        UniqueConstraint(
            "bundle_fingerprint",
            "source_contact_id",
            name="uq_crm_contact_capture_bundle_source",
        ),
        UniqueConstraint(
            "source_record_id", name="uq_crm_contact_capture_source_record"
        ),
        CheckConstraint(
            "capture_ordinal > 0", name="ck_crm_contact_capture_ordinal"
        ),
        CheckConstraint(
            "length(source_contact_id) = 24 "
            "AND source_contact_id = lower(source_contact_id) "
            f"AND {_SOURCE_CONTACT_HEX_REMAINDER} = ''",
            name="ck_crm_contact_capture_source_contact_id",
        ),
        CheckConstraint(
            "capture_quality IN ('complete', 'partial', 'shell', 'error')",
            name="ck_crm_contact_capture_quality",
        ),
        Index(
            "ix_crm_contact_capture_lookup", "contact_id", "bundle_fingerprint"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="RESTRICT")
    )
    bundle_fingerprint: Mapped[str] = mapped_column(String(64))
    capture_ordinal: Mapped[int] = mapped_column(Integer)
    source_contact_id: Mapped[str] = mapped_column(String(24))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capture_quality: Mapped[str] = mapped_column(String(24), default="complete")
    limitations_json: Mapped[str] = mapped_column(Text, default="[]")


class CRMContactSectionCapture(Timestamped, Base):
    __tablename__ = "crm_contact_section_captures"
    __table_args__ = (
        UniqueConstraint(
            "capture_position_id",
            "section_name",
            name="uq_crm_contact_position_section",
        ),
        UniqueConstraint(
            "source_record_id", name="uq_crm_contact_section_source_record"
        ),
        CheckConstraint(
            "section_name IN "
            "('timeline', 'opportunities', 'smart_plans', 'notes', "
            "'saved_searches', 'tasks_to_do', 'tasks_completed', 'tasks_archived')",
            name="ck_crm_contact_section_name",
        ),
        CheckConstraint(
            "capture_quality IN ('complete', 'partial', 'shell', 'error')",
            name="ck_crm_contact_section_quality",
        ),
        CheckConstraint(
            "row_count >= 0", name="ck_crm_contact_section_row_count"
        ),
        Index(
            "ix_crm_contact_section_lookup", "capture_position_id", "section_name"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capture_position_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contact_capture_positions.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="RESTRICT")
    )
    section_name: Mapped[str] = mapped_column(String(32))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capture_quality: Mapped[str] = mapped_column(String(24), default="complete")
    is_empty: Mapped[bool] = mapped_column(Boolean, default=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    limitations_json: Mapped[str] = mapped_column(Text, default="[]")


class CRMContactTimelineEvent(Timestamped, Base):
    __tablename__ = "crm_contact_timeline_events"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "source_event_key",
            name="uq_crm_contact_timeline_source_event",
        ),
        UniqueConstraint(
            "source_record_id", name="uq_crm_contact_timeline_source_record"
        ),
        Index(
            "ix_crm_contact_timeline_order", "contact_id", "occurred_at", "id"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="RESTRICT")
    )
    source_system: Mapped[str] = mapped_column(String(64))
    source_event_key: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)
    actor_label: Mapped[str | None] = mapped_column(String(255))
    channel: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attributes_json: Mapped[str] = mapped_column(Text, default="{}")


class CRMContactAuditEvent(Base):
    __tablename__ = "crm_contact_audit_events"
    __table_args__ = (
        Index("ix_crm_contact_audit_order", "contact_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE")
    )
    actor_subject: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(120))
    before_json: Mapped[str] = mapped_column(Text, default="{}")
    after_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
