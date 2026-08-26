from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[2] / "hermes" / "overlay"
sys.path.insert(0, str(OVERLAY))

from sydney_backfill import SydneyBackfill
from sydney_spool import SydneySpool


class _ReceiptBackend:
    def __init__(self) -> None:
        self.events: dict[str, list[dict]] = {}
        self.reconciliations: list[dict] = []

    def ingest_events(self, payload: dict) -> dict:
        from uuid import NAMESPACE_URL, uuid5

        receipts = []
        for event in payload["events"]:
            event_id = str(uuid5(NAMESPACE_URL, event["source_event_key"]))
            receipts.append(
                {
                    "event_id": event_id,
                    "event_type": event["event_type"],
                    "occurred_at": event["occurred_at"],
                    "content_sha256": __import__("hashlib")
                    .sha256(event["content"].encode())
                    .hexdigest(),
                }
            )
        self.events.setdefault(payload["hermes_session_id"], []).extend(receipts)
        return {
            "identity_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "session_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "logical_conversation_id": payload["logical_conversation_id"],
            "event_ids": [receipt["event_id"] for receipt in receipts],
            "event_receipts": receipts,
            "inserted_count": len(receipts),
            "replayed_count": 0,
        }

    def reconcile_session(self, payload: dict) -> dict:
        from sydney_spool import ordered_reconciliation_hash

        self.reconciliations.append(payload)
        rows = self.events[payload["hermes_session_id"]]
        digest = ordered_reconciliation_hash(rows)
        return {
            "identity_id": payload["identity_id"],
            "session_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "hermes_session_id": payload["hermes_session_id"],
            "event_count": len(rows),
            "ordered_hash": digest,
            "matched": (
                payload["expected_event_count"] == len(rows)
                and payload["expected_ordered_hash"] == digest
            ),
        }


def _seed_state(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            user_id TEXT,
            parent_session_id TEXT,
            started_at REAL NOT NULL,
            ended_at REAL,
            end_reason TEXT
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            timestamp REAL NOT NULL,
            reasoning TEXT,
            reasoning_content TEXT,
            reasoning_details TEXT,
            platform_message_id TEXT,
            observed INTEGER DEFAULT 0
        );
        INSERT INTO sessions VALUES (
            'session-1', 'telegram', 'brandon', NULL,
            1766664000, 1766664999, 'compression'
        );
        INSERT INTO sessions VALUES (
            'session-2', 'telegram', NULL, 'session-1',
            1766665000, NULL, NULL
        );
        INSERT INTO sessions VALUES (
            'other-session', 'telegram', 'someone-else', NULL,
            1766666000, NULL, NULL
        );
        """
    )
    connection.executemany(
        """
        INSERT INTO messages(
            session_id, role, content, tool_call_id, tool_calls, tool_name,
            timestamp, reasoning, reasoning_content, reasoning_details,
            platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "session-1",
                "user",
                "Remember the closing date. password=hunter2",
                None,
                None,
                None,
                1766664001,
                "never persist this reasoning",
                None,
                None,
                "telegram-1",
                0,
            ),
            (
                "session-1",
                "assistant",
                "I will remember.",
                None,
                json.dumps(
                    [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "command_contacts_search",
                                "arguments": '{"query":"Brandon"}',
                            },
                        }
                    ]
                ),
                None,
                1766664002,
                None,
                "hidden thought signature",
                '{"encrypted":"hidden"}',
                None,
                0,
            ),
            (
                "session-1",
                "tool",
                '{"total":1}',
                "call-1",
                None,
                "command_contacts_search",
                1766664003,
                None,
                None,
                None,
                None,
                0,
            ),
            (
                "session-2",
                "assistant",
                "Continuation complete.",
                None,
                None,
                None,
                1766665001,
                None,
                None,
                None,
                None,
                0,
            ),
            (
                "session-2",
                "user",
                "Observed group chatter",
                None,
                None,
                None,
                1766665002,
                None,
                None,
                None,
                None,
                1,
            ),
            (
                "other-session",
                "user",
                "Another person's private history",
                None,
                None,
                None,
                1766666001,
                None,
                None,
                None,
                "telegram-other",
                0,
            ),
        ],
    )
    connection.commit()
    connection.close()
    sessions_directory = path.parent / "sessions"
    sessions_directory.mkdir()
    (sessions_directory / "sessions.json").write_text(
        json.dumps(
            {
                "agent:main:telegram:dm:private-chat": {
                    "session_key": "agent:main:telegram:dm:private-chat",
                    "session_id": "session-2",
                    "updated_at": "2026-08-25T12:00:00+00:00",
                    "platform": "telegram",
                    "chat_type": "dm",
                    "origin": {
                        "platform": "telegram",
                        "chat_id": "private-chat",
                        "chat_type": "dm",
                        "user_id": "brandon",
                    },
                },
                "agent:main:telegram:dm:other-chat": {
                    "session_key": "agent:main:telegram:dm:other-chat",
                    "session_id": "other-session",
                    "updated_at": "2026-08-25T12:01:00+00:00",
                    "platform": "telegram",
                    "chat_type": "dm",
                    "origin": {
                        "platform": "telegram",
                        "chat_id": "other-chat",
                        "chat_type": "dm",
                        "user_id": "someone-else",
                    },
                },
            }
        )
    )


