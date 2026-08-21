from __future__ import annotations

import importlib
import importlib.util
import os
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import sqlalchemy as sa
import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from tests.gmail_task_postgres import (
    gmail_task_test_url,
    owned_empty_test_schema,
    run_alembic,
    run_owned_alembic_downgrade,
    sync_test_url,
)


REVISION = "82b5e3d7f0a1"
DOWN_REVISION = "81a4d2c6e9f0"
HEALTH_TABLE = "integration_health_states"
HEARTBEAT_TABLE = "integration_worker_heartbeats"


def _backend_root() -> Path:
    return Path(__file__).parents[1]


def _revision_path() -> Path:
    return (
        _backend_root()
        / "alembic"
        / "versions"
        / "82b5e3d7f0a1_add_integration_runtime_health.py"
    )


def _load_revision():
    revision_path = _revision_path()
    assert revision_path.is_file(), f"missing migration: {revision_path.name}"
    spec = importlib.util.spec_from_file_location(
        "integration_runtime_revision_82b5e3d7f0a1",
        revision_path,
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def _script_directory() -> ScriptDirectory:
    config = Config(str(_backend_root() / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(_backend_root() / "alembic"),
    )
    return ScriptDirectory.from_config(config)


def _render(function_name: str) -> str:
    revision = _load_revision()
    output = StringIO()
    revision.op = Operations(
        MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output},
        )
    )
    getattr(revision, function_name)()
    return " ".join(output.getvalue().upper().split())


def test_revision_82_directly_follows_81_and_remains_in_the_serial_history() -> None:
    revision = _load_revision()
    assert revision.revision == REVISION
    assert revision.down_revision == DOWN_REVISION
    assert revision.branch_labels is None
    assert revision.depends_on is None
    script_directory = _script_directory()
    heads = script_directory.get_heads()
    assert len(heads) == 1
    ancestor_revisions = {
        candidate.revision
        for candidate in script_directory.walk_revisions(
            base="base",
            head=heads[0],
        )
    }
    assert REVISION in ancestor_revisions
    assert script_directory.get_revision(REVISION).down_revision == DOWN_REVISION


def test_revision_82_generated_ddl_has_exact_runtime_inventory() -> None:
    upgrade_sql = _render("upgrade")
    assert f"CREATE TABLE {HEALTH_TABLE.upper()}" in upgrade_sql
    assert f"CREATE TABLE {HEARTBEAT_TABLE.upper()}" in upgrade_sql
    for column in (
        "PROVIDER",
        "STATE",
        "LAST_CHECKED_AT",
        "LAST_SUCCEEDED_AT",
        "LAST_ERROR_CATEGORY",
        "LAST_ERROR_MESSAGE",
        "CONSECUTIVE_FAILURES",
        "TRANSITION_EPOCH",
        "LAST_ALERTED_AT",
        "NEXT_REMINDER_AT",
        "RECOVERED_AT",
    ):
        assert column in upgrade_sql
    for column in (
        "WORKER_ID",
        "BOOTED_AT",
        "HEARTBEAT_AT",
        "CURRENT_JOB",
        "LAST_COMPLETED_JOB",
    ):
        assert column in upgrade_sql
    for column in (
        "PROVIDER_KEY",
        "DEDUPE_KEY",
        "LEASE_OWNER",
        "LEASE_EXPIRES_AT",
    ):
        assert f"ADD COLUMN {column}" in upgrade_sql
    assert "UQ_NOTIFICATION_JOBS_PROVIDER_DEDUPE" in upgrade_sql
    assert "PROVIDER_KEY IS NOT NULL AND DEDUPE_KEY IS NOT NULL" in upgrade_sql
    assert "IX_NOTIFICATION_JOBS_CLAIMABLE" in upgrade_sql

    downgrade_sql = _render("downgrade")
    assert downgrade_sql.index(
        f"DROP TABLE {HEARTBEAT_TABLE.upper()}"
    ) < downgrade_sql.index(f"DROP TABLE {HEALTH_TABLE.upper()}")
    dedupe_drop = downgrade_sql.index(
        "DROP INDEX UQ_NOTIFICATION_JOBS_PROVIDER_DEDUPE"
    )
    first_claim_column_drop = downgrade_sql.index(
        "DROP COLUMN LEASE_EXPIRES_AT"
    )
    assert dedupe_drop < first_claim_column_drop


