from __future__ import annotations

import hashlib
import importlib.util
import os
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from tests.gmail_task_postgres import (
    gmail_task_test_url,
    migrated_test_database,
    owned_empty_test_schema,
    run_alembic,
    run_owned_alembic_downgrade,
    sync_test_url,
)

REVISION = "85e8b7c9d4f1"
DOWN_REVISION = "84d7a5f9b2c3"
HEAD_REVISION = "87a0d9b1e3f2"


def _backend_root() -> Path:
    return Path(__file__).parents[1]


def _revision_path() -> Path:
    return (
        _backend_root()
        / "alembic"
        / "versions"
        / "85e8b7c9d4f1_add_sydney_durable_context.py"
    )


def _load_revision():
    path = _revision_path()
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("sydney_context_revision_85", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_dedupe_revision():
    path = (
        _backend_root()
        / "alembic"
        / "versions"
        / "86f9c8a0d2e1_add_sydney_request_dedupe.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("sydney_context_revision_86", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scripts() -> ScriptDirectory:
    config = Config(str(_backend_root() / "alembic.ini"))
    config.set_main_option("script_location", str(_backend_root() / "alembic"))
    return ScriptDirectory.from_config(config)


def _render(function_name: str, *, revision=None) -> str:
    revision = revision or _load_revision()
    output = StringIO()
    revision.op = Operations(
        MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output},
        )
    )
    getattr(revision, function_name)()
    return " ".join(output.getvalue().split())


def test_revision_85_serially_follows_revision_84_and_86_is_the_only_head() -> None:
    revision = _load_revision()
    scripts = _scripts()

    assert revision.revision == REVISION
    assert revision.down_revision == DOWN_REVISION
    assert revision.branch_labels is None
    assert revision.depends_on is None
    assert scripts.get_heads() == [HEAD_REVISION]
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION
    assert scripts.get_revision("86f9c8a0d2e1").down_revision == REVISION
    assert scripts.get_revision(HEAD_REVISION).down_revision == "86f9c8a0d2e1"


def test_revision_86_adds_content_free_request_dedupe_and_receipts() -> None:
    revision = _load_dedupe_revision()
    sql = _render("upgrade", revision=revision)

    assert revision.revision == "86f9c8a0d2e1"
    assert revision.down_revision == REVISION
    assert "ADD COLUMN request_fingerprint_sha256 VARCHAR(64)" in sql
    assert "CREATE TABLE agent_run_request_receipts" in sql
    assert "uq_agent_run_jobs_active_request" in sql
    assert "WHERE state IN ('queued', 'running', 'waiting_retry')" in sql
    assert "normalize" in sql.lower()
    assert "search_text" in sql
    assert "request_text" not in sql


def test_revision_86_upgrades_real_postgresql_with_one_serial_head() -> None:
    with migrated_test_database(HEAD_REVISION) as (_url, engine):
        inspector = sa.inspect(engine)
        columns = {
            column["name"]: column for column in inspector.get_columns("agent_run_jobs")
        }
        assert columns["request_fingerprint_sha256"]["nullable"] is False
        assert "agent_run_request_receipts" in inspector.get_table_names()
        indexes = {
            index["name"]: index for index in inspector.get_indexes("agent_run_jobs")
        }
        active = indexes["uq_agent_run_jobs_active_request"]
        assert active["unique"] is True
        assert active["column_names"] == [
            "identity_id",
            "logical_conversation_id",
            "request_fingerprint_sha256",
        ]


