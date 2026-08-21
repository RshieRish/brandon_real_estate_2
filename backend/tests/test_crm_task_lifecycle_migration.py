from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from uuid import UUID, uuid4

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
OWNERSHIP_MARKER_TABLE = "_crm_task_lifecycle_test_ownership"


def _fail_closed(message: str) -> None:
    if os.getenv("CI", "").strip().lower() == "true":
        pytest.fail(message)
    raise RuntimeError(message)


def _repository_script_directory() -> ScriptDirectory:
    backend_root = Path(__file__).parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return ScriptDirectory.from_config(config)


def _repository_head() -> str:
    script_directory = _repository_script_directory()
    heads = script_directory.get_heads()
    assert len(heads) == 1, (
        "the repository must have exactly one Alembic head; found "
        f"{heads}"
    )
    head = script_directory.get_current_head()
    assert head is not None
    return head


def _public_schema_user_objects(connection: sa.Connection) -> list[str]:
    return list(
        connection.scalars(
            sa.text(
                """
                SELECT object_name
                FROM (
                    SELECT 'relation:' || c.relname AS object_name
                    FROM pg_catalog.pg_class AS c
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f', 'c', 'i', 'I')
                    UNION ALL
                    SELECT 'routine:' || p.proname
                    FROM pg_catalog.pg_proc AS p
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'type:' || t.typname
                    FROM pg_catalog.pg_type AS t
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = t.typnamespace
                    WHERE n.nspname = 'public' AND t.typrelid = 0
                    UNION ALL
                    SELECT 'extension:' || e.extname
                    FROM pg_catalog.pg_extension AS e
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = e.extnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'collation:' || c.collname
                    FROM pg_catalog.pg_collation AS c
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = c.collnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'conversion:' || c.conname
                    FROM pg_catalog.pg_conversion AS c
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = c.connamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'operator:' || o.oprname
                    FROM pg_catalog.pg_operator AS o
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = o.oprnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'operator_class:' || o.opcname
                    FROM pg_catalog.pg_opclass AS o
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = o.opcnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'operator_family:' || o.opfname
                    FROM pg_catalog.pg_opfamily AS o
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = o.opfnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'text_search_config:' || c.cfgname
                    FROM pg_catalog.pg_ts_config AS c
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = c.cfgnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'text_search_dictionary:' || d.dictname
                    FROM pg_catalog.pg_ts_dict AS d
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = d.dictnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'text_search_parser:' || p.prsname
                    FROM pg_catalog.pg_ts_parser AS p
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = p.prsnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'text_search_template:' || t.tmplname
                    FROM pg_catalog.pg_ts_template AS t
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = t.tmplnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 'extended_statistic:' || s.stxname
                    FROM pg_catalog.pg_statistic_ext AS s
                    JOIN pg_catalog.pg_namespace AS n
                      ON n.oid = s.stxnamespace
                    WHERE n.nspname = 'public'
                ) AS public_objects
                ORDER BY object_name
                """
            )
        )
    )


def _cleanup_owned_test_schema(
    connection: sa.Connection,
    *,
    expected_database: str,
    ownership_marker: str,
) -> None:
    actual_database = connection.scalar(sa.text("SELECT current_database()"))
    if actual_database != expected_database:
        _fail_closed(
            "refusing cleanup outside the exact configured test database"
        )
    marker_table_oid = connection.scalar(
        sa.text("SELECT to_regclass(:table_name)::oid"),
        {"table_name": f"public.{OWNERSHIP_MARKER_TABLE}"},
    )
    if marker_table_oid is None:
        _fail_closed(
            "refusing cleanup without the test ownership marker table"
        )
    marker_counts = connection.execute(
        sa.text(
            f"SELECT count(*), count(*) FILTER (WHERE marker = :marker) "
            f"FROM public.{OWNERSHIP_MARKER_TABLE}"
        ),
        {"marker": ownership_marker},
    ).one()
    if tuple(marker_counts) != (1, 1):
        _fail_closed(
            "refusing cleanup without the exact test ownership marker"
        )
    connection.exec_driver_sql("DROP SCHEMA public CASCADE")
    connection.exec_driver_sql("CREATE SCHEMA public")


