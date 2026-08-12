"""Source provenance and reconciliation records for recovered CRM evidence."""
from datetime import datetime
from enum import Enum

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
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.command import Timestamped


class EvidenceLevel(str, Enum):
    OBSERVED_RECORD = "observed_record"
    RENDERED_OCCURRENCE = "rendered_occurrence"
    DISPLAYED_AGGREGATE = "displayed_aggregate"


class CaptureQuality(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    SHELL = "shell"
    ERROR = "error"


class CRMSourceRecord(Timestamped, Base):
    __tablename__ = "crm_source_records"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "module",
            "record_kind",
            "source_key",
            "parser_version",
            name="uq_crm_source_record_identity",
        ),
        CheckConstraint(
            "evidence_level IN ('observed_record', 'rendered_occurrence', "
            "'displayed_aggregate')",
            name="ck_crm_source_records_evidence_level",
        ),
        CheckConstraint(
            "capture_quality IN ('complete', 'partial', 'shell', 'error')",
            name="ck_crm_source_records_capture_quality",
        ),
        Index(
            "ix_crm_source_records_module_level",
            "source_system",
            "module",
            "evidence_level",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_system: Mapped[str] = mapped_column(String(64))
    module: Mapped[str] = mapped_column(String(64))
    record_kind: Mapped[str] = mapped_column(String(64))
    source_key: Mapped[str] = mapped_column(String(500))
    evidence_level: Mapped[str] = mapped_column(String(32))
    display_label: Mapped[str] = mapped_column(String(500), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    capture_quality: Mapped[str] = mapped_column(
        String(32), default=CaptureQuality.COMPLETE.value
    )
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parser_version: Mapped[str] = mapped_column(String(64))


class CRMSourceRecordArtifact(Base):
    __tablename__ = "crm_source_record_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "source_record_id",
            "artifact_id",
            name="uq_crm_source_record_artifact",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="CASCADE")
    )
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("crm_archive_artifacts.id", ondelete="RESTRICT")
    )
    relation: Mapped[str] = mapped_column(String(32), default="evidence")


class CRMEntitySource(Base):
    __tablename__ = "crm_entity_sources"
    __table_args__ = (
        UniqueConstraint(
            "source_record_id",
            "entity_type",
            name="uq_crm_source_entity_type",
        ),
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "source_record_id",
            name="uq_crm_entity_source",
        ),
        Index("ix_crm_entity_sources_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int] = mapped_column(Integer)
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("crm_source_records.id", ondelete="CASCADE")
    )


class CRMReconciliationRun(Base):
    __tablename__ = "crm_reconciliation_runs"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('dry_run', 'apply', 'verify_only')",
            name="ck_crm_reconciliation_runs_mode",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_crm_reconciliation_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="running")
    requested_modules_json: Mapped[str] = mapped_column(Text, default="[]")
    error_text: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CRMReconciliationResult(Base):
    __tablename__ = "crm_reconciliation_results"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_system",
            "module",
            name="uq_crm_reconciliation_result",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("crm_reconciliation_runs.id", ondelete="CASCADE")
    )
    source_system: Mapped[str] = mapped_column(String(64))
    module: Mapped[str] = mapped_column(String(64))
    expected_count: Mapped[int | None] = mapped_column(Integer)
    observed_count: Mapped[int] = mapped_column(Integer, default=0)
    rendered_count: Mapped[int] = mapped_column(Integer, default=0)
    normalized_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_only_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_content_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
