from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[2] / "hermes" / "overlay"
sys.path.insert(0, str(OVERLAY))

from sydney_spool import SpoolConflict, SydneySpool


def _bundle(message_id: str = "telegram-1") -> tuple[dict, dict]:
    event_batch = {
        "platform": "telegram",
        "external_user_id": "brandon",
        "external_chat_id": "private-chat",
        "display_label": "Brandon",
        "hermes_session_id": "session-1",
        "logical_conversation_id": "11111111-1111-4111-8111-111111111111",
        "events": [
            {
                "source_event_key": f"telegram:{message_id}:user",
                "event_type": "user",
                "role": "user",
                "occurred_at": "2026-08-25T12:00:00+00:00",
                "content": "Keep this context",
                "metadata": {"message_id": message_id},
            }
        ],
    }
    run_start = {
        "platform_message_id": message_id,
        "terminal_deadline_at": "2026-08-26T12:00:00+00:00",
    }
    return event_batch, run_start


def test_creates_private_wal_database_with_explicit_schema(tmp_path: Path) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    try:
        assert spool.schema_version == 1
        assert spool.pragma("journal_mode").lower() == "wal"
        assert int(spool.pragma("synchronous")) == 2
        assert int(spool.pragma("foreign_keys")) == 1
        assert int(spool.pragma("busy_timeout")) >= 5_000
        assert (spool.path.stat().st_mode & 0o777) == 0o600
    finally:
        spool.close()


def test_inbound_event_and_run_are_committed_as_one_exactly_replayable_unit(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, run_start = _bundle()
    first = spool.enqueue_inbound(event_batch, run_start, source_key="inbound:1")
    replay = spool.enqueue_inbound(event_batch, run_start, source_key="inbound:1")

    assert replay == first
    assert spool.pending_count == 1
    record = spool.pending(limit=10)[0]
    assert record.kind == "inbound_bundle"
    assert record.payload == {"event_batch": event_batch, "run_start": run_start}

    conflicting_event, conflicting_run = _bundle("different")
    with pytest.raises(SpoolConflict):
        spool.enqueue_inbound(
            conflicting_event,
            conflicting_run,
            source_key="inbound:1",
        )


def test_secret_material_is_redacted_before_sqlite_persistence(tmp_path: Path) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    event_batch, run_start = _bundle()
    secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
    event_batch["events"][0]["content"] = (
        f"Authorization: Bearer {secret} password=hunter2 "
        "https://example.test/path?access_token=oauth-secret#handoff=signed"
    )
    spool.enqueue_inbound(event_batch, run_start, source_key="inbound:redacted")
    spool.close()

    database_bytes = (tmp_path / "sydney_spool.db").read_bytes()
    wal_path = tmp_path / "sydney_spool.db-wal"
    if wal_path.exists():
        database_bytes += wal_path.read_bytes()
    assert secret.encode() not in database_bytes
    assert b"hunter2" not in database_bytes
    assert b"oauth-secret" not in database_bytes
    assert b"#handoff=signed" not in database_bytes


def test_ordered_bounded_drain_acknowledges_only_successful_delivery(
    tmp_path: Path,
) -> None:
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    for index in range(4):
        spool.enqueue(
            kind="event_batch",
            source_key=f"event:{index}",
            payload={"index": index},
        )

    delivered: list[int] = []

    def handler(record):
        delivered.append(record.payload["index"])
        if record.payload["index"] == 1:
            raise TimeoutError("backend unavailable")
        return {"receipt": record.payload["index"]}

    result = spool.drain(handler, limit=3)

    assert delivered == [0, 1]
    assert result.acknowledged == 1
    assert result.failed == 1
    assert [item.payload["index"] for item in spool.pending(limit=10)] == [1, 2, 3]
    assert spool.get_record("event:0").receipt == {"receipt": 0}
    assert spool.get_record("event:1").attempt_count == 1


def test_crash_reopen_recovers_and_drains_once(tmp_path: Path) -> None:
    spool_path = tmp_path / "sydney_spool.db"
    script = textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {str(OVERLAY)!r})
        from sydney_spool import SydneySpool
        spool = SydneySpool({str(spool_path)!r})
        spool.enqueue(kind='event_batch', source_key='crash:1', payload={{'value': 1}})
        os._exit(23)
        """
    )
    completed = subprocess.run([sys.executable, "-c", script], check=False)
    assert completed.returncode == 23

    reopened = SydneySpool(spool_path)
    calls: list[str] = []
    reopened.drain(lambda record: calls.append(record.source_key) or {"ok": True})
    reopened.drain(lambda record: calls.append(record.source_key) or {"ok": True})
    assert calls == ["crash:1"]
    assert reopened.pending_count == 0


def test_tool_records_cache_lineage_and_cursor_survive_reopen(tmp_path: Path) -> None:
    spool_path = tmp_path / "sydney_spool.db"
    spool = SydneySpool(spool_path)
    before_id = spool.enqueue_tool_before(
        run_id="run-1",
        tool_call_id="call-1",
        tool_name="command_contacts_search",
        arguments={"query": "Brandon"},
        side_effect_class="read_only",
    )
    after_id = spool.enqueue_tool_after(
        run_id="run-1",
        tool_call_id="call-1",
        state="succeeded",
        result_event_id="22222222-2222-4222-8222-222222222222",
    )
    spool.rotate_session(
        session_id="session-2",
        logical_conversation_id="11111111-1111-4111-8111-111111111111",
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        parent_session_id="session-1",
        continuation_reason="compression",
    )
    packet = {
        "rendered_context": "source-linked context",
        "estimated_tokens": 5,
        "sections": [{"source_event_ids": ["source-1"]}],
    }
    spool.cache_context("session-2", packet)
    spool.set_reconciliation_cursor("session-2", 8, "ordered-hash")
    spool.close()

    reopened = SydneySpool(spool_path)
    assert before_id != after_id
    assert [record.kind for record in reopened.pending(limit=10)] == [
        "tool_before",
        "tool_after",
    ]
    assert reopened.get_session("session-2")["parent_session_id"] == "session-1"
    assert reopened.get_cached_context("session-2") == packet
    assert reopened.get_reconciliation_cursor("session-2") == {
        "event_count": 8,
        "ordered_hash": "ordered-hash",
    }


def test_spool_never_creates_token_columns_or_persists_environment_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_CONTROL_TOKEN", "environment-only-token")
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    spool.enqueue(kind="event_batch", source_key="safe:1", payload={"ok": True})
    columns = {
        row[1]
        for table in ("spool_meta", "session_lineage", "outbox", "context_cache")
        for row in spool.connection.execute(f"PRAGMA table_info({table})")
    }
    spool.close()
    assert not any(
        "token" in column.lower() or "authorization" in column.lower()
        for column in columns
    )
    assert b"environment-only-token" not in (tmp_path / "sydney_spool.db").read_bytes()