@contextmanager
def _owned_empty_test_schema(
    engine: sa.Engine,
    expected_database: str,
) -> Iterator[str]:
    ownership_marker = uuid4().hex
    cleanup_armed = False
    try:
        with engine.begin() as connection:
            actual_database = connection.scalar(
                sa.text("SELECT current_database()")
            )
            if actual_database != expected_database:
                _fail_closed(
                    "refusing setup outside the exact configured test database"
                )
            existing_objects = _public_schema_user_objects(connection)
            if existing_objects:
                _fail_closed(
                    "public schema is not empty: "
                    + ", ".join(existing_objects)
                )
            connection.exec_driver_sql(
                f"CREATE TABLE public.{OWNERSHIP_MARKER_TABLE} "
                "(marker text PRIMARY KEY)"
            )
            connection.execute(
                sa.text(
                    f"INSERT INTO public.{OWNERSHIP_MARKER_TABLE} (marker) "
                    "VALUES (:marker)"
                ),
                {"marker": ownership_marker},
            )
        cleanup_armed = True
        yield ownership_marker
    finally:
        if cleanup_armed:
            with engine.begin() as connection:
                _cleanup_owned_test_schema(
                    connection,
                    expected_database=expected_database,
                    ownership_marker=ownership_marker,
                )


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


def _isolated_test_url() -> sa.engine.URL:
    raw_url = os.getenv("CRM_TASK_TEST_DATABASE_URL")
    expected_database = os.getenv("CRM_TASK_TEST_DATABASE_NAME")
    if not raw_url or not expected_database:
        if os.getenv("CI", "").strip().lower() == "true":
            pytest.fail(
                "CI requires CRM_TASK_TEST_DATABASE_NAME and "
                "CRM_TASK_TEST_DATABASE_URL"
            )
        pytest.skip("CRM_TASK_TEST_DATABASE_URL is not provisioned")
    url = make_url(raw_url)
    if not expected_database.endswith("_test"):
        _fail_closed(
            "CRM_TASK_TEST_DATABASE_NAME must identify the disposable _test "
            "database"
        )
    if url.database != expected_database:
        _fail_closed(
            "CRM_TASK_TEST_DATABASE_URL must target exactly "
            "CRM_TASK_TEST_DATABASE_NAME"
        )
    if not (url.database or "").endswith("_test"):
        _fail_closed(
            "CRM task migration integration tests require a disposable "
            "PostgreSQL database whose name ends in _test"
        )
    if not url.drivername.startswith("postgresql"):
        _fail_closed(
            "CRM task migration integration tests require PostgreSQL"
        )
    return url


def _sync_test_url(url: sa.engine.URL) -> sa.engine.URL:
    query = dict(url.query)
    async_ssl_mode = query.pop("ssl", None)
    if async_ssl_mode is not None:
        query.setdefault("sslmode", async_ssl_mode)
    return url.set(drivername="postgresql+psycopg2", query=query)