def test_backfill_pages_visible_history_redacts_and_deduplicates(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    backfill = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )

    report = backfill.run(page_size=2)
    replay = backfill.run(page_size=2)

    assert report == replay
    assert report["session_count"] == 2
    assert report["message_count"] == 4
    assert report["role_counts"] == {"assistant": 2, "tool": 1, "user": 1}
    assert report["tool_call_count"] == 1
    assert report["tool_result_count"] == 1
    assert len(report["ordered_hash"]) == 64
    assert len(report["sessions"]) == 2
    assert spool.pending_count == 5

    serialized = json.dumps([record.payload for record in spool.pending(limit=100)])
    assert "hunter2" not in serialized
    assert "REDACTED" in serialized
    assert "never persist this reasoning" not in serialized
    assert "hidden thought signature" not in serialized
    assert '"encrypted":"hidden"' not in serialized
    assert "Observed group chatter" not in serialized
    assert "Another person's private history" not in serialized
    assert "call-1" in serialized
    assert "command_contacts_search" in serialized
    child_batches = [
        record.payload
        for record in spool.pending(limit=100)
        if record.payload.get("hermes_session_id") == "session-2"
    ]
    assert child_batches
    assert all(
        batch["parent_hermes_session_id"] == "session-1" for batch in child_batches
    )


def test_backfill_excludes_delegated_child_sessions_from_durable_history(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    connection = sqlite3.connect(state_path)
    connection.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "delegated-child",
            "telegram",
            None,
            "session-2",
            1766665500,
            1766665599,
            "completed",
        ),
    )
    connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, timestamp, platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        (
            "delegated-child",
            "user",
            "Internal delegated research objective",
            1766665501,
            None,
            0,
        ),
    )
    connection.commit()
    connection.close()
    spool = SydneySpool(tmp_path / "sydney_spool.db")

    report = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    ).run()

    serialized = json.dumps([record.payload for record in spool.pending(limit=100)])
    assert report["session_count"] == 2
    assert "Internal delegated research objective" not in serialized
    assert "delegated-child" not in serialized


def test_backfill_omits_parent_link_when_parent_has_no_canonical_event(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    connection = sqlite3.connect(state_path)
    connection.execute("DELETE FROM messages WHERE session_id = 'session-1'")
    connection.commit()
    connection.close()
    spool = SydneySpool(tmp_path / "sydney_spool.db")

    SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    ).run()

    child_batches = [
        record.payload
        for record in spool.pending(limit=100)
        if record.payload.get("hermes_session_id") == "session-2"
    ]
    assert child_batches
    assert all(batch["parent_hermes_session_id"] is None for batch in child_batches)
    assert all(
        batch["continuation_reason"] == "backfill_root" for batch in child_batches
    )