def test_runtime_models_match_bounded_persistence_contract() -> None:
    module = importlib.import_module("models.integration_health")
    health = module.IntegrationHealthState.__table__
    heartbeat = module.IntegrationWorkerHeartbeat.__table__
    notification_module = importlib.import_module("models.notification_job")
    notification = notification_module.NotificationJob.__table__

    assert health.name == HEALTH_TABLE
    assert health.primary_key.columns.keys() == ["provider"]
    assert health.columns["provider"].type.length == 64
    assert health.columns["state"].type.length == 32
    assert health.columns["last_error_category"].type.length == 64
    assert health.columns["last_error_message"].type.length == 500
    assert tuple(health.columns.keys()) == (
        "provider",
        "state",
        "last_checked_at",
        "last_succeeded_at",
        "last_error_category",
        "last_error_message",
        "consecutive_failures",
        "transition_epoch",
        "last_alerted_at",
        "next_reminder_at",
        "recovered_at",
        "created_at",
        "updated_at",
    )
    assert health.columns["state"].nullable is False
    assert health.columns["consecutive_failures"].nullable is False
    assert health.columns["consecutive_failures"].default.arg == 0
    assert str(health.columns["consecutive_failures"].server_default.arg) == "0"
    assert health.columns["transition_epoch"].nullable is False
    assert health.columns["transition_epoch"].default.arg == 1
    assert str(health.columns["transition_epoch"].server_default.arg) == "1"
    assert all(
        health.columns[name].type.timezone is True
        for name in (
            "last_checked_at",
            "last_succeeded_at",
            "last_alerted_at",
            "next_reminder_at",
            "recovered_at",
            "created_at",
            "updated_at",
        )
    )
    assert {
        constraint.name
        for constraint in health.constraints
        if isinstance(constraint, sa.CheckConstraint)
    } == {
        "ck_integration_health_consecutive_failures_nonnegative",
        "ck_integration_health_transition_epoch_positive",
    }

    assert heartbeat.name == HEARTBEAT_TABLE
    assert heartbeat.primary_key.columns.keys() == ["worker_id"]
    assert tuple(heartbeat.columns.keys()) == (
        "worker_id",
        "booted_at",
        "heartbeat_at",
        "current_job",
        "last_completed_job",
    )
    assert heartbeat.columns["worker_id"].type.length == 128
    assert heartbeat.columns["current_job"].type.length == 128
    assert heartbeat.columns["last_completed_job"].type.length == 128
    assert all(
        heartbeat.columns[name].type.timezone is True
        for name in ("booted_at", "heartbeat_at")
    )
    forbidden = {"subject", "recipient", "body", "token", "payload"}
    assert forbidden.isdisjoint(heartbeat.columns.keys())

    for name, length in (
        ("provider_key", 100),
        ("dedupe_key", 255),
        ("lease_owner", 128),
    ):
        assert notification.columns[name].type.length == length
        assert notification.columns[name].nullable is True
    assert notification.columns["lease_expires_at"].type.timezone is True
    indexes = {index.name: index for index in notification.indexes}
    dedupe_index = indexes["uq_notification_jobs_provider_dedupe"]
    assert dedupe_index.unique is True
    assert tuple(column.name for column in dedupe_index.columns) == (
        "provider_key",
        "dedupe_key",
    )
    assert str(
        dedupe_index.dialect_options["postgresql"].get("where")
    ) == "provider_key IS NOT NULL AND dedupe_key IS NOT NULL"
    dedupe_ddl = str(
        CreateIndex(dedupe_index).compile(dialect=postgresql.dialect())
    )
    assert dedupe_ddl == (
        "CREATE UNIQUE INDEX uq_notification_jobs_provider_dedupe ON "
        "notification_jobs (provider_key, dedupe_key) WHERE provider_key IS "
        "NOT NULL AND dedupe_key IS NOT NULL"
    )
    assert tuple(
        column.name for column in indexes["ix_notification_jobs_claimable"].columns
    ) == ("status", "next_attempt_at", "lease_expires_at", "id")
    compiled = str(
        CreateIndex(indexes["ix_notification_jobs_claimable"]).compile(
            dialect=postgresql.dialect()
        )
    )
    assert compiled == (
        "CREATE INDEX ix_notification_jobs_claimable ON notification_jobs "
        "(status, next_attempt_at, lease_expires_at, id)"
    )


def test_runtime_models_are_registered_for_application_and_alembic() -> None:
    models = importlib.import_module("models")
    module = importlib.import_module("models.integration_health")
    assert models.IntegrationHealthState is module.IntegrationHealthState
    assert models.IntegrationWorkerHeartbeat is module.IntegrationWorkerHeartbeat
    assert {
        "IntegrationHealthState",
        "IntegrationWorkerHeartbeat",
    }.issubset(set(models.__all__))
    env_source = (_backend_root() / "alembic" / "env.py").read_text(
        encoding="utf-8"
    )
    assert "import models.integration_health" in env_source


