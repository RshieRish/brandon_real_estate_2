"""Idempotently mirror visible Hermes ``state.db`` history into Sydney's spool."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

try:
    from .sydney_spool import (
        SpoolConflict,
        SydneySpool,
        ordered_reconciliation_hash,
        redact_text,
    )
except ImportError:
    from sydney_spool import (
        SpoolConflict,
        SydneySpool,
        ordered_reconciliation_hash,
        redact_text,
    )


_IDENTITY_NAMESPACE = UUID("23f42827-f36c-4d2d-b403-28bc21cbb52a")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iso_timestamp(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return datetime.now(timezone.utc).isoformat()


class SydneyBackfill:
    def __init__(
        self,
        *,
        state_db: str | Path,
        spool: SydneySpool,
        platform: str,
        external_user_id: str,
        external_chat_id: str,
        display_label: str,
    ) -> None:
        self.state_db = Path(state_db).expanduser().resolve()
        self.spool = spool
        self.platform = platform
        self.external_user_id = external_user_id
        self.external_chat_id = external_chat_id
        self.display_label = display_label[:128]
        stable_key = f"{platform}\x1f{external_user_id}\x1f{external_chat_id}"
        self.logical_conversation_id = str(uuid5(_IDENTITY_NAMESPACE, stable_key))
        self._cursor_key = (
            "backfill_cursor:" + hashlib.sha256(str(self.state_db).encode()).hexdigest()
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.state_db}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
        }

    def _sessions(self, connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        columns = self._columns(connection, "sessions")
        requested = [
            name
            for name in ("id", "source", "user_id", "parent_session_id", "started_at")
            if name in columns
        ]
        filters: list[str] = []
        parameters: list[str] = []
        if "source" in columns:
            filters.append("source = ?")
            parameters.append(self.platform)
        if "user_id" in columns:
            filters.append("user_id = ?")
            parameters.append(self.external_user_id)
        where = f" WHERE {' AND '.join(filters)}" if filters else ""
        rows = connection.execute(
            f"SELECT {', '.join(requested)} FROM sessions{where} "
            "ORDER BY started_at, id",
            parameters,
        ).fetchall()
        sessions = {str(row["id"]): dict(row) for row in rows}
        for session_id, session in sessions.items():
            self.spool.rotate_session(
                session_id=session_id,
                logical_conversation_id=self.logical_conversation_id,
                platform=self.platform,
                external_user_id=self.external_user_id,
                external_chat_id=self.external_chat_id,
                parent_session_id=session.get("parent_session_id"),
                continuation_reason=(
                    "backfill_continuation"
                    if session.get("parent_session_id")
                    else "backfill_root"
                ),
            )
        return sessions

    @staticmethod
    def _message_columns(connection: sqlite3.Connection) -> list[str]:
        available = SydneyBackfill._columns(connection, "messages")
        return [
            name
            for name in (
                "id",
                "session_id",
                "role",
                "content",
                "tool_call_id",
                "tool_calls",
                "tool_name",
                "timestamp",
                "platform_message_id",
                "observed",
            )
            if name in available
        ]

    def _events_for_message(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        if bool(row.get("observed", 0)):
            return []
        role = str(row.get("role") or "")
        if role not in {"user", "assistant", "tool"}:
            return []
        message_id = str(row["id"])
        session_id = str(row["session_id"])
        occurred_at = _iso_timestamp(row.get("timestamp"))
        platform_message_id = row.get("platform_message_id")
        base = f"state:{session_id}:{message_id}"
        events: list[dict[str, Any]] = []
        content = redact_text(str(row.get("content") or ""))
        if content:
            event_type = "tool_result" if role == "tool" else role
            events.append(
                {
                    "source_event_key": f"{base}:{event_type}",
                    "event_type": event_type,
                    "role": role,
                    "occurred_at": occurred_at,
                    "content": content,
                    "tool_name": row.get("tool_name"),
                    "tool_call_id": row.get("tool_call_id"),
                    "metadata": {
                        "state_message_id": int(row["id"]),
                        "platform_message_id": platform_message_id,
                        "backfill": True,
                    },
                }
            )
        if role == "assistant" and row.get("tool_calls"):
            try:
                tool_calls = json.loads(str(row["tool_calls"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                tool_calls = []
            if isinstance(tool_calls, list):
                for index, tool_call in enumerate(tool_calls):
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function") or {}
                    if not isinstance(function, dict):
                        function = {}
                    tool_call_id = str(tool_call.get("id") or f"{message_id}-{index}")
                    events.append(
                        {
                            "source_event_key": f"{base}:tool_call:{tool_call_id}",
                            "event_type": "tool_call",
                            "role": "assistant",
                            "occurred_at": occurred_at,
                            "content": redact_text(
                                str(function.get("arguments") or "{}")
                            ),
                            "tool_name": str(function.get("name") or "") or None,
                            "tool_call_id": tool_call_id,
                            "metadata": {
                                "state_message_id": int(row["id"]),
                                "backfill": True,
                            },
                        }
                    )
        return events

    def _batch(
        self, session: dict[str, Any], events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "external_user_id": self.external_user_id,
            "external_chat_id": self.external_chat_id,
            "display_label": self.display_label,
            "hermes_session_id": str(session["id"]),
            "logical_conversation_id": self.logical_conversation_id,
            "parent_hermes_session_id": session.get("parent_session_id"),
            "continuation_reason": (
                "backfill_continuation"
                if session.get("parent_session_id")
                else "backfill_root"
            ),
            "source_version": "hermes-state-backfill-v1",
            "events": events,
        }

    def _report(
        self,
        sessions: dict[str, dict[str, Any]],
        visible_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        role_counts: Counter[str] = Counter()
        tool_count = 0
        tool_result_count = 0
        event_count = 0
        event_session_ids: set[str] = set()
        global_digest = hashlib.sha256(b"sydney-backfill-v1\0")
        session_digests: dict[str, Any] = defaultdict(
            lambda: hashlib.sha256(b"sydney-backfill-session-v1\0")
        )
        message_count = 0
        for row in visible_rows:
            events = self._events_for_message(row)
            if not events:
                continue
            role = str(row.get("role") or "")
            role_counts[role] += 1
            message_count += 1
            tool_count += sum(event["event_type"] == "tool_call" for event in events)
            for event in events:
                event_count += 1
                event_session_ids.add(str(row["session_id"]))
                tool_result_count += event["event_type"] == "tool_result"
                descriptor = _canonical(
                    {
                        "source_event_key": event["source_event_key"],
                        "event_type": event["event_type"],
                        "content_sha256": hashlib.sha256(
                            event["content"].encode()
                        ).hexdigest(),
                    }
                ).encode()
                global_digest.update(descriptor)
                session_digests[str(row["session_id"])].update(descriptor)
        return {
            "schema_version": "sydney-backfill-v1",
            "session_count": len(event_session_ids),
            "message_count": message_count,
            "event_count": event_count,
            "role_counts": dict(sorted(role_counts.items())),
            "tool_call_count": tool_count,
            "tool_result_count": tool_result_count,
            "ordered_hash": global_digest.hexdigest(),
            "sessions": [
                {
                    "session_key_sha256": hashlib.sha256(
                        session_id.encode()
                    ).hexdigest(),
                    "ordered_hash": session_digests[session_id].hexdigest(),
                }
                for session_id in sorted(event_session_ids)
            ],
        }

    def run(
        self, *, page_size: int = 100, max_pages: int | None = None
    ) -> dict[str, Any]:
        bounded_page = max(1, min(int(page_size), 100))
        connection = self._connect()
        try:
            sessions = self._sessions(connection)
            columns = self._message_columns(connection)
            session_ids = tuple(sessions)
            if not session_ids:
                return self._report(sessions, [])
            session_placeholders = ", ".join("?" for _ in session_ids)
            session_filter = f"session_id IN ({session_placeholders})"
            all_rows = [
                dict(row)
                for row in connection.execute(
                    f"SELECT {', '.join(columns)} FROM messages "
                    f"WHERE {session_filter} ORDER BY id",
                    session_ids,
                ).fetchall()
                if "observed" not in row or not bool(row["observed"])
            ]
            cursor = int(self.spool.get_meta(self._cursor_key, 0) or 0)
            pages = 0
            while max_pages is None or pages < max_pages:
                rows = connection.execute(
                    f"SELECT {', '.join(columns)} FROM messages "
                    f"WHERE {session_filter} AND id > ? ORDER BY id LIMIT ?",
                    (*session_ids, cursor, bounded_page),
                ).fetchall()
                if not rows:
                    break
                for raw in rows:
                    row = dict(raw)
                    events = self._events_for_message(row)
                    session = sessions.get(str(row["session_id"]))
                    if events and session is not None:
                        for event in events:
                            self.spool.enqueue(
                                kind="event_batch",
                                source_key=f"backfill:{event['source_event_key']}",
                                payload=self._batch(session, [event]),
                            )
                    cursor = int(row["id"])
                    self.spool.set_meta(self._cursor_key, cursor)
                pages += 1
            return self._report(sessions, all_rows)
        finally:
            connection.close()

    @staticmethod
    def _batch_and_receipt(record: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        batch = record.payload
        receipt = record.receipt or {}
        if record.kind != "event_batch" or not isinstance(batch, dict):
            raise RuntimeError("backfill spool record has an invalid kind")
        if not isinstance(receipt, dict):
            raise TypeError("backfill spool receipt is missing")
        return batch, receipt

    def _drain_backfill(self, backend: Any, *, wait_seconds: float) -> int:
        deadline = time.monotonic() + max(0.0, min(float(wait_seconds), 300.0))
        while True:
            pending = self.spool.matching_records(
                state="pending",
                source_prefix="backfill:",
                limit=100,
            )
            if not pending:
                return 0
            made_progress = False
            for record in pending:
                try:
                    receipt = backend.ingest_events(record.payload)
                    self.spool.acknowledge(record.id, receipt)
                    made_progress = True
                except SpoolConflict:
                    current = self.spool.get_record(record.source_key)
                    if current is None or current.state != "acknowledged":
                        raise
                    made_progress = True
                except Exception:  # noqa: BLE001 - bounded external delivery.
                    self.spool.record_failure(record.id)
                    break
            remaining = self.spool.matching_count(
                state="pending", source_prefix="backfill:"
            )
            if remaining == 0:
                return 0
            if time.monotonic() >= deadline:
                return remaining
            if not made_progress:
                time.sleep(0.25)

    def _acknowledgement_report(
        self,
        backend: Any,
        *,
        source: dict[str, Any],
        unacknowledged_count: int,
    ) -> dict[str, Any]:
        records = self.spool.matching_records(
            state="acknowledged",
            source_prefix="backfill:",
        )
        global_digest = hashlib.sha256(b"sydney-backfill-v1\0")
        session_digests: dict[str, Any] = defaultdict(
            lambda: hashlib.sha256(b"sydney-backfill-session-v1\0")
        )
        canonical_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        identities: dict[str, str] = {}
        seen_messages: dict[tuple[str, str], str] = {}
        role_counts: Counter[str] = Counter()
        tool_call_count = 0
        tool_result_count = 0
        event_count = 0

        for record in records:
            batch, receipt = self._batch_and_receipt(record)
            session_id = str(batch.get("hermes_session_id") or "")
            if not session_id:
                raise RuntimeError("backfill session receipt is incomplete")
            identity_id = str(receipt.get("identity_id") or "")
            event_receipts = receipt.get("event_receipts")
            events = batch.get("events")
            if (
                not identity_id
                or not isinstance(events, list)
                or not isinstance(event_receipts, list)
                or len(events) != len(event_receipts)
            ):
                raise RuntimeError("backfill ingest receipt is incomplete")
            previous_identity = identities.setdefault(session_id, identity_id)
            if previous_identity != identity_id:
                raise RuntimeError("backfill session identity changed")
            for event, event_receipt in zip(events, event_receipts, strict=True):
                if not isinstance(event, dict) or not isinstance(event_receipt, dict):
                    raise TypeError("backfill event receipt is invalid")
                descriptor = _canonical(
                    {
                        "source_event_key": event["source_event_key"],
                        "event_type": event["event_type"],
                        "content_sha256": hashlib.sha256(
                            str(event.get("content") or "").encode()
                        ).hexdigest(),
                    }
                ).encode()
                global_digest.update(descriptor)
                session_digests[session_id].update(descriptor)
                canonical_rows[session_id].append(event_receipt)
                event_count += 1
                if event.get("event_type") == "tool_call":
                    tool_call_count += 1
                if event.get("event_type") == "tool_result":
                    tool_result_count += 1
                metadata = event.get("metadata") or {}
                message_id = metadata.get("state_message_id")
                role = str(event.get("role") or "")
                if message_id is not None and role:
                    seen_messages[(session_id, str(message_id))] = role

        role_counts.update(seen_messages.values())
        source_sessions = {
            str(row["session_key_sha256"]): str(row["ordered_hash"])
            for row in source.get("sessions", [])
        }
        sessions: list[dict[str, Any]] = []
        all_backend_matched = True
        all_source_sessions_matched = True
        for session_id in sorted(canonical_rows):
            session_key = hashlib.sha256(session_id.encode()).hexdigest()
            expected_hash = ordered_reconciliation_hash(canonical_rows[session_id])
            response = backend.reconcile_session(
                {
                    "identity_id": identities[session_id],
                    "hermes_session_id": session_id,
                    "expected_event_count": len(canonical_rows[session_id]),
                    "expected_ordered_hash": expected_hash,
                }
            )
            matched = bool(response.get("matched")) and (
                int(response.get("event_count", -1)) == len(canonical_rows[session_id])
                and str(response.get("ordered_hash") or "") == expected_hash
            )
            source_hash = source_sessions.get(session_key)
            acknowledged_hash = session_digests[session_id].hexdigest()
            source_session_matched = source_hash == acknowledged_hash
            all_backend_matched = all_backend_matched and matched
            all_source_sessions_matched = (
                all_source_sessions_matched and source_session_matched
            )
            if matched:
                self.spool.set_reconciliation_cursor(
                    session_id,
                    len(canonical_rows[session_id]),
                    expected_hash,
                )
            sessions.append(
                {
                    "session_key_sha256": session_key,
                    "source_ordered_hash": source_hash,
                    "acknowledged_ordered_hash": acknowledged_hash,
                    "canonical_event_count": len(canonical_rows[session_id]),
                    "canonical_ordered_hash": expected_hash,
                    "matched": matched and source_session_matched,
                }
            )

        acknowledged = {
            "session_count": len(canonical_rows),
            "message_count": len(seen_messages),
            "event_count": event_count,
            "role_counts": dict(sorted(role_counts.items())),
            "tool_call_count": tool_call_count,
            "tool_result_count": tool_result_count,
            "ordered_hash": global_digest.hexdigest(),
        }
        summary_matched = (
            unacknowledged_count == 0
            and int(source.get("session_count", -1))
            == acknowledged["session_count"]
            and int(source.get("message_count", -1)) == acknowledged["message_count"]
            and int(source.get("event_count", -1)) == acknowledged["event_count"]
            and source.get("role_counts") == acknowledged["role_counts"]
            and int(source.get("tool_call_count", -1))
            == acknowledged["tool_call_count"]
            and int(source.get("tool_result_count", -1))
            == acknowledged["tool_result_count"]
            and source.get("ordered_hash") == acknowledged["ordered_hash"]
            and len(source_sessions) == len(sessions)
            and all_backend_matched
            and all_source_sessions_matched
        )
        return {
            "schema_version": "sydney-backfill-reconciliation-v1",
            "matched": summary_matched,
            "unacknowledged_count": unacknowledged_count,
            "source": source,
            "acknowledged": acknowledged,
            "sessions": sessions,
        }

    def drain_and_reconcile(
        self,
        backend: Any,
        *,
        wait_seconds: float = 60.0,
    ) -> dict[str, Any]:
        source = self.run()
        remaining = self._drain_backfill(backend, wait_seconds=wait_seconds)
        return self._acknowledgement_report(
            backend,
            source=source,
            unacknowledged_count=remaining,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--display-label", default="Sydney user")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Drain this backfill and verify exact backend counts and hashes.",
    )
    parser.add_argument("--wait-seconds", type=float, default=60.0)
    args = parser.parse_args()
    spool = SydneySpool(args.spool)
    try:
        backfill = SydneyBackfill(
            state_db=args.state_db,
            spool=spool,
            platform=args.platform,
            external_user_id=args.user_id,
            external_chat_id=args.chat_id,
            display_label=args.display_label,
        )
        if args.reconcile:
            try:
                from .sydney_memory_provider import SydneyBackendClient
            except ImportError:
                from sydney_memory_provider import SydneyBackendClient

            backend_url = (
                os.environ.get("BACKEND_API_URL")
                or os.environ.get("BRANDON_BACKEND_URL")
                or ""
            )
            token = (
                os.environ.get("AGENT_CONTROL_TOKEN")
                or os.environ.get("BRANDON_AGENT_CONTROL_TOKEN")
                or ""
            )
            if not backend_url or not token:
                raise SystemExit("backend URL and agent-control token are required")
            report = backfill.drain_and_reconcile(
                SydneyBackendClient(backend_url, token),
                wait_seconds=args.wait_seconds,
            )
        else:
            report = backfill.run()
        print(json.dumps(report, sort_keys=True))
        if args.reconcile and not report.get("matched"):
            raise SystemExit(1)
    finally:
        spool.close()


if __name__ == "__main__":
    main()
