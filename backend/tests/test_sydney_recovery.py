from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

OVERLAY = Path(__file__).resolve().parents[2] / "hermes" / "overlay"
sys.path.insert(0, str(OVERLAY))

import sydney_recovery
from sydney_backfill import SydneyBackfill
from sydney_recovery import RecoveryRejected, SydneyLegacyRecovery
from sydney_retry import AUTOMATIC_CONTINUATION_MESSAGE
from sydney_spool import SydneySpool

IDENTITY_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SELECTED_CONTENT = "Use current Command contacts and prepare a review packet."


@dataclass
class RecoveryFixture:
    recovery: SydneyLegacyRecovery
    backfill: SydneyBackfill
    spool: SydneySpool
    state_db: Path
    session_id: str
    message_id: int
    selected_content: str
    selected_sha256: str


def _seed_state(
    path: Path,
    *,
    role: str = "user",
    content: str = SELECTED_CONTENT,
    observed: int = 0,
) -> int:
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
            1787664000, NULL, NULL
        );
        """
    )
    cursor = connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, timestamp, platform_message_id, observed
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        ("session-1", role, content, 1787664001, "telegram-original", observed),
    )
    message_id = int(cursor.lastrowid)
    connection.commit()
    connection.close()

    sessions_directory = path.parent / "sessions"
    sessions_directory.mkdir()
    (sessions_directory / "sessions.json").write_text(
        json.dumps(
            {
                "agent:main:telegram:dm:private-chat": {
                    "session_id": "session-1",
                    "platform": "telegram",
                    "chat_type": "dm",
                    "origin": {
                        "platform": "telegram",
                        "chat_id": "private-chat",
                        "chat_type": "dm",
                        "user_id": "brandon",
                    },
                }
            }
        )
    )
    return message_id


def _ingest_receipt(batch: dict) -> dict:
    event_receipts = []
    for event in batch["events"]:
        event_receipts.append(
            {
                "event_id": str(uuid5(NAMESPACE_URL, event["source_event_key"])),
                "event_type": event["event_type"],
                "occurred_at": event["occurred_at"],
                "content_sha256": hashlib.sha256(event["content"].encode()).hexdigest(),
            }
        )
    return {"identity_id": IDENTITY_ID, "event_receipts": event_receipts}


def _make_recovery_fixture(
    tmp_path: Path,
    *,
    role: str = "user",
    content: str = SELECTED_CONTENT,
    observed: int = 0,
) -> RecoveryFixture:
    state_db = tmp_path / "state.db"
    message_id = _seed_state(
        state_db,
        role=role,
        content=content,
        observed=observed,
    )
    spool = SydneySpool(tmp_path / "sydney_spool.db")
    backfill = SydneyBackfill(
        state_db=state_db,
        spool=spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="private-chat",
        display_label="Brandon",
    )
    backfill.run()
    for record in spool.matching_records(state="pending", source_prefix="backfill:"):
        spool.acknowledge(record.id, _ingest_receipt(record.payload))
    return RecoveryFixture(
        recovery=SydneyLegacyRecovery(backfill=backfill, spool=spool),
        backfill=backfill,
        spool=spool,
        state_db=state_db,
        session_id="session-1",
        message_id=message_id,
        selected_content=content,
        selected_sha256=hashlib.sha256(content.encode()).hexdigest(),
    )


@pytest.fixture
def recovery_fixture(tmp_path: Path):
    fixture = _make_recovery_fixture(tmp_path)
    try:
        yield fixture
    finally:
        fixture.spool.close()


def test_review_only_recovery_dry_run_then_enqueues_once(
    recovery_fixture: RecoveryFixture,
) -> None:
    fixture = recovery_fixture
    before_changes = fixture.spool.connection.total_changes
    dry_run = fixture.recovery.admit(
        session_id=fixture.session_id,
        message_id=fixture.message_id,
        expected_content_sha256=fixture.selected_sha256,
        enqueue=False,
    )

    assert dry_run["eligible"] is True
    assert dry_run["enqueued"] is False
    assert dry_run["existing"] is False
    assert dry_run["recovery_policy"] == "review_only"
    assert fixture.spool.connection.total_changes == before_changes
    assert fixture.spool.find_inbound(dry_run["platform_message_id"]) is None
    assert fixture.selected_content not in json.dumps(dry_run)

    admitted = fixture.recovery.admit(
        session_id=fixture.session_id,
        message_id=fixture.message_id,
        expected_content_sha256=fixture.selected_sha256,
        enqueue=True,
    )
    replay = fixture.recovery.admit(
        session_id=fixture.session_id,
        message_id=fixture.message_id,
        expected_content_sha256=fixture.selected_sha256,
        enqueue=True,
    )

    record = fixture.spool.find_inbound(admitted["platform_message_id"])
    assert record is not None
    assert admitted["record_id"] == replay["record_id"] == record.id
    assert admitted["existing"] is False
    assert replay["existing"] is True
    assert record.payload["local_metadata"] == {"recovery_policy": "review_only"}
    event = record.payload["event_batch"]["events"][0]
    assert event["source_event_key"].endswith(f":{fixture.message_id}:user")
    canonical = fixture.spool.get_record(f"backfill:{event['source_event_key']}")
    assert canonical is not None
    assert event == canonical.payload["events"][0]


def test_recovery_rejects_wrong_hash_and_wrong_session(
    recovery_fixture: RecoveryFixture,
) -> None:
    fixture = recovery_fixture
    with pytest.raises(RecoveryRejected, match="hash"):
        fixture.recovery.admit(
            session_id=fixture.session_id,
            message_id=fixture.message_id,
            expected_content_sha256="0" * 64,
        )
    with pytest.raises(RecoveryRejected, match="selected session"):
        fixture.recovery.admit(
            session_id="other-session",
            message_id=fixture.message_id,
            expected_content_sha256=fixture.selected_sha256,
        )


def test_recovery_rejects_wrong_private_identity(
    recovery_fixture: RecoveryFixture,
) -> None:
    fixture = recovery_fixture
    wrong_identity = SydneyBackfill(
        state_db=fixture.state_db,
        spool=fixture.spool,
        platform="telegram",
        external_user_id="brandon",
        external_chat_id="wrong-chat",
        display_label="Brandon",
    )

    with pytest.raises(RecoveryRejected, match="identity"):
        SydneyLegacyRecovery(
            backfill=wrong_identity,
            spool=fixture.spool,
        ).admit(
            session_id=fixture.session_id,
            message_id=fixture.message_id,
            expected_content_sha256=fixture.selected_sha256,
        )


@pytest.mark.parametrize(
    ("role", "content", "observed"),
    (
        ("assistant", "Already answered.", 0),
        ("tool", '{"result":"done"}', 0),
        ("user", "[System continuation: resume saved work]", 0),
        ("user", "[Sydney canary: retry proof]", 0),
        ("user", AUTOMATIC_CONTINUATION_MESSAGE, 0),
        ("user", "Observed group message", 1),
    ),
)
def test_recovery_rejects_non_business_user_rows(
    tmp_path: Path,
    role: str,
    content: str,
    observed: int,
) -> None:
    fixture = _make_recovery_fixture(
        tmp_path,
        role=role,
        content=content,
        observed=observed,
    )
    try:
        with pytest.raises(RecoveryRejected):
            fixture.recovery.admit(
                session_id=fixture.session_id,
                message_id=fixture.message_id,
                expected_content_sha256=fixture.selected_sha256,
            )
    finally:
        fixture.spool.close()


def test_recovery_requires_reconciliation_and_exact_backfill_receipt(
    recovery_fixture: RecoveryFixture,
) -> None:
    fixture = recovery_fixture
    fixture.spool.connection.execute(
        "DELETE FROM reconciliation_state WHERE session_id=?",
        (fixture.session_id,),
    )
    with pytest.raises(RecoveryRejected, match="reconciled"):
        fixture.recovery.admit(
            session_id=fixture.session_id,
            message_id=fixture.message_id,
            expected_content_sha256=fixture.selected_sha256,
        )

    canonical_key = f"backfill:state:{fixture.session_id}:{fixture.message_id}:user"
    fixture.spool.connection.execute(
        "DELETE FROM outbox WHERE source_key=?",
        (canonical_key,),
    )
    fixture.spool.connection.execute(
        """
        INSERT INTO reconciliation_state(
            session_id, identity_id, event_count, ordered_hash, updated_at
        ) VALUES(?, ?, 1, ?, '2026-08-27T00:00:00+00:00')
        """,
        (fixture.session_id, IDENTITY_ID, "f" * 64),
    )
    with pytest.raises(RecoveryRejected, match="backfill receipt"):
        fixture.recovery.admit(
            session_id=fixture.session_id,
            message_id=fixture.message_id,
            expected_content_sha256=fixture.selected_sha256,
        )


def test_recovery_rejects_existing_terminal_run(
    recovery_fixture: RecoveryFixture,
) -> None:
    fixture = recovery_fixture
    admitted = fixture.recovery.admit(
        session_id=fixture.session_id,
        message_id=fixture.message_id,
        expected_content_sha256=fixture.selected_sha256,
        enqueue=True,
    )
    record = fixture.spool.find_inbound(admitted["platform_message_id"])
    assert record is not None
    fixture.spool.acknowledge(
        record.id,
        {
            "ingest": _ingest_receipt(record.payload["event_batch"]),
            "run": {"run": {"id": "recovery-run-1", "state": "running"}},
        },
    )
    fixture.spool.mark_run_terminal("recovery-run-1", state="succeeded")

    with pytest.raises(RecoveryRejected, match="terminal"):
        fixture.recovery.admit(
            session_id=fixture.session_id,
            message_id=fixture.message_id,
            expected_content_sha256=fixture.selected_sha256,
            enqueue=True,
        )


def _insert_later_assistant(
    fixture: RecoveryFixture,
    *,
    content: str,
    tool_calls: list[dict] | None = None,
) -> None:
    connection = sqlite3.connect(fixture.state_db)
    connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, tool_calls, timestamp, observed
        ) VALUES(?, 'assistant', ?, ?, ?, 0)
        """,
        (
            fixture.session_id,
            content,
            json.dumps(tool_calls) if tool_calls is not None else None,
            1787664002,
        ),
    )
    connection.commit()
    connection.close()


