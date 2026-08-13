import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError


PROVENANCE_TABLES = {
    "crm_source_records",
    "crm_source_record_artifacts",
    "crm_entity_sources",
    "crm_reconciliation_runs",
    "crm_reconciliation_results",
}
SOURCE_RECORD_CHECKS = {
    "ck_crm_source_records_evidence_level": (
        "evidence_level IN ('observed_record', 'rendered_occurrence', "
        "'displayed_aggregate')"
    ),
    "ck_crm_source_records_capture_quality": (
        "capture_quality IN ('complete', 'partial', 'shell', 'error')"
    ),
}
RECONCILIATION_RUN_CHECKS = {
    "ck_crm_reconciliation_runs_mode": (
        "mode IN ('dry_run', 'apply', 'verify_only')"
    ),
    "ck_crm_reconciliation_runs_status": (
        "status IN ('running', 'completed', 'failed')"
    ),
}


def load_revision():
    revision_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "1d6e7f8a9b10_add_command_provenance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "command_provenance_revision_1d6e7f8a9b10",
        revision_path,
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def create_archive_prerequisite(connection):
    metadata = sa.MetaData()
    sa.Table(
        "crm_archive_artifacts",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    metadata.create_all(connection)


def check_constraints(connection, table_name):
    return {
        constraint["name"]: constraint["sqltext"]
        for constraint in sa.inspect(connection).get_check_constraints(table_name)
    }


def source_record_values(source_key, **overrides):
    values = {
        "source_system": "kw_command",
        "module": "contacts",
        "record_kind": "contact",
        "source_key": source_key,
        "evidence_level": "observed_record",
        "capture_quality": "complete",
        "parser_version": "command-v1",
    }
    values.update(overrides)
    return values


def reconciliation_run_values(fingerprint, **overrides):
    values = {
        "bundle_fingerprint": fingerprint,
        "parser_version": "command-v1",
        "mode": "dry_run",
        "status": "running",
    }
    values.update(overrides)
    return values


def assert_insert_rejected(connection, statement, values):
    with pytest.raises(IntegrityError):
        with connection.begin():
            connection.execute(statement, values)


def test_command_provenance_revision_upgrades_enforces_states_and_downgrades():
    engine = sa.create_engine("sqlite://")
    revision = load_revision()

    with engine.connect() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        connection.commit()
        create_archive_prerequisite(connection)
        connection.commit()

        revision.op = Operations(MigrationContext.configure(connection))
        revision.upgrade()
        connection.commit()

        assert set(sa.inspect(connection).get_table_names()) == {
            "crm_archive_artifacts",
            *PROVENANCE_TABLES,
        }
        assert check_constraints(connection, "crm_source_records") == SOURCE_RECORD_CHECKS
        assert (
            check_constraints(connection, "crm_reconciliation_runs")
            == RECONCILIATION_RUN_CHECKS
        )
        connection.commit()

        with connection.begin():
            connection.execute(
                sa.text(
                    """
                    INSERT INTO crm_source_records (
                        source_system, module, record_kind, source_key,
                        evidence_level, capture_quality, parser_version
                    ) VALUES (
                        :source_system, :module, :record_kind, :source_key,
                        :evidence_level, :capture_quality, :parser_version
                    )
                    """
                ),
                source_record_values("valid-source"),
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO crm_reconciliation_runs (
                        bundle_fingerprint, parser_version, mode, status
                    ) VALUES (
                        :bundle_fingerprint, :parser_version, :mode, :status
                    )
                    """
                ),
                reconciliation_run_values("a" * 64),
            )

        source_insert = sa.text(
            """
            INSERT INTO crm_source_records (
                source_system, module, record_kind, source_key,
                evidence_level, capture_quality, parser_version
            ) VALUES (
                :source_system, :module, :record_kind, :source_key,
                :evidence_level, :capture_quality, :parser_version
            )
            """
        )
        run_insert = sa.text(
            """
            INSERT INTO crm_reconciliation_runs (
                bundle_fingerprint, parser_version, mode, status
            ) VALUES (
                :bundle_fingerprint, :parser_version, :mode, :status
            )
            """
        )

        assert_insert_rejected(
            connection,
            source_insert,
            source_record_values("invalid-evidence", evidence_level="inferred_record"),
        )
        assert_insert_rejected(
            connection,
            source_insert,
            source_record_values("invalid-quality", capture_quality="unknown"),
        )
        assert_insert_rejected(
            connection,
            run_insert,
            reconciliation_run_values("b" * 64, mode="unsafe_apply"),
        )
        assert_insert_rejected(
            connection,
            run_insert,
            reconciliation_run_values("c" * 64, status="unknown"),
        )

        revision.downgrade()
        connection.commit()

        assert set(sa.inspect(connection).get_table_names()) == {
            "crm_archive_artifacts"
        }
