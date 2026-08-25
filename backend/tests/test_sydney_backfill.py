from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

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
            started_at REAL NOT NULL
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
        INSERT INTO sessions VALUES ('session-1', 'telegram', 'brandon', NULL, 1766664000);
        INSERT INTO sessions VALUES ('session-2', 'telegram', 'brandon', 'session-1', 1766665000);
        INSERT INTO sessions VALUES ('other-session', 'telegram', 'someone-else', NULL, 1766666000);
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
