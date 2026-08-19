"""Idempotency, provenance, and immutable lifecycle records for CRM tasks."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.command import Timestamped


class CRMTaskCreationRequest(Timestamped, Base):
    """A sanitized, durable idempotency claim for one task creation request."""

    __tablename__ = "crm_task_creation_requests"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "idempotency_key",
            name="uq_crm_task_creation_request_scope_key",
        ),
        CheckConstraint(
            "state IN ('applying', 'applied', 'failed')",
            name="ck_crm_task_creation_requests_state",
        ),
        Index("ix_crm_task_creation_requests_task_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32), default="applying")
    failure_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    metadata_json: Mapped[str] = mapped_column(
        Text, default="{}", nullable=False
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_tasks.id", ondelete="RESTRICT"), nullable=True
    )
    result_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CRMTaskSource(Base):
    """A stable external or internal source identity linked to one task."""

    __tablename__ = "crm_task_sources"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "source_key",
            name="uq_crm_task_source_identity",
        ),
        Index("ix_crm_task_sources_task_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("crm_tasks.id", ondelete="RESTRICT")
    )
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(255))
    source_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CRMRecordLifecycleEvent(Base):
    """An immutable, replay-safe record of one CRM lifecycle action."""

    __tablename__ = "crm_record_lifecycle_events"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "action",
            "request_id",
            name="uq_crm_record_lifecycle_event_request",
        ),
        Index(
            "ix_crm_record_lifecycle_events_entity_created_at",
            "entity_type",
            "entity_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    request_hash: Mapped[str] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(255))
    result_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    metadata_json: Mapped[str] = mapped_column(
        Text, default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
