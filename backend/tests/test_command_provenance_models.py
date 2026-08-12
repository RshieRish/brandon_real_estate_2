import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, create_engine
from sqlalchemy.exc import IntegrityError

from models.command_provenance import (
    CRMEntitySource,
    CRMReconciliationResult,
    CRMReconciliationRun,
    CRMSourceRecord,
    CRMSourceRecordArtifact,
    CaptureQuality,
    EvidenceLevel,
)


def unique_constraint_columns(model):
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def check_constraint_expressions(model):
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


def index_columns(model):
    return {
        index.name: tuple(column.name for column in index.columns)
        for index in model.__table__.indexes
    }


def column_defaults(model):
    return {
        column.name: column.default.arg
        for column in model.__table__.columns
        if column.default is not None
    }


def test_provenance_enums_expose_only_supported_evidence_and_capture_states():
    assert {item.value for item in EvidenceLevel} == {
        "observed_record",
        "rendered_occurrence",
        "displayed_aggregate",
    }
    assert {item.value for item in CaptureQuality} == {
        "complete",
        "partial",
        "shell",
        "error",
    }


def test_source_record_states_have_exact_database_check_constraints():
    assert check_constraint_expressions(CRMSourceRecord) == {
        "ck_crm_source_records_evidence_level": (
            "evidence_level IN ('observed_record', 'rendered_occurrence', "
            "'displayed_aggregate')"
        ),
        "ck_crm_source_records_capture_quality": (
            "capture_quality IN ('complete', 'partial', 'shell', 'error')"
        ),
    }


def test_reconciliation_run_states_have_exact_database_check_constraints():
    assert check_constraint_expressions(CRMReconciliationRun) == {
        "ck_crm_reconciliation_runs_mode": (
            "mode IN ('dry_run', 'apply', 'verify_only')"
        ),
        "ck_crm_reconciliation_runs_status": (
            "status IN ('running', 'completed', 'failed')"
        ),
    }


def test_reconciliation_runs_store_exclusive_worker_claims():
    columns = CRMReconciliationRun.__table__.columns

    assert columns["claim_token"].type.length == 64
    assert columns["claim_token"].nullable is False
    assert columns["claimed_at"].nullable is True
    assert columns["claimed_at"].type.timezone is True


def test_source_record_identity_is_exactly_parser_versioned():
    assert unique_constraint_columns(CRMSourceRecord) == {
        ("source_system", "module", "record_kind", "source_key", "parser_version"),
    }


def test_provenance_links_have_exact_database_uniqueness_contracts():
    assert unique_constraint_columns(CRMSourceRecordArtifact) == {
        ("source_record_id", "artifact_id"),
    }
    assert unique_constraint_columns(CRMEntitySource) == {
        ("source_record_id", "entity_type"),
        ("entity_type", "entity_id", "source_record_id"),
    }


def test_reconciliation_result_identity_is_exactly_run_source_and_module():
    assert unique_constraint_columns(CRMReconciliationResult) == {
        ("run_id", "source_system", "module"),
    }


def test_provenance_models_expose_safe_defaults():
    assert column_defaults(CRMSourceRecord) == {
        "display_label": "",
        "payload_json": "{}",
        "capture_quality": CaptureQuality.COMPLETE.value,
    }
    assert column_defaults(CRMSourceRecordArtifact) == {"relation": "evidence"}
    assert column_defaults(CRMReconciliationRun) == {
        "status": "running",
        "requested_modules_json": "[]",
        "error_text": "",
        "claim_token": "",
    }
    assert column_defaults(CRMReconciliationResult) == {
        "observed_count": 0,
        "rendered_count": 0,
        "normalized_count": 0,
        "evidence_only_count": 0,
        "unmatched_count": 0,
        "duplicate_content_count": 0,
        "error_count": 0,
        "details_json": "{}",
    }


def test_provenance_lookup_indexes_cover_module_entity_and_fingerprint_queries():
    assert index_columns(CRMSourceRecord) == {
        "ix_crm_source_records_module_level": (
            "source_system",
            "module",
            "evidence_level",
        ),
    }
    assert index_columns(CRMEntitySource) == {
        "ix_crm_entity_sources_entity": ("entity_type", "entity_id"),
    }
    assert index_columns(CRMReconciliationRun) == {
        "ix_crm_reconciliation_runs_bundle_fingerprint": ("bundle_fingerprint",),
    }


def test_provenance_foreign_keys_preserve_artifacts_and_cascade_dependents():
    artifact_link_foreign_keys = {
        column.name: next(iter(column.foreign_keys)).ondelete
        for column in CRMSourceRecordArtifact.__table__.columns
        if column.foreign_keys
    }
    entity_link_foreign_keys = {
        column.name: next(iter(column.foreign_keys)).ondelete
        for column in CRMEntitySource.__table__.columns
        if column.foreign_keys
    }
    result_foreign_keys = {
        column.name: next(iter(column.foreign_keys)).ondelete
        for column in CRMReconciliationResult.__table__.columns
        if column.foreign_keys
    }

    assert artifact_link_foreign_keys == {
        "source_record_id": "CASCADE",
        "artifact_id": "RESTRICT",
    }
    assert entity_link_foreign_keys == {"source_record_id": "CASCADE"}
    assert result_foreign_keys == {"run_id": "CASCADE"}


def test_source_records_include_shared_immutable_capture_timestamps():
    assert {"created_at", "updated_at", "captured_at"}.issubset(
        CRMSourceRecord.__table__.columns.keys()
    )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("evidence_level", "inferred_record"),
        ("capture_quality", "unknown"),
    ],
)
def test_source_record_database_rejects_invalid_states(field, invalid_value):
    engine = create_engine("sqlite://")
    CRMSourceRecord.__table__.create(engine)
    valid_values = {
        "source_system": "kw_command",
        "module": "contacts",
        "record_kind": "contact",
        "source_key": "valid-source",
        "evidence_level": EvidenceLevel.OBSERVED_RECORD.value,
        "capture_quality": CaptureQuality.COMPLETE.value,
        "parser_version": "command-v1",
    }

    with engine.begin() as connection:
        connection.execute(CRMSourceRecord.__table__.insert(), valid_values)

    invalid_values = {
        **valid_values,
        "source_key": f"invalid-{field}",
        field: invalid_value,
    }
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(CRMSourceRecord.__table__.insert(), invalid_values)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("mode", "unsafe_apply"),
        ("status", "unknown"),
    ],
)
def test_reconciliation_run_database_rejects_invalid_states(field, invalid_value):
    engine = create_engine("sqlite://")
    CRMReconciliationRun.__table__.create(engine)
    valid_values = {
        "bundle_fingerprint": "a" * 64,
        "parser_version": "command-v1",
        "mode": "dry_run",
        "status": "running",
    }

    with engine.begin() as connection:
        connection.execute(CRMReconciliationRun.__table__.insert(), valid_values)

    invalid_values = {
        **valid_values,
        "bundle_fingerprint": "b" * 64,
        field: invalid_value,
    }
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(CRMReconciliationRun.__table__.insert(), invalid_values)