def test_completed_backfill_reuses_report_without_historical_rescan(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    spool_path = tmp_path / "sydney_spool.db"
    _seed_state(state_path)
    first_spool = SydneySpool(spool_path)
    first = SydneyBackfill(
        state_db=state_path,
        spool=first_spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    ).run(page_size=2)
    first_spool.close()

    class NoHistoricalRescanConnection:
        def __init__(self, path: Path) -> None:
            self._connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            self._connection.row_factory = sqlite3.Row

        def execute(self, sql: str, *args, **kwargs):
            normalized = " ".join(sql.split())
            if (
                " FROM messages " in f" {normalized} "
                and " AND id <= ? ORDER BY id" in normalized
                and " AND id > ?" not in normalized
            ):
                raise AssertionError("completed backfill rescanned historical messages")
            return self._connection.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self._connection.close()

    class RestartedBackfill(SydneyBackfill):
        def _connect(self):
            return NoHistoricalRescanConnection(self.state_db)

    reopened = SydneySpool(spool_path)
    replay = RestartedBackfill(
        state_db=state_path,
        spool=reopened,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    ).run(page_size=2)

    assert replay == first
    assert reopened.pending_count == 5


def test_backfill_decodes_hermes_structured_content_without_persisting_nul(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    structured = "\x00json:" + json.dumps(
        [
            {"type": "text", "text": "Visible structured caption"},
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://example.test/photo.jpg?token=private-image-token"
                },
            },
        ]
    )
    connection = sqlite3.connect(state_path)
    connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, timestamp, platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        ("session-2", "assistant", structured, 1766665004, None, 0),
    )
    connection.commit()
    connection.close()
    spool = SydneySpool(tmp_path / "sydney_spool.db")

    SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    ).run()

    serialized = json.dumps(
        [record.payload for record in spool.pending(limit=100)],
        ensure_ascii=False,
    )
    assert "Visible structured caption" in serialized
    assert "attachment:image_url" in serialized
    assert "private-image-token" not in serialized
    assert "\\u0000" not in serialized


def test_backfill_cursor_recovers_after_reopen_without_duplicate_rows(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    spool_path = tmp_path / "sydney_spool.db"
    _seed_state(state_path)
    first_spool = SydneySpool(spool_path)
    first = SydneyBackfill(
        state_db=state_path,
        spool=first_spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )
    first.run(page_size=1, max_pages=1)
    first_spool.close()

    reopened = SydneySpool(spool_path)
    resumed = SydneyBackfill(
        state_db=state_path,
        spool=reopened,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )
    report = resumed.run(page_size=1)
    assert report["message_count"] == 4
    assert reopened.pending_count == 5


def test_backfill_cutover_excludes_messages_created_after_live_ingest_begins(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    backfill = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )
    initial = backfill.run(page_size=2)

    connection = sqlite3.connect(state_path)
    connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, timestamp, platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        (
            "session-2",
            "assistant",
            "This arrived through the live runtime hook.",
            1766665003,
            None,
            0,
        ),
    )
    connection.commit()
    connection.close()

    restarted = backfill.run(page_size=2)

    assert restarted == initial
    assert spool.pending_count == 5
    serialized = json.dumps([record.payload for record in spool.pending(limit=100)])
    assert "This arrived through the live runtime hook." not in serialized