def test_revision_86_coalesces_duplicate_active_history_to_the_live_canonical_run() -> (
    None
):
    from services.sydney_context_service import request_fingerprint_sha256

    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    identity_id = uuid4()
    session_id = uuid4()
    logical_id = uuid4()
    terminal_run_id = uuid4()
    canonical_run_id = uuid4()
    duplicate_run_id = uuid4()
    event_ids = [uuid4(), uuid4(), uuid4()]
    contents = [
        "source all september birthdays and home anniversaries",
        "  Source ALL September birthdays\nand home anniversaries  ",
        "source all september birthdays and home anniversaries",
    ]
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ):
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO agent_conversation_identities "
                        "(id, platform, external_user_id, external_chat_id, "
                        "display_label) VALUES (:id, 'telegram', 'user-1', "
                        "'chat-1', 'Brandon')"
                    ),
                    {"id": identity_id},
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO agent_conversation_sessions "
                        "(id, identity_id, hermes_session_id, "
                        "logical_conversation_id, platform) VALUES "
                        "(:id, :identity, 'session-1', :logical, 'telegram')"
                    ),
                    {
                        "id": session_id,
                        "identity": identity_id,
                        "logical": logical_id,
                    },
                )
                for index, (event_id, content) in enumerate(
                    zip(event_ids, contents, strict=True),
                    start=1,
                ):
                    connection.execute(
                        sa.text(
                            "INSERT INTO agent_conversation_events "
                            "(id, identity_id, session_id, source_event_key, "
                            "event_type, role, occurred_at, content_sha256, "
                            "redaction_status, search_text) VALUES "
                            "(:id, :identity, :session, :source, 'user', 'user', "
                            ":occurred, :digest, 'unchanged', :content)"
                        ),
                        {
                            "id": event_id,
                            "identity": identity_id,
                            "session": session_id,
                            "source": f"session-1:{index}",
                            "occurred": f"2026-09-04T12:0{index}:00+00:00",
                            "digest": hashlib.sha256(content.encode()).hexdigest(),
                            "content": content,
                        },
                    )
                for index, (run_id, event_id, state) in enumerate(
                    (
                        (terminal_run_id, event_ids[0], "terminal_failure"),
                        (canonical_run_id, event_ids[1], "queued"),
                        (duplicate_run_id, event_ids[2], "running"),
                    ),
                    start=1,
                ):
                    connection.execute(
                        sa.text(
                            "INSERT INTO agent_run_jobs "
                            "(id, identity_id, platform_message_id, "
                            "inbound_event_id, session_id, logical_conversation_id, "
                            "state, attempt_count, terminal_deadline_at, created_at) "
                            "VALUES (:id, :identity, :message, :event, :session, "
                            ":logical, :state, 0, "
                            "'2026-09-05T12:00:00+00:00', :created)"
                        ),
                        {
                            "id": run_id,
                            "identity": identity_id,
                            "message": f"telegram-{index}",
                            "event": event_id,
                            "session": session_id,
                            "logical": logical_id,
                            "state": state,
                            "created": f"2026-09-04T12:1{index}:00+00:00",
                        },
                    )
            run_alembic(url, "upgrade", HEAD_REVISION)

            with engine.begin() as connection:
                runs = connection.execute(
                    sa.text(
                        "SELECT id, state, request_fingerprint_sha256 "
                        "FROM agent_run_jobs ORDER BY created_at"
                    )
                ).all()
                receipts = connection.execute(
                    sa.text(
                        "SELECT platform_message_id, run_id, disposition "
                        "FROM agent_run_request_receipts "
                        "ORDER BY platform_message_id"
                    )
                ).all()

            expected_fingerprint = request_fingerprint_sha256(contents[0])
            assert {row.request_fingerprint_sha256 for row in runs} == {
                expected_fingerprint
            }
            assert [(row.id, row.state) for row in runs] == [
                (terminal_run_id, "terminal_failure"),
                (canonical_run_id, "queued"),
                (duplicate_run_id, "terminal_failure"),
            ]
            assert [
                (row.platform_message_id, row.run_id, row.disposition)
                for row in receipts
            ] == [
                ("telegram-1", terminal_run_id, "primary"),
                ("telegram-2", canonical_run_id, "primary"),
                ("telegram-3", canonical_run_id, "coalesced"),
            ]
    finally:
        engine.dispose()


def test_upgrade_creates_exact_context_tables_search_and_append_only_guards() -> None:
    sql = _render("upgrade")

    for table in (
        "agent_conversation_identities",
        "agent_conversation_sessions",
        "agent_conversation_events",
        "agent_conversation_event_segments",
        "agent_context_checkpoints",
        "agent_context_projection_claims",
        "agent_memory_facts",
        "agent_run_jobs",
        "agent_tool_invocations",
    ):
        assert f"CREATE TABLE {table}" in sql
    assert "tsvector" in sql
    assert "left(coalesce(search_text, ''), 32768)" in sql
    assert "right(coalesce(search_text, ''), 32768)" in sql
    assert "USING gin (search_vector)" in sql
    assert "ingestion_sequence BIGINT GENERATED BY DEFAULT AS IDENTITY" in sql
    assert "ix_agent_conversation_events_projection" in sql
    assert "source_boundary_char_offset INTEGER NOT NULL" in sql
    assert "source_boundary_char_offset >= 0" in sql
    assert "sydney_context_reject_append_only_mutation" in sql
    assert "DROP TABLE" not in sql