def _invoke_alembic(
    url: sa.engine.URL, *arguments: str
) -> subprocess.CompletedProcess[str]:
    backend_root = Path(__file__).parents[1]
    alembic_executable = Path(sys.executable).with_name("alembic")
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url.render_as_string(hide_password=False)
    environment.setdefault("JWT_SECRET", "test-secret")
    return subprocess.run(
        [str(alembic_executable), *arguments],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _run_alembic(url: sa.engine.URL, *arguments: str) -> str:
    completed = _invoke_alembic(url, *arguments)
    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode == 0, (
        f"alembic {' '.join(arguments)} failed with exit code "
        f"{completed.returncode}:\n{output}"
    )
    return output


def _seed_real_7d1f3a5b6c8e_schema(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO crm_contacts (id, first_name, last_name) "
            "VALUES (10, 'Recovered', 'Evidence')"
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO crm_source_records
                (id, source_system, module, record_kind, source_key,
                 evidence_level, display_label, payload_json, capture_quality,
                 captured_at, parser_version)
            VALUES
                (40, 'kw_command', 'contacts', 'contact_capture_position',
                 'lifecycle-test:capture', 'rendered_occurrence', 'Capture',
                 '{}', 'complete', '2026-05-05 17:00:00+00', 'test-v1'),
                (41, 'kw_command', 'contacts', 'contact_section_capture',
                 'lifecycle-test:section', 'rendered_occurrence', 'Section',
                 '{}', 'complete', '2026-05-05 17:00:00+00', 'test-v1'),
                (42, 'kw_command', 'contacts', 'contact_task',
                 'lifecycle-test:occurrence', 'rendered_occurrence',
                 'Recovered archived task', '{}', 'complete',
                 '2026-05-05 17:00:00+00', 'test-v1')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO crm_contact_capture_positions
                (id, contact_id, source_record_id, bundle_fingerprint,
                 capture_ordinal, source_contact_id, captured_at,
                 capture_quality, limitations_json)
            VALUES
                (30, 10, 40,
                 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                 1, '0123456789abcdef01234567',
                 '2026-05-05 17:00:00+00', 'complete', '[]')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO crm_contact_section_captures
                (id, capture_position_id, source_record_id, section_name,
                 captured_at, capture_quality, is_empty, row_count,
                 limitations_json)
            VALUES
                (31, 30, 41, 'tasks_archived',
                 '2026-05-05 17:00:00+00', 'complete', false, 1, '[]')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO crm_contact_source_occurrences
                (id, contact_id, section_capture_id, source_record_id,
                 occurrence_ordinal, created_at, updated_at)
            VALUES
                (21, 10, 31, 42, 1,
                 '2026-05-05 17:00:00+00', '2026-05-06 18:00:00+00')
            """
        )
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
            "'2026-04-04 15:00:00+00', '2026-04-05 16:00:00+00'), "
            "(4, NULL, 'Legacy no timestamp', '', 'archived', 'normal', "
            "NULL, NULL)"
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


def _seed_durable_lifecycle_history(
    connection: sa.Connection, table_name: str
) -> None:
    if table_name == "crm_task_creation_requests":
        connection.execute(
            sa.text(
                """
                INSERT INTO crm_task_creation_requests
                    (scope, idempotency_key, payload_hash, actor_type, actor_id,
                     source_type, source_id, task_id, result_version)
                VALUES
                    ('migration-test', 'durable-history', :payload_hash,
                     'test', 'quality-review', 'pytest', 'real-alembic-chain',
                     1, 1)
                """
            ),
            {"payload_hash": "a" * 64},
        )
        return
    if table_name == "crm_task_sources":
        connection.execute(
            sa.text(
                """
                INSERT INTO crm_task_sources
                    (task_id, source_type, source_id, source_key)
                VALUES
                    (1, 'pytest', 'real-alembic-chain', 'durable-history')
                """
            )
        )
        return
    if table_name == "crm_record_lifecycle_events":
        connection.execute(
            sa.text(
                """
                INSERT INTO crm_record_lifecycle_events
                    (entity_type, entity_id, action, request_id, request_hash,
                     actor_type, actor_id, source_type, source_id)
                VALUES
                    ('crm_task', 1, 'archive', :request_id, :request_hash,
                     'test', 'quality-review', 'pytest', 'real-alembic-chain')
                """
            ),
            {
                "request_id": UUID(
                    "11111111-1111-4111-8111-111111111111"
                ),
                "request_hash": "b" * 64,
            },
        )
        return
    raise AssertionError(f"unsupported durable history table: {table_name}")


def _durable_history_counts(connection: sa.Connection) -> tuple[int, int, int]:
    return tuple(
        connection.execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM crm_task_creation_requests),
                    (SELECT count(*) FROM crm_task_sources),
                    (SELECT count(*) FROM crm_record_lifecycle_events)
                """
            )
        ).one()
    )


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
    assert str(columns["state"].server_default.arg).strip("'") == "applying"
    assert columns["failure_category"].nullable is True
    assert columns["metadata_json"].nullable is False
    assert columns["metadata_json"].default.arg == "{}"
    assert str(columns["metadata_json"].server_default.arg).strip("'") == "{}"
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
        assert (
            str(event.columns[json_column].server_default.arg).strip("'")
            == "{}"
        )
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