def test_backfill_streams_source_rows_without_fetchall(tmp_path: Path) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    spool = SydneySpool(tmp_path / "sydney_spool.db")

    class CursorWithoutFetchAll:
        def __init__(self, cursor: sqlite3.Cursor) -> None:
            self._cursor = cursor

        def __iter__(self):
            return iter(self._cursor)

        def fetchall(self):
            raise AssertionError("backfill must stream or page source rows")

        def __getattr__(self, name: str):
            return getattr(self._cursor, name)

    class ConnectionWithoutFetchAll:
        def __init__(self, path: Path) -> None:
            self._connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            self._connection.row_factory = sqlite3.Row

        def execute(self, *args, **kwargs):
            return CursorWithoutFetchAll(self._connection.execute(*args, **kwargs))

        def close(self) -> None:
            self._connection.close()

    class StreamingBackfill(SydneyBackfill):
        def _connect(self):
            return ConnectionWithoutFetchAll(self.state_db)

    report = StreamingBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    ).run(page_size=2)

    assert report["message_count"] == 4
    assert spool.pending_count == 5


def test_backfill_report_is_content_free(tmp_path: Path) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    report = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    ).run()
    encoded = json.dumps(report)
    assert "closing date" not in encoded
    assert "Brandon" not in encoded
    assert "private-chat" not in encoded


def test_backfill_excludes_same_user_history_from_another_chat(tmp_path: Path) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    connection = sqlite3.connect(state_path)
    connection.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "same-user-other-chat",
            "telegram",
            "brandon",
            None,
            1766667000,
            None,
            None,
        ),
    )
    connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, timestamp, platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        (
            "same-user-other-chat",
            "user",
            "This belongs to Brandon's other Telegram chat",
            1766667001,
            "telegram-other-chat",
            0,
        ),
    )
    connection.commit()
    connection.close()
    sessions_path = tmp_path / "sessions" / "sessions.json"
    sessions = json.loads(sessions_path.read_text())
    sessions["agent:main:telegram:group:other"] = {
        "session_key": "agent:main:telegram:group:other",
        "session_id": "same-user-other-chat",
        "updated_at": "2026-08-25T12:02:00+00:00",
        "platform": "telegram",
        "chat_type": "group",
        "origin": {
            "platform": "telegram",
            "chat_id": "other-group",
            "chat_type": "group",
            "user_id": "brandon",
        },
    }
    sessions_path.write_text(json.dumps(sessions))

    spool = SydneySpool(tmp_path / "sydney_spool.db")
    report = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    ).run()

    assert report["session_count"] == 2
    serialized = json.dumps([record.payload for record in spool.pending(limit=100)])
    assert "This belongs to Brandon's other Telegram chat" not in serialized


def test_backfill_fails_closed_when_history_has_no_exact_chat_index(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    (tmp_path / "sessions" / "sessions.json").unlink()
    spool = SydneySpool(tmp_path / "sydney_spool.db")

    with pytest.raises(RuntimeError, match="exact chat session mapping"):
        SydneyBackfill(
            state_db=state_path,
            spool=spool,
            platform="telegram",
            external_user_id="brandon",
            external_chat_id="private-chat",
            display_label="Brandon",
        ).run()


def test_backfill_fails_closed_when_prior_reset_history_is_unmapped(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    connection = sqlite3.connect(state_path)
    connection.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "prior-reset-session",
            "telegram",
            "brandon",
            None,
            1766663000,
            1766663999,
            "session_reset",
        ),
    )
    connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, timestamp, platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        (
            "prior-reset-session",
            "user",
            "History from before the reset must not be silently omitted.",
            1766663001,
            "telegram-prior-reset",
            0,
        ),
    )
    connection.commit()
    connection.close()
    spool = SydneySpool(tmp_path / "sydney_spool.db")

    with pytest.raises(RuntimeError, match="unmapped same-user session history"):
        SydneyBackfill(
            state_db=state_path,
            spool=spool,
            platform="telegram",
            external_user_id="brandon",
            external_chat_id="private-chat",
            display_label="Brandon",
        ).run()