def test_revision_82_upgrades_existing_notification_rows_on_real_postgresql() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ) as run_marker:
            run_alembic(url, "upgrade", DOWN_REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_contacts "
                        "(id, first_name, last_name) "
                        "VALUES (501, 'Preexisting', 'Contact')"
                    )
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO crm_tasks "
                        "(id, contact_id, title, description, status, priority, "
                        "version, created_at, updated_at) VALUES "
                        "(502, 501, 'Preserve runtime migration', '', 'open', "
                        "'normal', 1, :created_at, :updated_at)"
                    ),
                    {
                        "created_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
                        "updated_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
                    },
                )
                existing_notification_id = connection.scalar(
                    sa.text(
                        "INSERT INTO notification_jobs "
                        "(event_type, status, recipient, subject, payload, "
                        "attempt_count, created_at, updated_at) VALUES "
                        "('existing', 'pending', 'admin@example.test', "
                        "'Existing', '{}', 0, :created_at, :updated_at)"
                        " RETURNING id"
                    ),
                    {
                        "created_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
                        "updated_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
                    },
                )

            run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                assert connection.scalar(
                    sa.text("SELECT version_num FROM alembic_version")
                ) == REVISION
                inspector = sa.inspect(connection)
                assert {HEALTH_TABLE, HEARTBEAT_TABLE}.issubset(
                    inspector.get_table_names()
                )
                notification_columns = {
                    column["name"]
                    for column in inspector.get_columns("notification_jobs")
                }
                assert {
                    "provider_key",
                    "dedupe_key",
                    "lease_owner",
                    "lease_expires_at",
                }.issubset(notification_columns)
                assert connection.execute(
                    sa.text(
                        "SELECT event_type, status, provider_key, dedupe_key, "
                        "lease_owner, lease_expires_at "
                        "FROM notification_jobs WHERE id = :job_id"
                    ),
                    {"job_id": existing_notification_id},
                ).one() == ("existing", "pending", None, None, None, None)
                assert connection.execute(
                    sa.text(
                        "SELECT c.first_name, t.title, t.version "
                        "FROM crm_contacts AS c JOIN crm_tasks AS t "
                        "ON t.contact_id = c.id WHERE t.id = 502"
                    )
                ).one() == (
                    "Preexisting",
                    "Preserve runtime migration",
                    1,
                )
                indexes = {
                    index["name"]: index
                    for index in inspector.get_indexes("notification_jobs")
                }
                assert tuple(
                    indexes["uq_notification_jobs_provider_dedupe"][
                        "column_names"
                    ]
                ) == ("provider_key", "dedupe_key")
                assert indexes["uq_notification_jobs_provider_dedupe"][
                    "unique"
                ] is True
                assert str(
                    indexes["uq_notification_jobs_provider_dedupe"][
                        "dialect_options"
                    ]["postgresql_where"]
                ) == "((provider_key IS NOT NULL) AND (dedupe_key IS NOT NULL))"
                assert tuple(
                    indexes["ix_notification_jobs_claimable"]["column_names"]
                ) == (
                    "status",
                    "next_attempt_at",
                    "lease_expires_at",
                    "id",
                )

            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO notification_jobs "
                        "(event_type, status, recipient, subject, payload, "
                        "attempt_count, provider_key, dedupe_key) VALUES "
                        "('null-dedupe-a', 'pending', 'admin@example.test', "
                        "'A', '{}', 0, NULL, NULL), "
                        "('null-dedupe-b', 'pending', 'admin@example.test', "
                        "'B', '{}', 0, NULL, NULL), "
                        "('deduped', 'pending', 'admin@example.test', "
                        "'C', '{}', 0, 'gmail_task_intake', 'epoch:1')"
                    )
                )
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO notification_jobs "
                            "(event_type, status, recipient, subject, payload, "
                            "attempt_count, provider_key, dedupe_key) VALUES "
                            "('duplicate', 'pending', 'admin@example.test', "
                            "'D', '{}', 0, 'gmail_task_intake', 'epoch:1')"
                        )
                    )

            run_owned_alembic_downgrade(
                url,
                DOWN_REVISION,
                expected_database=expected_database,
                run_marker=run_marker,
            )
            with engine.connect() as connection:
                inspector = sa.inspect(connection)
                assert {HEALTH_TABLE, HEARTBEAT_TABLE}.isdisjoint(
                    inspector.get_table_names()
                )
                assert {
                    "provider_key",
                    "dedupe_key",
                    "lease_owner",
                    "lease_expires_at",
                }.isdisjoint(
                    {
                        column["name"]
                        for column in inspector.get_columns("notification_jobs")
                    }
                )
                assert connection.scalar(
                    sa.text(
                        "SELECT event_type FROM notification_jobs "
                        "WHERE id = :job_id"
                    ),
                    {"job_id": existing_notification_id},
                ) == "existing"
                assert connection.execute(
                    sa.text(
                        "SELECT c.first_name, t.title, t.version "
                        "FROM crm_contacts AS c JOIN crm_tasks AS t "
                        "ON t.contact_id = c.id WHERE t.id = 502"
                    )
                ).one() == (
                    "Preexisting",
                    "Preserve runtime migration",
                    1,
                )

            run_alembic(url, "upgrade", REVISION)
            with engine.connect() as connection:
                assert connection.execute(
                    sa.text(
                        "SELECT c.first_name, t.title, t.version "
                        "FROM crm_contacts AS c JOIN crm_tasks AS t "
                        "ON t.contact_id = c.id WHERE t.id = 502"
                    )
                ).one() == (
                    "Preexisting",
                    "Preserve runtime migration",
                    1,
                )
            heads_output = run_alembic(url, "heads")
            repository_heads = _script_directory().get_heads()
            assert len(repository_heads) == 1
            assert heads_output.count(f"{repository_heads[0]} (head)") == 1
    finally:
        engine.dispose()