def test_recovery_rejects_later_final_assistant_before_next_user(
    recovery_fixture: RecoveryFixture,
) -> None:
    fixture = recovery_fixture
    _insert_later_assistant(fixture, content="Here is the completed answer.")

    with pytest.raises(RecoveryRejected, match="final assistant"):
        fixture.recovery.admit(
            session_id=fixture.session_id,
            message_id=fixture.message_id,
            expected_content_sha256=fixture.selected_sha256,
        )


def test_recovery_skips_synthetic_user_continuation_before_later_final_assistant(
    recovery_fixture: RecoveryFixture,
) -> None:
    fixture = recovery_fixture
    connection = sqlite3.connect(fixture.state_db)
    connection.execute(
        """
        INSERT INTO messages(
            session_id, role, content, timestamp, observed
        ) VALUES(?, 'user', ?, ?, 0)
        """,
        (fixture.session_id, AUTOMATIC_CONTINUATION_MESSAGE, 1787664002),
    )
    connection.commit()
    connection.close()
    _insert_later_assistant(
        fixture,
        content="Here is the completed answer after automatic continuation.",
    )

    with pytest.raises(RecoveryRejected, match="final assistant"):
        fixture.recovery.admit(
            session_id=fixture.session_id,
            message_id=fixture.message_id,
            expected_content_sha256=fixture.selected_sha256,
        )


