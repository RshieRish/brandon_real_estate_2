"""Crash-safe local write-ahead spool for Sydney durable context.

This module intentionally uses only the Python standard library because it is
copied into the pinned Hermes runtime image.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCHEMA_VERSION = 1
_SECRET_KEY = re.compile(
    r"(?:^|_)(?:authorization|access_token|refresh_token|id_token|oauth_token|"
    r"password|passwd|api_key|client_secret|cookie|set_cookie|bearer_token|"
    r"handoff)(?:$|_)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)(\b(?:authorization\s*:\s*)?bearer\s+)[^\s,;]+")
_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passwd|access[_-]?token|refresh[_-]?token|api[_-]?key|"
    r"client[_-]?secret|oauth[_-]?token)\s*[:=]\s*)([^\s,;&]+)"
)
_KNOWN_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b")
_URL = re.compile(r"https?://[^\s<>\"']+")
_URL_SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "api_key",
    "apikey",
    "key",
    "password",
    "client_secret",
}


class SpoolConflict(RuntimeError):
    """A replay reused a source key with different redacted content."""


@dataclass(frozen=True, slots=True)
class SpoolRecord:
    id: int
    kind: str
    source_key: str
    payload: dict[str, Any]
    state: str
    attempt_count: int
    created_at: str
    last_attempt_at: str | None
    acknowledged_at: str | None
    receipt: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class DrainResult:
    attempted: int
    acknowledged: int
    failed: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    try:
        parts = urlsplit(raw)
        query = [
            (
                key,
                "[REDACTED_OAUTH_TOKEN]" if key.lower() in _URL_SECRET_KEYS else value,
            )
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
        fragment = parts.fragment
        if fragment.lower().startswith("handoff="):
            fragment = "handoff=[REDACTED_SIGNED_FRAGMENT]"
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), fragment)
        )
    except (TypeError, ValueError):
        return "[REDACTED_URL_WITH_SECRET]"


def redact_text(value: str) -> str:
    """Irreversibly remove common credential forms without logging matches."""
    redacted = _URL.sub(_redact_url, value)
    redacted = _BEARER.sub(r"\1[REDACTED_BEARER_TOKEN]", redacted)
    redacted = _ASSIGNMENT.sub(r"\1[REDACTED_SECRET]", redacted)
    redacted = _KNOWN_TOKEN.sub("[REDACTED_TOKEN]", redacted)
    redacted = re.sub(
        r"(?i)(#handoff=)[^\s&#]+",
        r"\1[REDACTED_SIGNED_FRAGMENT]",
        redacted,
    )
    return redacted


def redact_payload(value: Any, *, key: str = "") -> Any:
    """Return a JSON-safe, recursively redacted copy of ``value``."""
    if key and _SECRET_KEY.search(key):
        return "[REDACTED_SECRET]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            str(item_key): redact_payload(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_payload(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


class SydneySpool:
    """A private SQLite WAL queue whose acknowledgements are backend receipts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            check_same_thread=False,
            timeout=5.0,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self._migrate()
        os.chmod(self.path, 0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.path}{suffix}")
            if sidecar.exists():
                os.chmod(sidecar, 0o600)

    def _migrate(self) -> None:
        with self._lock:
            try:
                self.connection.executescript(
                    """
                    BEGIN EXCLUSIVE;
                    CREATE TABLE IF NOT EXISTS spool_meta (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS session_lineage (
                        session_id TEXT PRIMARY KEY,
                        logical_conversation_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        external_user_id TEXT NOT NULL,
                        external_chat_id TEXT NOT NULL,
                        parent_session_id TEXT,
                        continuation_reason TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS outbox (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        kind TEXT NOT NULL,
                        source_key TEXT NOT NULL UNIQUE,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        state TEXT NOT NULL DEFAULT 'pending'
                            CHECK (state IN ('pending', 'acknowledged')),
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        last_attempt_at TEXT,
                        acknowledged_at TEXT,
                        receipt_json TEXT
                    );
                    CREATE INDEX IF NOT EXISTS ix_sydney_spool_pending
                        ON outbox (state, id);
                    CREATE TABLE IF NOT EXISTS context_cache (
                        session_id TEXT PRIMARY KEY,
                        packet_json TEXT NOT NULL,
                        fetched_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS reconciliation_cursor (
                        session_id TEXT PRIMARY KEY,
                        event_count INTEGER NOT NULL,
                        ordered_hash TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT OR IGNORE INTO spool_meta(key, value_json, updated_at)
                        VALUES('schema_version', '1', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
                    COMMIT;
                    """
                )
                existing = self.connection.execute(
                    "SELECT value_json FROM spool_meta WHERE key='schema_version'"
                ).fetchone()
                if existing is None or json.loads(existing[0]) != SCHEMA_VERSION:
                    raise RuntimeError("unsupported Sydney spool schema version")
            except Exception:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    @property
    def schema_version(self) -> int:
        return int(self.get_meta("schema_version"))

    @property
    def pending_count(self) -> int:
        row = self.connection.execute(
            "SELECT count(*) FROM outbox WHERE state='pending'"
        ).fetchone()
        return int(row[0])

    def pragma(self, name: str) -> Any:
        if name not in {"journal_mode", "synchronous", "foreign_keys", "busy_timeout"}:
            raise ValueError("unsupported pragma")
        return self.connection.execute(f"PRAGMA {name}").fetchone()[0]

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.connection.execute(
            "SELECT value_json FROM spool_meta WHERE key=?", (key,)
        ).fetchone()
        return default if row is None else json.loads(row[0])

    def meta_items(self, prefix: str = "") -> dict[str, Any]:
        rows = self.connection.execute(
            "SELECT key, value_json FROM spool_meta WHERE key LIKE ? ORDER BY key",
            (f"{prefix}%",),
        ).fetchall()
        return {str(row["key"]): json.loads(row["value_json"]) for row in rows}

    def set_meta(self, key: str, value: Any) -> None:
        safe = redact_payload(value, key=key)
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO spool_meta(key, value_json, updated_at) VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (key, _canonical_json(safe), _utc_now()),
            )

    def enqueue(
        self,
        *,
        kind: str,
        source_key: str,
        payload: dict[str, Any],
    ) -> int:
        safe_payload = redact_payload(payload)
        encoded = _canonical_json(safe_payload)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self._lock, self.connection:
            existing = self.connection.execute(
                "SELECT id, kind, payload_sha256 FROM outbox WHERE source_key=?",
                (source_key,),
            ).fetchone()
            if existing is not None:
                if existing["kind"] != kind or existing["payload_sha256"] != digest:
                    raise SpoolConflict(
                        "source key replay does not match stored payload"
                    )
                return int(existing["id"])
            cursor = self.connection.execute(
                """
                INSERT INTO outbox(kind, source_key, payload_json, payload_sha256, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (kind, source_key, encoded, digest, _utc_now()),
            )
            return int(cursor.lastrowid)

    def enqueue_inbound(
        self,
        event_batch: dict[str, Any],
        run_start: dict[str, Any],
        *,
        source_key: str,
    ) -> int:
        return self.enqueue(
            kind="inbound_bundle",
            source_key=source_key,
            payload={"event_batch": event_batch, "run_start": run_start},
        )

    def enqueue_tool_before(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        side_effect_class: str,
        caller_idempotency_key: str | None = None,
    ) -> int:
        payload = {
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "side_effect_class": side_effect_class,
            "caller_idempotency_key": caller_idempotency_key,
        }
        return self.enqueue(
            kind="tool_before",
            source_key=f"tool:{run_id}:{tool_call_id}:before",
            payload=payload,
        )

    def enqueue_tool_after(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        state: str,
        result_event_id: str | None = None,
    ) -> int:
        return self.enqueue(
            kind="tool_after",
            source_key=f"tool:{run_id}:{tool_call_id}:after:{state}",
            payload={
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "state": state,
                "result_event_id": result_event_id,
            },
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> SpoolRecord:
        return SpoolRecord(
            id=int(row["id"]),
            kind=str(row["kind"]),
            source_key=str(row["source_key"]),
            payload=json.loads(row["payload_json"]),
            state=str(row["state"]),
            attempt_count=int(row["attempt_count"]),
            created_at=str(row["created_at"]),
            last_attempt_at=row["last_attempt_at"],
            acknowledged_at=row["acknowledged_at"],
            receipt=json.loads(row["receipt_json"]) if row["receipt_json"] else None,
        )

    def pending(self, *, limit: int = 100) -> list[SpoolRecord]:
        bounded = max(1, min(int(limit), 100))
        rows = self.connection.execute(
            "SELECT * FROM outbox WHERE state='pending' ORDER BY id LIMIT ?",
            (bounded,),
        ).fetchall()
        return [self._record(row) for row in rows]

    def get_record(self, source_key: str) -> SpoolRecord | None:
        row = self.connection.execute(
            "SELECT * FROM outbox WHERE source_key=?", (source_key,)
        ).fetchone()
        return None if row is None else self._record(row)

    def find_inbound(self, platform_message_id: str) -> SpoolRecord | None:
        rows = self.connection.execute(
            "SELECT * FROM outbox WHERE kind='inbound_bundle' ORDER BY id DESC"
        ).fetchall()
        for row in rows:
            record = self._record(row)
            if str(record.payload.get("run_start", {}).get("platform_message_id")) == str(
                platform_message_id
            ):
                return record
        return None

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM session_lineage ORDER BY created_at, session_id"
        ).fetchall()
        return [dict(row) for row in rows]

    def acknowledge(self, record_id: int, receipt: dict[str, Any]) -> None:
        encoded = _canonical_json(redact_payload(receipt))
        with self._lock, self.connection:
            cursor = self.connection.execute(
                """
                UPDATE outbox SET state='acknowledged', acknowledged_at=?, receipt_json=?
                WHERE id=? AND state='pending'
                """,
                (_utc_now(), encoded, record_id),
            )
            if cursor.rowcount != 1:
                raise SpoolConflict("outbox record was already acknowledged")

    def record_failure(self, record_id: int) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                UPDATE outbox SET attempt_count=attempt_count + 1, last_attempt_at=?
                WHERE id=? AND state='pending'
                """,
                (_utc_now(), record_id),
            )

    def drain(
        self,
        handler: Callable[[SpoolRecord], dict[str, Any]],
        *,
        limit: int = 100,
    ) -> DrainResult:
        attempted = acknowledged = failed = 0
        for record in self.pending(limit=limit):
            attempted += 1
            try:
                receipt = handler(record)
                if not isinstance(receipt, dict):
                    raise TypeError("spool delivery must return a receipt object")
                self.acknowledge(record.id, receipt)
                acknowledged += 1
            except Exception:  # noqa: BLE001 - delivery callbacks are external code.
                self.record_failure(record.id)
                failed += 1
                break
        return DrainResult(attempted, acknowledged, failed)

    def rotate_session(
        self,
        *,
        session_id: str,
        logical_conversation_id: str,
        platform: str,
        external_user_id: str,
        external_chat_id: str,
        parent_session_id: str | None = None,
        continuation_reason: str | None = None,
    ) -> None:
        with self._lock, self.connection:
            existing = self.connection.execute(
                "SELECT * FROM session_lineage WHERE session_id=?", (session_id,)
            ).fetchone()
            values = (
                session_id,
                logical_conversation_id,
                platform,
                external_user_id,
                external_chat_id,
                parent_session_id,
                continuation_reason,
            )
            if existing is not None:
                stored = tuple(
                    existing[key]
                    for key in (
                        "session_id",
                        "logical_conversation_id",
                        "platform",
                        "external_user_id",
                        "external_chat_id",
                        "parent_session_id",
                        "continuation_reason",
                    )
                )
                if stored != values:
                    raise SpoolConflict("session lineage replay does not match")
                return
            self.connection.execute(
                """
                INSERT INTO session_lineage(
                    session_id, logical_conversation_id, platform,
                    external_user_id, external_chat_id, parent_session_id,
                    continuation_reason, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*values, _utc_now()),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM session_lineage WHERE session_id=?", (session_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def cache_context(self, session_id: str, packet: dict[str, Any]) -> None:
        safe = redact_payload(packet)
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO context_cache(session_id, packet_json, fetched_at)
                VALUES(?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    packet_json=excluded.packet_json, fetched_at=excluded.fetched_at
                """,
                (session_id, _canonical_json(safe), _utc_now()),
            )

    def get_cached_context(self, session_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT packet_json FROM context_cache WHERE session_id=?", (session_id,)
        ).fetchone()
        return None if row is None else json.loads(row[0])

    def get_latest_cached_context(self) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT packet_json FROM context_cache ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        return None if row is None else json.loads(row[0])

    def set_reconciliation_cursor(
        self, session_id: str, event_count: int, ordered_hash: str
    ) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO reconciliation_cursor(session_id, event_count, ordered_hash, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    event_count=excluded.event_count,
                    ordered_hash=excluded.ordered_hash,
                    updated_at=excluded.updated_at
                """,
                (session_id, int(event_count), ordered_hash, _utc_now()),
            )

    def get_reconciliation_cursor(self, session_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT event_count, ordered_hash FROM reconciliation_cursor WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return (
            None
            if row is None
            else {
                "event_count": int(row["event_count"]),
                "ordered_hash": row["ordered_hash"],
            }
        )

    def close(self) -> None:
        with self._lock:
            self.connection.close()
