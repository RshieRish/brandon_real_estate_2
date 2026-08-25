"""Idempotently mirror visible Hermes ``state.db`` history into Sydney's spool."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import UUID, uuid5

try:
    from .sydney_spool import SydneySpool, redact_text
except ImportError:
    from sydney_spool import SydneySpool, redact_text


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
            "backfill_cursor:"
            + hashlib.sha256(str(self.state_db).encode()).hexdigest()
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.state_db}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}

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
                            "content": redact_text(str(function.get("arguments") or "{}")),
                            "tool_name": str(function.get("name") or "") or None,
                            "tool_call_id": tool_call_id,
                            "metadata": {
                                "state_message_id": int(row["id"]),
                                "backfill": True,
                            },
                        }
                    )
        return events

    def _batch(self, session: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "external_user_id": self.external_user_id,
            "external_chat_id": self.external_chat_id,
            "display_label": self.display_label,
            "hermes_session_id": str(session["id"]),
            "logical_conversation_id": self.logical_conversation_id,
            "parent_hermes_session_id": session.get("parent_session_id"),
            "continuation_reason": (
                "backfill_continuation" if session.get("parent_session_id") else "backfill_root"
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
            "session_count": len(sessions),
            "message_count": message_count,
            "role_counts": dict(sorted(role_counts.items())),
            "tool_call_count": tool_count,
            "ordered_hash": global_digest.hexdigest(),
            "sessions": [
                {
                    "session_id": session_id,
                    "ordered_hash": session_digests[session_id].hexdigest(),
                }
                for session_id in sessions
            ],
        }

    def run(self, *, page_size: int = 100, max_pages: int | None = None) -> dict[str, Any]:
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
                if not bool(row["observed"] if "observed" in row.keys() else 0)
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--display-label", default="Sydney user")
    args = parser.parse_args()
    spool = SydneySpool(args.spool)
    try:
        report = SydneyBackfill(
            state_db=args.state_db,
            spool=spool,
            platform=args.platform,
            external_user_id=args.user_id,
            external_chat_id=args.chat_id,
            display_label=args.display_label,
        ).run()
        print(json.dumps(report, sort_keys=True))
    finally:
        spool.close()


if __name__ == "__main__":
    main()