def test_recovery_treats_an_empty_stored_tool_call_list_as_a_final_response(
    recovery_fixture: RecoveryFixture,
) -> None:
    fixture = recovery_fixture
    _insert_later_assistant(
        fixture,
        content="Here is the completed answer.",
        tool_calls=[],
    )

    with pytest.raises(RecoveryRejected, match="final assistant"):
        fixture.recovery.admit(
            session_id=fixture.session_id,
            message_id=fixture.message_id,
            expected_content_sha256=fixture.selected_sha256,
        )


def test_recovery_allows_an_unfinished_assistant_tool_call(
    recovery_fixture: RecoveryFixture,
) -> None:
    fixture = recovery_fixture
    _insert_later_assistant(
        fixture,
        content="I am checking the source.",
        tool_calls=[
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "drive_search", "arguments": "{}"},
            }
        ],
    )

    result = fixture.recovery.admit(
        session_id=fixture.session_id,
        message_id=fixture.message_id,
        expected_content_sha256=fixture.selected_sha256,
    )

    assert result["eligible"] is True
    assert result["enqueued"] is False


def _set_cli_arguments(
    monkeypatch: pytest.MonkeyPatch,
    fixture: RecoveryFixture,
    *,
    enqueue: bool = False,
) -> None:
    arguments = [
        "sydney_recovery",
        "--state-db",
        str(fixture.state_db),
        "--spool",
        str(fixture.spool.path),
        "--session-id",
        fixture.session_id,
        "--message-id",
        str(fixture.message_id),
        "--expected-content-sha256",
        fixture.selected_sha256,
    ]
    if enqueue:
        arguments.append("--enqueue")
    monkeypatch.setattr(sys, "argv", arguments)


def test_recovery_cli_defaults_to_dry_run_and_requires_explicit_enqueue(
    recovery_fixture: RecoveryFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = recovery_fixture
    monkeypatch.setenv("SYDNEY_DURABLE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID", "brandon")
    monkeypatch.setenv("SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID", "private-chat")
    monkeypatch.setenv("SYDNEY_DURABLE_CONTEXT_ALLOWED_USER_IDS", "brandon")
    monkeypatch.setenv("SYDNEY_DURABLE_CONTEXT_DISPLAY_LABEL", "Brandon")

    _set_cli_arguments(monkeypatch, fixture)
    sydney_recovery.main()
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["eligible"] is True
    assert dry_run["enqueued"] is False
    assert fixture.spool.find_inbound(dry_run["platform_message_id"]) is None
    assert fixture.selected_content not in json.dumps(dry_run)

    _set_cli_arguments(monkeypatch, fixture, enqueue=True)
    sydney_recovery.main()
    admitted = json.loads(capsys.readouterr().out)
    assert admitted["enqueued"] is True
    assert fixture.spool.find_inbound(admitted["platform_message_id"]) is not None


def test_recovery_cli_rejects_disabled_private_identity_before_opening_spool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SYDNEY_DURABLE_CONTEXT_ENABLED", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sydney_recovery",
            "--state-db",
            str(tmp_path / "missing-state.db"),
            "--spool",
            str(tmp_path / "must-not-exist.db"),
            "--session-id",
            "session-1",
            "--message-id",
            "1",
            "--expected-content-sha256",
            "0" * 64,
        ],
    )

    with pytest.raises(SystemExit, match="private identity"):
        sydney_recovery.main()

    assert not (tmp_path / "must-not-exist.db").exists()