def test_downgrade_locks_and_refuses_to_discard_nonempty_context_evidence() -> None:
    sql = _render("downgrade")

    assert "IN ACCESS EXCLUSIVE MODE" in sql
    assert "revision 85 downgrade refused" in sql
    assert sql.index("revision 85 downgrade refused") < sql.index(
        "DROP TABLE agent_tool_invocations"
    )


def test_revision_85_upgrades_real_postgresql_and_enforces_append_only() -> None:
    with migrated_test_database(REVISION) as (_url, engine):
        inspector = sa.inspect(engine)
        assert {
            "agent_conversation_identities",
            "agent_conversation_sessions",
            "agent_conversation_events",
            "agent_conversation_event_segments",
            "agent_context_checkpoints",
            "agent_context_projection_claims",
            "agent_memory_facts",
            "agent_run_jobs",
            "agent_tool_invocations",
        }.issubset(inspector.get_table_names())
        event_columns = {
            column["name"]: column
            for column in inspector.get_columns("agent_conversation_events")
        }
        assert event_columns["ingestion_sequence"]["nullable"] is False

        identity_id = uuid4()
        session_id = uuid4()
        event_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO agent_conversation_identities "
                    "(id, platform, external_user_id, external_chat_id, "
                    "display_label) VALUES (:id, 'telegram', 'user-1', "
                    "'chat-1', 'Brandon')"
                ),
                {"id": identity_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO agent_conversation_sessions "
                    "(id, identity_id, hermes_session_id, "
                    "logical_conversation_id, platform) VALUES "
                    "(:id, :identity, 'session-1', :logical, 'telegram')"
                ),
                {"id": session_id, "identity": identity_id, "logical": uuid4()},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO agent_conversation_events "
                    "(id, identity_id, session_id, source_event_key, event_type, "
                    "role, occurred_at, content_sha256, redaction_status, search_text) "
                    "VALUES (:id, :identity, :session, 'session-1:1', 'user', "
                    "'user', now(), :digest, 'unchanged', 'remember the gold folder')"
                ),
                {
                    "id": event_id,
                    "identity": identity_id,
                    "session": session_id,
                    "digest": "a" * 64,
                },
            )
        with (
            pytest.raises(sa.exc.DBAPIError, match="sydney_context_append_only"),
            engine.begin() as connection,
        ):
            connection.execute(
                sa.text(
                    "UPDATE agent_conversation_events SET search_text = 'changed' "
                    "WHERE id = :id"
                ),
                {"id": event_id},
            )


def test_revision_85_nonempty_downgrade_refuses_and_empty_downgrade_succeeds() -> None:
    url = gmail_task_test_url()
    expected_database = os.environ["GMAIL_TASK_TEST_DATABASE_NAME"]
    engine = sa.create_engine(sync_test_url(url))
    try:
        with owned_empty_test_schema(
            engine,
            expected_database=expected_database,
        ) as run_marker:
            run_alembic(url, "upgrade", REVISION)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO agent_conversation_identities "
                        "(platform, external_user_id, external_chat_id, display_label) "
                        "VALUES ('telegram', 'user-1', 'chat-1', 'Brandon')"
                    )
                )
            with pytest.raises(RuntimeError, match="revision 85 downgrade refused"):
                run_owned_alembic_downgrade(
                    url,
                    DOWN_REVISION,
                    expected_database=expected_database,
                    run_marker=run_marker,
                )
            with engine.begin() as connection:
                connection.execute(sa.text("DELETE FROM agent_conversation_identities"))
            run_owned_alembic_downgrade(
                url,
                DOWN_REVISION,
                expected_database=expected_database,
                run_marker=run_marker,
            )
            assert (
                "agent_conversation_identities"
                not in sa.inspect(engine).get_table_names()
            )
    finally:
        engine.dispose()
