from __future__ import annotations

import importlib.util
import os
import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateIndex

import models
from database import Base
from models.command import CRMTask
from models.crm_task_lifecycle import (
    CRMRecordLifecycleEvent,
    CRMTaskCreationRequest,
    CRMTaskSource,
)


REVISION = "81a4d2c6e9f0"
DOWN_REVISION = "7d1f3a5b6c8e"
NEW_TABLES = {
    "crm_task_creation_requests",
    "crm_task_sources",
    "crm_record_lifecycle_events",
}
TASK_INDEXES = {
    "ix_crm_tasks_contact_status_id": (
        ("contact_id", "status", "id"),
        None,
    ),
    "ix_crm_tasks_active_status_due_id": (
        ("status", "due_at", "id"),
        "archived_at IS NULL",
    ),
    "ix_crm_tasks_active_contact_status_id": (
        ("contact_id", "status", "id"),
        "archived_at IS NULL",
    ),
    "ix_crm_tasks_archived_at_id": (
        ("archived_at", "id"),
        "archived_at IS NOT NULL",
    ),
}
LIFECYCLE_INDEXES = {
    "crm_task_creation_requests": {
        "ix_crm_task_creation_requests_task_id": ("task_id",),
    },
    "crm_task_sources": {
        "ix_crm_task_sources_task_id": ("task_id",),
    },
    "crm_record_lifecycle_events": {
        "ix_crm_record_lifecycle_events_entity_created_at": (
            "entity_type",
            "entity_id",
            "created_at",
        ),
    },
}


def _load_revision():
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "81a4d2c6e9f0_add_crm_task_lifecycle.py"
    )
    assert path.is_file(), f"missing CRM task lifecycle revision: {path.name}"
    spec = importlib.util.spec_from_file_location(
        "crm_task_lifecycle_revision_81a4d2c6e9f0", path
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def _constraint_names(table: sa.Table, kind: type) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, kind) and constraint.name is not None
    }


def _named_unique_columns(table: sa.Table) -> dict[str, tuple[str, ...]]:
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
        and constraint.name is not None
    }


def _index_where(index: sa.Index) -> str | None:
    predicate = index.dialect_options["postgresql"].get("where")
    return None if predicate is None else str(predicate)


def _render_revision(function_name: str) -> str:
    revision = _load_revision()
    output = StringIO()
    revision.op = Operations(
        MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output},
        )
    )
    getattr(revision, function_name)()
    return output.getvalue()


def _normalized_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().upper()


