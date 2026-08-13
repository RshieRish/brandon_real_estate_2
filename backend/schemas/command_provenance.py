"""Typed, byte-safe API contracts for recovered Command provenance."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ProvenanceSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ArchiveArtifactMetadataOut(ProvenanceSchema):
    id: int
    domain: str
    artifact_type: str
    filename: str
    source_path: str
    sha256: str
    size_bytes: int
    text_preview: str
    relation: str


class SourceRecordOut(ProvenanceSchema):
    id: int
    source_system: str
    module: str
    record_kind: str
    source_key: str
    evidence_level: str
    display_label: str
    payload: dict[str, Any]
    capture_quality: str
    captured_at: datetime | None
    parser_version: str
    created_at: datetime
    updated_at: datetime


class SourceRecordDetailOut(SourceRecordOut):
    artifacts: list[ArchiveArtifactMetadataOut]


class SourceRecordPageOut(ProvenanceSchema):
    total: int
    page: int
    page_size: int
    rows: list[SourceRecordOut]


class EntitySourcesOut(ProvenanceSchema):
    entity_type: str
    entity_id: int
    sources: list[SourceRecordDetailOut]


class ReconciliationResultOut(ProvenanceSchema):
    id: int
    source_system: str
    module: str
    expected_count: int | None
    observed_count: int
    rendered_count: int
    normalized_count: int
    evidence_only_count: int
    unmatched_count: int
    duplicate_content_count: int
    error_count: int
    details: dict[str, Any]


class ReconciliationRunOut(ProvenanceSchema):
    id: int
    bundle_fingerprint: str
    parser_version: str
    mode: str
    status: str
    requested_modules: list[str]
    error_text: str
    started_at: datetime
    completed_at: datetime | None


class ReconciliationRunDetailOut(ReconciliationRunOut):
    results: list[ReconciliationResultOut]


class ReconciliationRunPageOut(ProvenanceSchema):
    total: int
    page: int
    page_size: int
    rows: list[ReconciliationRunOut]