def test_backfill_drains_and_proves_content_free_exact_reconciliation(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    backfill = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )
    source = backfill.run()
    backend = _ReceiptBackend()

    report = backfill.drain_and_reconcile(backend, wait_seconds=1)

    assert spool.pending_count == 0
    assert report["matched"] is True
    assert report["unacknowledged_count"] == 0
    assert report["compacted_record_count"] > 0
    assert (
        spool.connection.execute(
            "SELECT count(*) FROM outbox WHERE state='acknowledged'"
        ).fetchone()[0]
        == 0
    )
    assert report["source"]["message_count"] == source["message_count"]
    assert report["acknowledged"]["session_count"] == source["session_count"]
    assert report["acknowledged"]["message_count"] == source["message_count"]
    assert report["source"]["role_counts"] == report["acknowledged"]["role_counts"]
    assert report["source"]["tool_call_count"] == 1
    assert report["acknowledged"]["tool_call_count"] == 1
    assert report["source"]["tool_result_count"] == 1
    assert report["acknowledged"]["tool_result_count"] == 1
    assert report["source"]["ordered_hash"] == report["acknowledged"]["ordered_hash"]
    assert all(session["matched"] for session in report["sessions"])
    assert all(
        len(session["session_key_sha256"]) == 64 for session in report["sessions"]
    )
    assert "session-1" not in json.dumps(report)
    assert "private-chat" not in json.dumps(report)

    replay = backfill.drain_and_reconcile(backend, wait_seconds=1)

    assert replay["matched"] is True
    assert replay["unacknowledged_count"] == 0
    assert replay["compacted_record_count"] == 0
    assert replay["source"] == report["source"]
    assert replay["acknowledged"] == report["acknowledged"]
    assert all(session["matched"] for session in replay["sessions"])
    assert "session-1" not in json.dumps(replay)
    assert "private-chat" not in json.dumps(replay)


def test_live_tail_scan_recovers_only_rows_written_after_backfill_cutover(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    backfill = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )
    backfill.run()
    before = spool.pending_count

    connection = sqlite3.connect(state_path)
    cursor = connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, tool_call_id, tool_calls, tool_name,
            timestamp, reasoning, reasoning_content, reasoning_details,
            platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "session-2",
            "assistant",
            "Recovered response written immediately before a crash.",
            None,
            None,
            None,
            1766667001,
            "must not persist",
            None,
            None,
            None,
            0,
        ),
    )
    state_message_id = int(cursor.lastrowid)
    connection.commit()
    connection.close()

    first = backfill.run_live_tail(page_size=10)
    replay = backfill.run_live_tail(page_size=10)

    assert first == 1
    assert replay == 0
    assert spool.pending_count == before + 1
    recovered = spool.get_record(f"tail:state:session-2:{state_message_id}:assistant")
    assert recovered is not None
    assert recovered.payload["events"][0]["content"] == (
        "Recovered response written immediately before a crash."
    )
    assert "must not persist" not in json.dumps(recovered.payload)


def test_backfill_reuses_live_session_lineage_instead_of_relabeling_it(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    backfill = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )
    spool.rotate_session(
        session_id="session-1",
        logical_conversation_id=backfill.logical_conversation_id,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        parent_session_id=None,
        continuation_reason="initial",
    )
    spool.rotate_session(
        session_id="session-2",
        logical_conversation_id=backfill.logical_conversation_id,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        parent_session_id="session-1",
        continuation_reason="compression",
    )

    backfill.run(page_size=100)

    assert spool.get_session("session-1")["continuation_reason"] == "initial"
    assert spool.get_session("session-2")["continuation_reason"] == "compression"
    batches = [
        record.payload
        for record in spool.matching_records(state="pending", source_prefix="backfill:")
    ]
    reasons = {
        batch["hermes_session_id"]: batch["continuation_reason"] for batch in batches
    }
    assert reasons["session-1"] == "initial"
    assert reasons["session-2"] == "compression"