def test_ci_requires_the_isolated_postgresql_contract(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("CRM_TASK_TEST_DATABASE_NAME", raising=False)
    monkeypatch.delenv("CRM_TASK_TEST_DATABASE_URL", raising=False)

    with pytest.raises(BaseException) as captured:
        _isolated_test_url()

    assert isinstance(captured.value, pytest.fail.Exception)
    assert "CI requires CRM_TASK_TEST_DATABASE" in str(captured.value)


def test_repository_ci_runs_the_real_tls_postgresql_migration_contract() -> None:
    workflow_path = (
        Path(__file__).parents[2]
        / ".github"
        / "workflows"
        / "crm-task-lifecycle-migration.yml"
    )
    assert workflow_path.is_file()
    workflow = workflow_path.read_text(encoding="utf-8")
    for required_fragment in (
        "postgres:16-alpine",
        "CRM_TASK_TEST_DATABASE_NAME:",
        "CRM_TASK_TEST_DATABASE_URL:",
        "SSL_CERT_FILE:",
        "ALTER SYSTEM SET ssl = 'on'",
        "hostnossl all all 0.0.0.0/0 reject",
        "pg_stat_ssl",
        'sslmode="verify-full"',
        "tests/test_crm_task_lifecycle_migration.py",
        "backend/services/crm_task_service.py",
        "backend/tests/test_crm_task_service.py",
        "backend/tests/test_command_task_api.py",
        "tests/test_crm_task_service.py",
        "tests/test_command_task_api.py",
        '"pytest==9.0.3"',
        '"pytest-asyncio==1.3.0"',
        '"backend/database.py"',
        '"backend/middleware/auth.py"',
        '"backend/config.py"',
        "if: always()",
        "docker rm --force crm-task-lifecycle-postgres",
    ):
        assert required_fragment in workflow


def test_approved_plan_uses_a_disposable_database_name_accepted_by_test_gate() -> None:
    plan_path = (
        Path(__file__).parents[2]
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-08-18-crm-task-archive-foundation.md"
    )
    plan = plan_path.read_text(encoding="utf-8")
    database_name = "brandon_crm_task_archive_<unique-suffix>_test"
    assert f"CRM_TASK_TEST_DATABASE_NAME='{database_name}'" in plan
    assert f"/{database_name}?ssl=require" in plan

    sync_url_exports = [
        line
        for line in plan.splitlines()
        if line.startswith("export CRM_TASK_TEST_SYNC_URL=")
    ]
    assert sync_url_exports
    for async_url in (
        "postgresql+asyncpg://fixture:fixture@db.example.test/"
        "brandon_crm_task_archive_demo_test?ssl=require",
        "postgresql+asyncpg://fixture:fixture@db.example.test/"
        "brandon_crm_task_archive_demo_test?application_name=crm&ssl=require",
    ):
        completed = subprocess.run(
            [
                "bash",
                "-euc",
                "\n".join(
                    [
                        *sync_url_exports,
                        'printf "%s" "$CRM_TASK_TEST_SYNC_URL"',
                    ]
                ),
            ],
            env={**os.environ, "CRM_TASK_TEST_DATABASE_URL": async_url},
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout == async_url.replace(
            "postgresql+asyncpg:", "postgresql:", 1
        ).replace("ssl=require", "sslmode=require", 1)
        assert "?ssl=require" not in completed.stdout
        assert "&ssl=require" not in completed.stdout


def test_populated_test_database_is_not_claimed_or_destroyed() -> None:
    url = _isolated_test_url()
    expected_database = os.environ["CRM_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(_sync_test_url(url))
    sentinel = f"_crm_task_lifecycle_evidence_{uuid4().hex[:12]}"
    sentinel_created = False
    try:
        with engine.begin() as connection:
            assert connection.scalar(
                sa.text("SELECT current_database()")
            ) == expected_database
            assert sa.inspect(connection).get_table_names() == []
            connection.exec_driver_sql(
                f"CREATE MATERIALIZED VIEW {sentinel} AS "
                "SELECT 'preserve-me'::text AS value"
            )
            sentinel_created = True

        with pytest.raises(BaseException, match="public schema is not empty"):
            with _owned_empty_test_schema(engine, expected_database):
                pytest.fail("a populated test database must not be claimed")

        with engine.connect() as connection:
            assert connection.scalar(
                sa.text(f"SELECT value FROM {sentinel}")
            ) == "preserve-me"
            assert connection.scalar(
                sa.text("SELECT to_regclass(:marker_table)"),
                {"marker_table": f"public.{OWNERSHIP_MARKER_TABLE}"},
            ) is None
    finally:
        if sentinel_created:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    f"DROP MATERIALIZED VIEW {sentinel}"
                )
        engine.dispose()


def test_revision_metadata_and_generated_postgresql_ddl_are_explicit() -> None:
    revision = _load_revision()
    assert revision.revision == REVISION
    assert revision.down_revision == DOWN_REVISION
    assert revision.branch_labels is None
    assert revision.depends_on is None
    script_directory = _repository_script_directory()
    repository_head = _repository_head()
    ancestor_revisions = {
        candidate.revision
        for candidate in script_directory.walk_revisions(
            base="base",
            head=repository_head,
        )
    }
    assert REVISION in ancestor_revisions

    sql = _normalized_sql(_render_revision("upgrade"))
    lock_timeout_position = sql.index("SET LOCAL LOCK_TIMEOUT = '2S'")
    statement_timeout_position = sql.index(
        "SET LOCAL STATEMENT_TIMEOUT = '30S'"
    )
    lock_position = sql.index(
        "LOCK TABLE CRM_TASKS, CRM_CONTACT_SOURCE_OCCURRENCES "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    count_capture_position = sql.index(
        "CREATE TEMPORARY TABLE _CRM_TASK_LIFECYCLE_COUNTS_81A4D2C6E9F0"
    )
    first_ddl_position = sql.index("ALTER TABLE CRM_TASKS ADD COLUMN")
    assert (
        lock_timeout_position
        < statement_timeout_position
        < lock_position
        < count_capture_position
        < first_ddl_position
    )
    assert "ALTER TABLE CRM_TASKS ADD COLUMN ARCHIVED_AT TIMESTAMP WITH TIME ZONE" in sql
    assert "ALTER TABLE CRM_TASKS ADD COLUMN VERSION INTEGER DEFAULT 1 NOT NULL" in sql
    assert (
        "SET ARCHIVED_AT = COALESCE(UPDATED_AT, CREATED_AT, CURRENT_TIMESTAMP), "
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


def test_repository_has_one_serial_alembic_head_with_revision_81_as_ancestor() -> None:
    script_directory = _repository_script_directory()
    repository_head = _repository_head()
    ancestor_revisions = {
        candidate.revision
        for candidate in script_directory.walk_revisions(
            base="base",
            head=repository_head,
        )
    }
    assert REVISION in ancestor_revisions


def test_generated_downgrade_restores_legacy_status_and_only_drops_new_indexes() -> None:
    revision = _load_revision()
    assert "cannot reconstruct" in (revision.downgrade.__doc__ or "").lower()

    sql = _normalized_sql(_render_revision("downgrade"))
    assert sql.index("SET LOCAL LOCK_TIMEOUT = '2S'") < sql.index("DO $$")
    assert sql.index("SET LOCAL STATEMENT_TIMEOUT = '30S'") < sql.index(
        "DO $$"
    )
    preflight_position = sql.index(
        "REFUSING CRM TASK LIFECYCLE DOWNGRADE: DURABLE HISTORY EXISTS"
    )
    downgrade_lock_position = sql.index(
        "LOCK TABLE CRM_TASKS, CRM_TASK_CREATION_REQUESTS, CRM_TASK_SOURCES, "
        "CRM_RECORD_LIFECYCLE_EVENTS IN SHARE ROW EXCLUSIVE MODE"
    )
    update_position = sql.index(
        "UPDATE CRM_TASKS SET STATUS = 'ARCHIVED' WHERE ARCHIVED_AT IS NOT NULL"
    )
    first_drop_position = sql.index("DROP INDEX")
    assert downgrade_lock_position < preflight_position
    assert preflight_position < update_position < first_drop_position
    for existence_check in (
        "EXISTS (SELECT 1 FROM CRM_TASK_CREATION_REQUESTS)",
        "EXISTS (SELECT 1 FROM CRM_TASK_SOURCES)",
        "EXISTS (SELECT 1 FROM CRM_RECORD_LIFECYCLE_EVENTS)",
    ):
        assert existence_check in sql[:update_position]
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
    url = _isolated_test_url()
    expected_database = os.environ["CRM_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(_sync_test_url(url))
    try:
        with _owned_empty_test_schema(engine, expected_database):
            _run_alembic(url, "upgrade", DOWN_REVISION)
            with engine.begin() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == DOWN_REVISION
                _seed_real_7d1f3a5b6c8e_schema(connection)
                source_before = _source_evidence_row(connection)
                fallback_lower_bound = connection.scalar(
                    sa.text("SELECT clock_timestamp()")
                )

            # A normal writer transaction on either preserved source must make
            # the bounded migration fail before any schema or data mutation.
            for write_sql in (
                "UPDATE crm_tasks SET title = title WHERE id = 1",
                "UPDATE crm_contact_source_occurrences "
                "SET occurrence_ordinal = occurrence_ordinal WHERE id = 21",
            ):
                with engine.begin() as blocker:
                    blocker.exec_driver_sql(write_sql)
                    failed_upgrade = _invoke_alembic(
                        url, "upgrade", REVISION
                    )
                    failed_output = (
                        f"{failed_upgrade.stdout}\n{failed_upgrade.stderr}"
                    ).lower()
                    assert failed_upgrade.returncode != 0
                    assert "lock timeout" in failed_output

                with engine.connect() as connection:
                    assert connection.scalar(
                        sa.text("SELECT version_num FROM alembic_version")
                    ) == DOWN_REVISION
                    inspector = sa.inspect(connection)
                    assert NEW_TABLES.isdisjoint(inspector.get_table_names())
                    assert "archived_at" not in {
                        column["name"]
                        for column in inspector.get_columns("crm_tasks")
                    }
                    assert connection.scalar(
                        sa.text("SELECT count(*) FROM crm_tasks")
                    ) == 4
                    assert _source_evidence_row(connection) == source_before

            _run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == REVISION

                inspector = sa.inspect(connection)
                assert NEW_TABLES.issubset(inspector.get_table_names())
                assert _indexes(inspector, "crm_tasks") == {
                    name: columns
                    for name, (columns, _where) in TASK_INDEXES.items()
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
                    for constraint in inspector.get_unique_constraints(
                        "crm_task_sources"
                    )
                } == {"uq_crm_task_source_identity"}
                assert {
                    constraint["name"]
                    for constraint in inspector.get_unique_constraints(
                        "crm_record_lifecycle_events"
                    )
                } == {"uq_crm_record_lifecycle_event_request"}
                request_id = next(
                    column
                    for column in inspector.get_columns(
                        "crm_record_lifecycle_events"
                    )
                    if column["name"] == "request_id"
                )
                assert isinstance(request_id["type"], PostgreSQLUUID)
                assert request_id["nullable"] is False

                rows = connection.execute(
                    sa.text(
                        "SELECT id, status, archived_at, archived_by_type, "
                        "archived_by_id, archive_reason, version "
                        "FROM crm_tasks ORDER BY id"
                    )
                ).mappings().all()
                fallback_upper_bound = connection.scalar(
                    sa.text("SELECT clock_timestamp()")
                )
                assert [row["status"] for row in rows] == ["open"] * 4
                assert rows[0]["archived_at"] == datetime(
                    2026, 2, 2, 13, 30, tzinfo=timezone.utc
                )
                assert rows[1]["archived_at"] == datetime(
                    2026, 3, 3, 14, 0, tzinfo=timezone.utc
                )
                assert rows[2]["archived_at"] is None
                assert (
                    fallback_lower_bound
                    <= rows[3]["archived_at"]
                    <= fallback_upper_bound
                )
                assert {
                    (
                        row["archived_by_type"],
                        row["archived_by_id"],
                        row["archive_reason"],
                        row["version"],
                    )
                    for row in (rows[0], rows[1], rows[3])
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

            current_output = _run_alembic(url, "current")
            assert REVISION in current_output
            heads_output = _run_alembic(url, "heads")
            repository_head = _repository_head()
            assert heads_output.count(f"{repository_head} (head)") == 1

            history_cases = (
                ("crm_task_creation_requests", (1, 0, 0)),
                ("crm_task_sources", (0, 1, 0)),
                ("crm_record_lifecycle_events", (0, 0, 1)),
            )
            delete_history = {
                "crm_task_creation_requests": (
                    "DELETE FROM crm_task_creation_requests"
                ),
                "crm_task_sources": "DELETE FROM crm_task_sources",
                "crm_record_lifecycle_events": (
                    "DELETE FROM crm_record_lifecycle_events"
                ),
            }
            for history_table, expected_counts in history_cases:
                with engine.begin() as connection:
                    _seed_durable_lifecycle_history(
                        connection, history_table
                    )
                    assert (
                        _durable_history_counts(connection)
                        == expected_counts
                    )
                    if history_table == "crm_task_creation_requests":
                        assert connection.execute(
                            sa.text(
                                "SELECT state, metadata_json "
                                "FROM crm_task_creation_requests"
                            )
                        ).one() == ("applying", "{}")
                    if history_table == "crm_record_lifecycle_events":
                        assert connection.execute(
                            sa.text(
                                "SELECT result_json, metadata_json "
                                "FROM crm_record_lifecycle_events"
                            )
                        ).one() == ("{}", "{}")

                refused_downgrade = _invoke_alembic(
                    url, "downgrade", DOWN_REVISION
                )
                refused_output = (
                    f"{refused_downgrade.stdout}\n"
                    f"{refused_downgrade.stderr}"
                ).lower()
                assert refused_downgrade.returncode != 0
                assert (
                    "refusing crm task lifecycle downgrade: durable history "
                    "exists" in refused_output
                )
                with engine.connect() as connection:
                    assert connection.scalar(
                        sa.text("SELECT version_num FROM alembic_version")
                    ) == REVISION
                    assert (
                        _durable_history_counts(connection)
                        == expected_counts
                    )
                    assert connection.execute(
                        sa.text(
                            "SELECT id, status FROM crm_tasks ORDER BY id"
                        )
                    ).all() == [
                        (1, "open"),
                        (2, "open"),
                        (3, "open"),
                        (4, "open"),
                    ]
                    assert _source_evidence_row(connection) == source_before
                assert REVISION in _run_alembic(url, "current")

                # This explicit clear models the separately approved operator
                # recovery required before a deliberately lossy downgrade.
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        delete_history[history_table]
                    )
                    assert _durable_history_counts(connection) == (0, 0, 0)

            _run_alembic(url, "downgrade", DOWN_REVISION)
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == DOWN_REVISION
                inspector = sa.inspect(connection)
                assert NEW_TABLES.isdisjoint(inspector.get_table_names())
                assert _indexes(inspector, "crm_tasks") == {
                    "ix_crm_tasks_contact_status_id": (
                        "contact_id",
                        "status",
                        "id",
                    )
                }
                assert "version" not in {
                    column["name"]
                    for column in inspector.get_columns("crm_tasks")
                }
                downgraded = connection.execute(
                    sa.text("SELECT id, status FROM crm_tasks ORDER BY id")
                ).all()
                assert downgraded == [
                    (1, "archived"),
                    (2, "archived"),
                    (3, "open"),
                    (4, "archived"),
                ]
                assert _source_evidence_row(connection) == source_before

            _run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == REVISION
                assert connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM crm_tasks "
                        "WHERE status = 'open' AND version = 1"
                    )
                ) == 4
                assert _source_evidence_row(connection) == source_before
    finally:
        engine.dispose()