def _sync_test_url() -> sa.engine.URL:
    raw_url = os.getenv("CRM_TASK_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("CRM_TASK_TEST_DATABASE_URL is not provisioned")
    url = make_url(raw_url)
    assert url.database and url.database.endswith("_test"), (
        "CRM task migration integration tests require a disposable PostgreSQL "
        "database whose name ends in _test"
    )
    assert url.drivername.startswith("postgresql"), (
        "CRM task migration integration tests require PostgreSQL"
    )
    query = {
        key: value
        for key, value in url.query.items()
        if key not in {"ssl", "sslmode"}
    }
    return url.set(drivername="postgresql+psycopg2", query=query)


def _create_7d1f3a5b6c8e_fixture(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    tasks = sa.Table(
        "crm_tasks",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column(
            "priority", sa.String(32), nullable=False, server_default="normal"
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    sa.Index(
        "ix_crm_tasks_contact_status_id",
        tasks.c.contact_id,
        tasks.c.status,
        tasks.c.id,
    )
    sa.Table(
        "crm_contact_source_occurrences",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("section_capture_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("occurrence_ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    sa.Table(
        "alembic_version",
        metadata,
        sa.Column("version_num", sa.String(32), primary_key=True),
    )
    metadata.create_all(connection)
    connection.execute(
        sa.text(
            "INSERT INTO alembic_version (version_num) VALUES (:version_num)"
        ),
        {"version_num": DOWN_REVISION},
    )
    connection.execute(
        sa.text(
            "INSERT INTO crm_tasks "
            "(id, contact_id, title, description, status, priority, created_at, "
            "updated_at) VALUES "
            "(1, 10, 'Legacy updated', '', 'archived', 'normal', "
            "'2026-01-01 12:00:00+00', '2026-02-02 13:30:00+00'), "
            "(2, NULL, 'Legacy created', '', 'archived', 'normal', "
            "'2026-03-03 14:00:00+00', NULL), "
            "(3, 10, 'Existing open', '', 'open', 'normal', "
            "'2026-04-04 15:00:00+00', '2026-04-05 16:00:00+00')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO crm_contact_source_occurrences "
            "(id, contact_id, section_capture_id, source_record_id, "
            "occurrence_ordinal, created_at, updated_at) VALUES "
            "(21, 10, 30, 40, 2, "
            "'2026-05-05 17:00:00+00', '2026-05-06 18:00:00+00')"
        )
    )


def _source_evidence_row(connection: sa.Connection) -> dict[str, object]:
    return dict(
        connection.execute(
            sa.text(
                "SELECT id, contact_id, section_capture_id, source_record_id, "
                "occurrence_ordinal, created_at, updated_at "
                "FROM crm_contact_source_occurrences WHERE id = 21"
            )
        ).mappings().one()
    )


def _indexes(inspector: sa.Inspector, table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes(table_name)
        if index["name"] and not index.get("duplicates_constraint")
    }


def test_task_lifecycle_columns_are_explicit() -> None:
    columns = CRMTask.__table__.columns
    assert columns["archived_at"].nullable is True
    assert columns["archived_at"].type.timezone is True
    assert columns["archived_by_type"].nullable is True
    assert columns["archived_by_type"].type.length == 32
    assert columns["archived_by_id"].nullable is True
    assert columns["archived_by_id"].type.length == 128
    assert columns["archive_reason"].nullable is True
    assert columns["archive_reason"].type.length == 500
    assert columns["version"].nullable is False
    assert columns["version"].default.arg == 1
    assert str(columns["version"].server_default.arg) == "1"
    assert CRMTask(title="Keep workflow", status="in_progress").status == (
        "in_progress"
    )


def test_creation_request_contract_is_bounded_and_idempotent() -> None:
    table = CRMTaskCreationRequest.__table__
    columns = table.columns
    assert _named_unique_columns(table) == {
        "uq_crm_task_creation_request_scope_key": (
            "scope",
            "idempotency_key",
        )
    }
    assert "ck_crm_task_creation_requests_state" in _constraint_names(
        table, sa.CheckConstraint
    )
    assert columns["scope"].type.length == 64
    assert columns["idempotency_key"].type.length == 128
    assert columns["payload_hash"].type.length == 64
    assert columns["actor_type"].type.length == 32
    assert columns["actor_id"].type.length == 128
    assert columns["source_type"].type.length == 64
    assert columns["source_id"].type.length == 255
    for required_column in (
        "scope",
        "idempotency_key",
        "payload_hash",
        "actor_type",
        "actor_id",
        "source_type",
        "source_id",
        "state",
        "metadata_json",
        "created_at",
        "updated_at",
    ):
        assert columns[required_column].nullable is False
    assert columns["state"].nullable is False
    assert columns["state"].default.arg == "applying"
    assert columns["failure_category"].nullable is True
    assert columns["metadata_json"].nullable is False
    assert columns["metadata_json"].default.arg == "{}"
    assert columns["task_id"].nullable is True
    assert columns["result_version"].nullable is True
    task_foreign_key = next(iter(columns["task_id"].foreign_keys))
    assert task_foreign_key.target_fullname == "crm_tasks.id"
    assert task_foreign_key.ondelete == "RESTRICT"


def test_task_source_identity_and_lifecycle_event_request_are_unique() -> None:
    source = CRMTaskSource.__table__
    event = CRMRecordLifecycleEvent.__table__
    assert _named_unique_columns(source) == {
        "uq_crm_task_source_identity": (
            "source_type",
            "source_id",
            "source_key",
        )
    }
    assert _named_unique_columns(event) == {
        "uq_crm_record_lifecycle_event_request": (
            "entity_type",
            "entity_id",
            "action",
            "request_id",
        )
    }
    assert source.columns["source_type"].type.length == 64
    assert source.columns["source_id"].type.length == 255
    assert source.columns["source_key"].type.length == 128
    assert all(column.nullable is False for column in source.columns)
    source_task_foreign_key = next(iter(source.columns["task_id"].foreign_keys))
    assert source_task_foreign_key.target_fullname == "crm_tasks.id"
    assert source_task_foreign_key.ondelete == "RESTRICT"
    assert source.columns["created_at"].type.timezone is True

    request_id = event.columns["request_id"]
    assert request_id.nullable is False
    assert isinstance(request_id.type, PostgreSQLUUID)
    assert request_id.type.as_uuid is True
    assert request_id.type.python_type is UUID
    assert event.columns["entity_type"].type.length == 64
    assert event.columns["action"].type.length == 64
    assert event.columns["request_hash"].type.length == 64
    assert event.columns["actor_type"].type.length == 32
    assert event.columns["actor_id"].type.length == 128
    assert event.columns["source_type"].type.length == 64
    assert event.columns["source_id"].type.length == 255
    assert all(column.nullable is False for column in event.columns)
    for json_column in ("metadata_json", "result_json"):
        assert isinstance(event.columns[json_column].type, sa.Text)
        assert event.columns[json_column].nullable is False
        assert event.columns[json_column].default.arg == "{}"
    assert event.columns["created_at"].type.timezone is True


def test_task_visibility_indexes_are_named_partial_and_supplement_legacy_index() -> None:
    indexes = {index.name: index for index in CRMTask.__table__.indexes}
    assert set(TASK_INDEXES).issubset(indexes)
    for index_name, (expected_columns, expected_where) in TASK_INDEXES.items():
        index = indexes[index_name]
        assert tuple(column.name for column in index.columns) == expected_columns
        assert _index_where(index) == expected_where

    ddl = {
        name: str(
            CreateIndex(indexes[name]).compile(dialect=postgresql.dialect())
        )
        for name in TASK_INDEXES
    }
    assert "WHERE archived_at IS NULL" in ddl[
        "ix_crm_tasks_active_status_due_id"
    ]
    assert "WHERE archived_at IS NULL" in ddl[
        "ix_crm_tasks_active_contact_status_id"
    ]
    assert "WHERE archived_at IS NOT NULL" in ddl[
        "ix_crm_tasks_archived_at_id"
    ]
    assert " WHERE " not in ddl["ix_crm_tasks_contact_status_id"]


def test_lifecycle_models_are_registered_for_application_and_alembic() -> None:
    assert NEW_TABLES.issubset(Base.metadata.tables)
    assert models.CRMTaskCreationRequest is CRMTaskCreationRequest
    assert models.CRMTaskSource is CRMTaskSource
    assert models.CRMRecordLifecycleEvent is CRMRecordLifecycleEvent
    assert {
        "CRMTaskCreationRequest",
        "CRMTaskSource",
        "CRMRecordLifecycleEvent",
    }.issubset(set(models.__all__))

    env_source = (
        Path(__file__).parents[1] / "alembic" / "env.py"
    ).read_text(encoding="utf-8")
    assert "import models.crm_task_lifecycle" in env_source


def test_revision_metadata_and_generated_postgresql_ddl_are_explicit() -> None:
    revision = _load_revision()
    assert revision.revision == REVISION
    assert revision.down_revision == DOWN_REVISION
    assert revision.branch_labels is None
    assert revision.depends_on is None
    backend_root = Path(__file__).parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [REVISION]

    sql = _normalized_sql(_render_revision("upgrade"))
    assert "ALTER TABLE CRM_TASKS ADD COLUMN ARCHIVED_AT TIMESTAMP WITH TIME ZONE" in sql
    assert "ALTER TABLE CRM_TASKS ADD COLUMN VERSION INTEGER DEFAULT 1 NOT NULL" in sql
    assert (
        "SET ARCHIVED_AT = COALESCE(UPDATED_AT, CREATED_AT), "
        "ARCHIVED_BY_TYPE = 'MIGRATION', ARCHIVED_BY_ID = '81A4D2C6E9F0', "
        "ARCHIVE_REASON = 'LEGACY_STATUS_MIGRATION', STATUS = 'OPEN' "
        "WHERE STATUS = 'ARCHIVED'"
    ) in sql
    assert "CREATE TABLE CRM_TASK_CREATION_REQUESTS" in sql
    assert "CREATE TABLE CRM_TASK_SOURCES" in sql
    assert "CREATE TABLE CRM_RECORD_LIFECYCLE_EVENTS" in sql
    assert "REQUEST_ID UUID NOT NULL" in sql
    assert "CONSTRAINT UQ_CRM_TASK_CREATION_REQUEST_SCOPE_KEY UNIQUE" in sql
    assert "CONSTRAINT UQ_CRM_TASK_SOURCE_IDENTITY UNIQUE" in sql
    assert "CONSTRAINT UQ_CRM_RECORD_LIFECYCLE_EVENT_REQUEST UNIQUE" in sql
    assert "CONSTRAINT CK_CRM_TASK_CREATION_REQUESTS_STATE CHECK" in sql
    assert "CONSTRAINT CK_CRM_TASKS_VERSION_POSITIVE CHECK" in sql
    for index_name in {
        *TASK_INDEXES,
        *(name for names in LIFECYCLE_INDEXES.values() for name in names),
    }:
        if index_name == "ix_crm_tasks_contact_status_id":
            continue
        assert f"CREATE INDEX {index_name.upper()}" in sql
    assert (
        "CREATE INDEX IX_CRM_TASKS_ACTIVE_STATUS_DUE_ID ON CRM_TASKS "
        "(STATUS, DUE_AT, ID) WHERE ARCHIVED_AT IS NULL"
    ) in sql
    assert (
        "CREATE INDEX IX_CRM_TASKS_ARCHIVED_AT_ID ON CRM_TASKS "
        "(ARCHIVED_AT, ID) WHERE ARCHIVED_AT IS NOT NULL"
    ) in sql
    assert "CRM_CONTACT_SOURCE_OCCURRENCES" in sql
    assert "SOURCE-ONLY RECOVERED EVIDENCE COUNT CHANGED" in sql
    assert "DROP INDEX IX_CRM_TASKS_CONTACT_STATUS_ID" not in sql


def test_generated_downgrade_restores_legacy_status_and_only_drops_new_indexes() -> None:
    revision = _load_revision()
    assert "cannot reconstruct" in (revision.downgrade.__doc__ or "").lower()

    sql = _normalized_sql(_render_revision("downgrade"))
    update_position = sql.index(
        "UPDATE CRM_TASKS SET STATUS = 'ARCHIVED' WHERE ARCHIVED_AT IS NOT NULL"
    )
    first_drop_position = sql.index("DROP INDEX")
    assert update_position < first_drop_position
    for index_name in {
        "ix_crm_task_creation_requests_task_id",
        "ix_crm_task_sources_task_id",
        "ix_crm_record_lifecycle_events_entity_created_at",
        "ix_crm_tasks_active_status_due_id",
        "ix_crm_tasks_active_contact_status_id",
        "ix_crm_tasks_archived_at_id",
    }:
        assert f"DROP INDEX {index_name.upper()}" in sql
    assert "DROP INDEX IX_CRM_TASKS_CONTACT_STATUS_ID" not in sql
    assert sql.index("DROP TABLE CRM_RECORD_LIFECYCLE_EVENTS") < sql.index(
        "DROP TABLE CRM_TASK_SOURCES"
    )
    assert sql.index("DROP TABLE CRM_TASK_SOURCES") < sql.index(
        "DROP TABLE CRM_TASK_CREATION_REQUESTS"
    )


def test_upgrade_downgrade_upgrade_reconciles_legacy_rows_on_isolated_postgresql() -> None:
    engine = sa.create_engine(_sync_test_url())
    try:
        with engine.connect() as connection:
            database_name = connection.scalar(sa.text("SELECT current_database()"))
            assert isinstance(database_name, str) and database_name.endswith("_test")
            assert sa.inspect(connection).get_table_names() == []

            _create_7d1f3a5b6c8e_fixture(connection)
            connection.commit()
            source_before = _source_evidence_row(connection)
            revision = _load_revision()
            revision.op = Operations(MigrationContext.configure(connection))
            revision.upgrade()
            connection.commit()

            inspector = sa.inspect(connection)
            assert NEW_TABLES.issubset(inspector.get_table_names())
            assert _indexes(inspector, "crm_tasks") == {
                name: columns for name, (columns, _where) in TASK_INDEXES.items()
            }
            for table_name, expected_indexes in LIFECYCLE_INDEXES.items():
                assert _indexes(inspector, table_name) == expected_indexes
            assert {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "crm_task_creation_requests"
                )
            } == {"uq_crm_task_creation_request_scope_key"}
            assert {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("crm_task_sources")
            } == {"uq_crm_task_source_identity"}
            assert {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "crm_record_lifecycle_events"
                )
            } == {"uq_crm_record_lifecycle_event_request"}
            request_id = next(
                column
                for column in inspector.get_columns("crm_record_lifecycle_events")
                if column["name"] == "request_id"
            )
            assert isinstance(request_id["type"], PostgreSQLUUID)
            assert request_id["nullable"] is False

            rows = connection.execute(
                sa.text(
                    "SELECT id, status, archived_at, archived_by_type, "
                    "archived_by_id, archive_reason, version FROM crm_tasks "
                    "ORDER BY id"
                )
            ).mappings().all()
            assert [row["status"] for row in rows] == ["open", "open", "open"]
            assert rows[0]["archived_at"] == datetime(
                2026, 2, 2, 13, 30, tzinfo=timezone.utc
            )
            assert rows[1]["archived_at"] == datetime(
                2026, 3, 3, 14, 0, tzinfo=timezone.utc
            )
            assert rows[2]["archived_at"] is None
            assert {
                (
                    row["archived_by_type"],
                    row["archived_by_id"],
                    row["archive_reason"],
                    row["version"],
                )
                for row in rows[:2]
            } == {
                (
                    "migration",
                    REVISION,
                    "legacy_status_migration",
                    1,
                )
            }
            assert rows[2]["version"] == 1
            assert _source_evidence_row(connection) == source_before

            revision.downgrade()
            connection.commit()
            assert NEW_TABLES.isdisjoint(sa.inspect(connection).get_table_names())
            assert _indexes(sa.inspect(connection), "crm_tasks") == {
                "ix_crm_tasks_contact_status_id": ("contact_id", "status", "id")
            }
            downgraded = connection.execute(
                sa.text("SELECT id, status FROM crm_tasks ORDER BY id")
            ).all()
            assert downgraded == [(1, "archived"), (2, "archived"), (3, "open")]
            assert _source_evidence_row(connection) == source_before

            revision.upgrade()
            connection.commit()
            assert connection.scalar(
                sa.text(
                    "SELECT count(*) FROM crm_tasks WHERE status = 'open' "
                    "AND version = 1"
                )
            ) == 3
            assert _source_evidence_row(connection) == source_before
    finally:
        engine.dispose()