def test_persisted_internal_continuation_is_not_mirrored_as_a_user_request(
    tmp_path: Path,
) -> None:
    from sydney_gateway import _CONTINUATION_MARKER

    spool = SydneySpool(tmp_path / "sydney_spool.db")
    backfill = SydneyBackfill(
        state_db=tmp_path / "state.db",
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )

    events = backfill._events_for_message(
        {
            "id": 41,
            "session_id": "session-continuation",
            "role": "user",
            "content": _CONTINUATION_MARKER,
            "timestamp": 1766665000,
            "platform_message_id": "telegram-original",
            "observed": 0,
        }
    )

    assert len(events) == 1
    assert events[0]["event_type"] == "continuation"
    assert events[0]["source_event_key"].endswith(":continuation")
    assert events[0]["content"] == _CONTINUATION_MARKER


def test_live_tail_scan_does_not_duplicate_a_row_already_written_by_live_hooks(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    backfill = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )
    backfill.run()
    connection = sqlite3.connect(state_path)
    cursor = connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, tool_call_id, tool_calls, tool_name,
            timestamp, reasoning, reasoning_content, reasoning_details,
            platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "session-2",
            "assistant",
            "Already covered by the completion hook.",
            None,
            None,
            None,
            1766667001,
            None,
            None,
            None,
            None,
            0,
        ),
    )
    state_message_id = int(cursor.lastrowid)
    connection.commit()
    connection.close()
    spool.enqueue(
        kind="event_batch",
        source_key="run:run-live:completion",
        payload={
            "platform": "telegram",
            "external_user_id": "brandon",
            "external_chat_id": "private-chat",
            "display_label": "Brandon",
            "hermes_session_id": "session-2",
            "logical_conversation_id": backfill.logical_conversation_id,
            "events": [
                {
                    "source_event_key": "run:run-live:final_response",
                    "event_type": "assistant",
                    "role": "assistant",
                    "occurred_at": "2025-12-25T12:50:01+00:00",
                    "content": "Already covered by the completion hook.",
                    "metadata": {"run_completion": True},
                }
            ],
        },
    )

    assert backfill.run_live_tail(page_size=10) == 0
    assert (
        spool.get_record(f"tail:state:session-2:{state_message_id}:assistant") is None
    )


def test_live_tail_match_consumes_each_live_source_only_once_across_restarts(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    _seed_state(state_path)
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    backfill = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )
    backfill.run()
    spool.enqueue(
        kind="event_batch",
        source_key="run:run-live:completion",
        payload={
            "platform": "telegram",
            "external_user_id": "brandon",
            "external_chat_id": "private-chat",
            "display_label": "Brandon",
            "hermes_session_id": "session-2",
            "logical_conversation_id": backfill.logical_conversation_id,
            "events": [
                {
                    "source_event_key": "run:run-live:final_response",
                    "event_type": "assistant",
                    "role": "assistant",
                    "occurred_at": "2025-12-25T12:50:01+00:00",
                    "content": "The same reply can be correct twice.",
                    "metadata": {"run_completion": True},
                }
            ],
        },
    )

    connection = sqlite3.connect(state_path)
    first = connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, timestamp, platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        (
            "session-2",
            "assistant",
            "The same reply can be correct twice.",
            1766667001,
            None,
            0,
        ),
    )
    first_id = int(first.lastrowid)
    connection.commit()

    assert backfill.run_live_tail(page_size=10) == 0
    assert spool.get_record(f"tail:state:session-2:{first_id}:assistant") is None

    second = connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, timestamp, platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        (
            "session-2",
            "assistant",
            "The same reply can be correct twice.",
            1766667061,
            None,
            0,
        ),
    )
    second_id = int(second.lastrowid)
    connection.commit()
    connection.close()

    restarted = SydneyBackfill(
        state_db=state_path,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )
    assert restarted.run_live_tail(page_size=10) == 1
    recovered = spool.get_record(f"tail:state:session-2:{second_id}:assistant")
    assert recovered is not None
    assert recovered.payload["events"][0]["content"] == (
        "The same reply can be correct twice."
    )
