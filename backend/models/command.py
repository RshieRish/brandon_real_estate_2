"""Persistent internal CRM entities for the Command workspace."""
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AgreementStatus(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    READY = "ready"
    SHARED = "shared"
    VIEWED = "viewed"
    COMPLETED = "completed"
    VOIDED = "voided"
    EXPIRED = "expired"


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CRMContact(Timestamped, Base):
    __tablename__ = "crm_contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True, unique=True)
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    stage: Mapped[str] = mapped_column(String(50), default="lead")


class CRMActivity(Base):
    __tablename__ = "crm_activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contacts.id"))
    kind: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column("metadata", Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CRMTask(Timestamped, Base):
    __tablename__ = "crm_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contacts.id"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="open")
    priority: Mapped[str] = mapped_column(String(32), default="normal")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __init__(self, **kwargs):
        kwargs.setdefault("status", "open")
        kwargs.setdefault("priority", "normal")
        super().__init__(**kwargs)


class CRMNote(Timestamped, Base):
    __tablename__ = "crm_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"))
    body: Mapped[str] = mapped_column(Text)

class CRMTag(Base):
    __tablename__ = "crm_tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)

class CRMSavedSearch(Timestamped, Base):
    __tablename__ = "crm_saved_searches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contacts.id"))
    name: Mapped[str] = mapped_column(String(255))
    criteria_json: Mapped[str] = mapped_column("criteria", Text, default="{}")


class CRMSmartPlan(Timestamped, Base):
    __tablename__ = "crm_smart_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")


class CRMSmartPlanStep(Base):
    __tablename__ = "crm_smart_plan_steps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    smart_plan_id: Mapped[int] = mapped_column(ForeignKey("crm_smart_plans.id"))
    position: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(50))
    payload_json: Mapped[str] = mapped_column("payload", Text, default="{}")


class CRMSmartPlanEnrollment(Timestamped, Base):
    __tablename__ = "crm_smart_plan_enrollments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    smart_plan_id: Mapped[int] = mapped_column(ForeignKey("crm_smart_plans.id"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"))
    status: Mapped[str] = mapped_column(String(32), default="active")


class CRMOpportunity(Timestamped, Base):
    __tablename__ = "crm_opportunities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    stage: Mapped[str] = mapped_column(String(50), default="cultivate")
    value_cents: Mapped[int | None] = mapped_column(Integer)

class CRMOpportunityContact(Base):
    __tablename__ = "crm_opportunity_contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("crm_opportunities.id"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"))
    role: Mapped[str] = mapped_column(String(50), default="client")

class CRMOpportunityVendor(Base):
    __tablename__ = "crm_opportunity_vendors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("crm_opportunities.id"))
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(80), default="vendor")

class CRMOpportunityOffer(Base):
    __tablename__ = "crm_opportunity_offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("crm_opportunities.id"))
    amount_cents: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft")


class CRMListingRecord(Timestamped, Base):
    __tablename__ = "crm_listing_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address: Mapped[str] = mapped_column(String(500))
    latitude: Mapped[str | None] = mapped_column(String(32))
    longitude: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="active")


class CRMAgreementTemplate(Timestamped, Base):
    __tablename__ = "crm_agreement_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")


class CRMAgreement(Timestamped, Base):
    __tablename__ = "crm_agreements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("crm_agreement_templates.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contacts.id"))
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default=AgreementStatus.DRAFT.value)


class CRMAgreementEvent(Base):
    __tablename__ = "crm_agreement_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agreement_id: Mapped[int] = mapped_column(ForeignKey("crm_agreements.id"))
    event_type: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class CRMAgreementRecipient(Base):
    __tablename__ = "crm_agreement_recipients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agreement_id: Mapped[int] = mapped_column(ForeignKey("crm_agreements.id"))
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="recipient")


class CRMFileAsset(Timestamped, Base):
    __tablename__ = "crm_file_assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
