"""Idempotently mirror visible Hermes ``state.db`` history into Sydney's spool."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

try:
    from .sydney_spool import (
        SydneySpool,
        ordered_reconciliation_hash,
        redact_text,
    )
except ImportError:
    from sydney_spool import (
        SydneySpool,
        ordered_reconciliation_hash,
        redact_text,
    )


_IDENTITY_NAMESPACE = UUID("23f42827-f36c-4d2d-b403-28bc21cbb52a")
_HERMES_STRUCTURED_CONTENT_PREFIX = "\x00json:"
_CONTINUATION_MARKER_PREFIX = "[System continuation:"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iso_timestamp(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return datetime.now(timezone.utc).isoformat()


def _structured_visible_parts(value: Any) -> list[str]:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(_structured_visible_parts(item))
        return parts
    if not isinstance(value, dict):
        return []
    kind = str(value.get("type") or "")
    if kind in {"text", "input_text", "output_text"}:
        text = value.get("text")
        return [str(text)] if isinstance(text, str) and text else []
    if kind in {"image_url", "file_url", "input_file", "attachment"}:
        reference: Any = value.get(kind) or value.get("url") or value.get("file_url")
        if isinstance(reference, dict):
            reference = reference.get("url") or reference.get("file_id")
        rendered = str(reference or "").replace("\x00", "")
        if rendered.startswith("data:"):
            rendered = "embedded"
        return [
            f"[attachment:{kind} {rendered}]" if rendered else f"[attachment:{kind}]"
        ]
    parts = []
    for item in value.values():
        if isinstance(item, (dict, list)):
            parts.extend(_structured_visible_parts(item))
    return parts


def _visible_stored_content(value: Any) -> str:
    raw = "" if value is None else str(value)
    if not raw.startswith(_HERMES_STRUCTURED_CONTENT_PREFIX):
        return raw.replace("\x00", "")
    try:
        decoded = json.loads(raw[len(_HERMES_STRUCTURED_CONTENT_PREFIX) :])
    except (TypeError, ValueError, json.JSONDecodeError):
        return "[unsupported structured content]"
    parts = _structured_visible_parts(decoded)
    return "\n".join(part for part in parts if part).replace("\x00", "")


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
        sessions_index: str | Path | None = None,
    ) -> None:
        self.state_db = Path(state_db).expanduser().resolve()
        self.sessions_index = (
            Path(sessions_index).expanduser().resolve()
            if sessions_index is not None
            else self.state_db.parent / "sessions" / "sessions.json"
        )
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
        self._cutover_key = (
            "backfill_cutover:"
            + hashlib.sha256(str(self.state_db).encode()).hexdigest()
        )
        self._live_cursor_key = (
            "live_tail_cursor:"
            + hashlib.sha256(str(self.state_db).encode()).hexdigest()
        )
        proof_scope = f"{self.state_db}\x1f{stable_key}"
        self._reconciliation_proof_key = (
            "backfill_reconciliation_proof:"
            + hashlib.sha256(proof_scope.encode()).hexdigest()
        )
        self._source_report_key = (
            "backfill_source_report:" + hashlib.sha256(proof_scope.encode()).hexdigest()
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
        # Identity selection must fail closed. A platform-only scan could merge
        # another Telegram user's private history into Brandon's durable store.
        if not {"id", "source", "user_id"}.issubset(columns):
            return {}
        requested = [
            name
            for name in (
                "id",
                "source",
                "user_id",
                "parent_session_id",
                "started_at",
                "ended_at",
                "end_reason",
            )
            if name in columns
        ]
        rows = connection.execute(
            f"SELECT {', '.join(requested)} FROM sessions WHERE source = ?",
            (self.platform,),
        )
        candidates = {str(row["id"]): dict(row) for row in rows}
        exact_ids = self._exact_chat_session_ids()
        selected_ids = {
            session_id
            for session_id in exact_ids
            if session_id in candidates
            and candidates[session_id].get("user_id") in {None, self.external_user_id}
        }
        expected_identity = (
            self.logical_conversation_id,
            self.platform,
            self.external_user_id,
            self.external_chat_id,
        )
        for session_id in candidates:
            existing = self.spool.get_session(session_id)
            if existing is None:
                continue
            stored_identity = tuple(
                str(existing.get(key) or "")
                for key in (
                    "logical_conversation_id",
                    "platform",
                    "external_user_id",
                    "external_chat_id",
                )
            )
            if stored_identity == expected_identity:
                selected_ids.add(session_id)
        if not selected_ids:
            matching_history = connection.execute(
                "SELECT 1 FROM messages AS message "
                "JOIN sessions AS session ON session.id = message.session_id "
                "WHERE session.source = ? AND session.user_id = ? LIMIT 1",
                (self.platform, self.external_user_id),
            ).fetchone()
            if matching_history is not None:
                raise RuntimeError(
                    "exact chat session mapping is unavailable; refusing broad backfill"
                )
            return {}

        if {
            "parent_session_id",
            "started_at",
            "ended_at",
            "end_reason",
        }.issubset(columns):

            def is_compression_continuation(
                parent: dict[str, Any], child: dict[str, Any]
            ) -> bool:
                try:
                    parent_ended_at = float(parent.get("ended_at"))
                    child_started_at = float(child.get("started_at"))
                except (TypeError, ValueError):
                    return False
                return (
                    str(parent.get("end_reason") or "") == "compression"
                    and parent_ended_at <= child_started_at
                )

            changed = True
            while changed:
                changed = False
                for session_id, session in candidates.items():
                    if session.get("user_id") not in {None, self.external_user_id}:
                        continue
                    parent_id = session.get("parent_session_id")
                    if (
                        session_id in selected_ids
                        and parent_id in candidates
                        and candidates[str(parent_id)].get("user_id")
                        in {None, self.external_user_id}
                        and is_compression_continuation(
                            candidates[str(parent_id)], session
                        )
                        and parent_id not in selected_ids
                    ):
                        selected_ids.add(str(parent_id))
                        changed = True
                    if (
                        parent_id in selected_ids
                        and session_id not in selected_ids
                        and is_compression_continuation(
                            candidates[str(parent_id)], session
                        )
                    ):
                        selected_ids.add(session_id)
                        changed = True

        routed_ids = self._routed_session_ids_for_user()
        unmapped_same_user_ids = {
            session_id
            for session_id, session in candidates.items()
            if session.get("user_id") == self.external_user_id
            and session_id not in selected_ids
            and session_id not in routed_ids
        }
        if unmapped_same_user_ids:
            placeholders = ", ".join("?" for _ in unmapped_same_user_ids)
            unmapped_history = connection.execute(
                f"SELECT 1 FROM messages WHERE session_id IN ({placeholders}) LIMIT 1",
                tuple(sorted(unmapped_same_user_ids)),
            ).fetchone()
            if unmapped_history is not None:
                raise RuntimeError(
                    "unmapped same-user session history prevents exact backfill"
                )

        sessions = {
            session_id: {
                **candidates[session_id],
                "parent_session_id": (
                    candidates[session_id].get("parent_session_id")
                    if candidates[session_id].get("parent_session_id") in selected_ids
                    else None
                ),
            }
            for session_id in sorted(
                selected_ids,
                key=lambda value: (
                    candidates[value].get("started_at") or 0,
                    value,
                ),
            )
        }
        for session_id, session in sessions.items():
            existing = self.spool.get_session(session_id)
            if existing is not None:
                expected_identity = (
                    self.logical_conversation_id,
                    self.platform,
                    self.external_user_id,
                    self.external_chat_id,
                )
                stored_identity = tuple(
                    str(existing.get(key) or "")
                    for key in (
                        "logical_conversation_id",
                        "platform",
                        "external_user_id",
                        "external_chat_id",
                    )
                )
                if stored_identity != expected_identity:
                    raise RuntimeError(
                        "existing Sydney session lineage belongs to another identity"
                    )
                session["parent_session_id"] = existing.get("parent_session_id")
                session["continuation_reason"] = existing.get("continuation_reason")
                session["preserve_existing_lineage"] = True
            else:
                session["continuation_reason"] = (
                    "backfill_continuation"
                    if session.get("parent_session_id")
                    else "backfill_root"
                )
            self.spool.rotate_session(
                session_id=session_id,
                logical_conversation_id=self.logical_conversation_id,
                platform=self.platform,
                external_user_id=self.external_user_id,
                external_chat_id=self.external_chat_id,
                parent_session_id=session.get("parent_session_id"),
                continuation_reason=session.get("continuation_reason"),
            )
        return sessions

    def _exact_chat_session_ids(self) -> set[str]:
        """Resolve only session IDs proven to belong to the configured private chat."""
        try:
            payload = json.loads(self.sessions_index.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        if not isinstance(payload, dict):
            return set()
        result: set[str] = set()
        for entry in payload.values():
            if not isinstance(entry, dict):
                continue
            origin = entry.get("origin")
            if not isinstance(origin, dict):
                continue
            platform = str(origin.get("platform") or entry.get("platform") or "")
            chat_id = str(origin.get("chat_id") or "")
            user_ids = {
                str(origin.get("user_id") or ""),
                str(origin.get("user_id_alt") or ""),
            }
            chat_type = str(origin.get("chat_type") or entry.get("chat_type") or "")
            session_id = str(entry.get("session_id") or "")
            if (
                platform == self.platform
                and chat_id == self.external_chat_id
                and self.external_user_id in user_ids
                and chat_type == "dm"
                and session_id
            ):
                result.add(session_id)
        return result

    def _routed_session_ids_for_user(self) -> set[str]:
        """Return sessions whose routing index proves a chat for this user."""
        try:
            payload = json.loads(self.sessions_index.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        if not isinstance(payload, dict):
            return set()
        result: set[str] = set()
        for entry in payload.values():
            if not isinstance(entry, dict):
                continue
            origin = entry.get("origin")
            if not isinstance(origin, dict):
                continue
            platform = str(origin.get("platform") or entry.get("platform") or "")
            chat_id = str(origin.get("chat_id") or "")
            user_ids = {
                str(origin.get("user_id") or ""),
                str(origin.get("user_id_alt") or ""),
            }
            session_id = str(entry.get("session_id") or "")
            if (
                platform == self.platform
                and chat_id
                and self.external_user_id in user_ids
                and session_id
            ):
                result.add(session_id)
        return result

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
        content = redact_text(_visible_stored_content(row.get("content")))
        if content:
            is_continuation = role == "user" and content.startswith(
                _CONTINUATION_MARKER_PREFIX
            )
            event_type = (
                "continuation"
                if is_continuation
                else ("tool_result" if role == "tool" else role)
            )
            events.append(
                {
                    "source_event_key": f"{base}:{event_type}",
                    "event_type": event_type,
                    "role": "system" if is_continuation else role,
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

    def _known_canonical_or_staged_sessions(self) -> set[str]:
        """Return sessions that exist remotely or precede later FIFO batches."""
        known = set(self.spool.reconciliation_expectations())
        for state in ("pending", "acknowledged"):
            for record in self.spool.matching_records(
                state=state,
                source_prefix="",
            ):
                delivery = self.spool._event_delivery(record)
                if delivery is None:
                    continue
                session_id = str(delivery[0].get("hermes_session_id") or "")
                if session_id:
                    known.add(session_id)
        return known

    def _resolved_parent_session_id(
        self,
        session: dict[str, Any],
        known_session_ids: set[str],
    ) -> str | None:
        """Resolve lineage once, omitting parents that cannot be created first."""
        session_id = str(session["id"])
        lineage_key = (
            "backfill_lineage:"
            + hashlib.sha256(
                f"{self.logical_conversation_id}\x1f{session_id}".encode()
            ).hexdigest()
        )
        stored = self.spool.get_meta(lineage_key)
        if isinstance(stored, dict) and "parent_session_id" in stored:
            parent = stored.get("parent_session_id")
            return str(parent) if parent else None
        requested_parent = str(session.get("parent_session_id") or "")
        resolved_parent = (
            requested_parent if requested_parent in known_session_ids else None
        )
        self.spool.set_meta(
            lineage_key,
            {
                "schema_version": "sydney-backfill-lineage-v1",
                "parent_session_id": resolved_parent,
            },
        )
        return resolved_parent

    def _batch(
        self,
        session: dict[str, Any],
        events: list[dict[str, Any]],
        *,
        known_session_ids: set[str],
    ) -> dict[str, Any]:
        parent_session_id = self._resolved_parent_session_id(
            session,
            known_session_ids,
        )
        return {
            "platform": self.platform,
            "external_user_id": self.external_user_id,
            "external_chat_id": self.external_chat_id,
            "display_label": self.display_label,
            "hermes_session_id": str(session["id"]),
            "logical_conversation_id": self.logical_conversation_id,
            "parent_hermes_session_id": parent_session_id,
            "continuation_reason": (
                session.get("continuation_reason")
                if session.get("preserve_existing_lineage")
                else ("backfill_continuation" if parent_session_id else "backfill_root")
            ),
            "source_version": "hermes-state-backfill-v1",
            "events": events,
        }

    def _report(
        self,
        sessions: dict[str, dict[str, Any]],
        visible_rows: Iterable[dict[str, Any]],
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

    @staticmethod
    def _valid_source_report(report: Any) -> bool:
        if not isinstance(report, dict):
            return False
        if report.get("schema_version") != "sydney-backfill-v1":
            return False
        integer_fields = (
            "session_count",
            "message_count",
            "event_count",
            "tool_call_count",
            "tool_result_count",
        )
        if any(
            not isinstance(report.get(field), int) or report[field] < 0
            for field in integer_fields
        ):
            return False
        role_counts = report.get("role_counts")
        sessions = report.get("sessions")
        if not isinstance(role_counts, dict) or not isinstance(sessions, list):
            return False
        if any(
            not isinstance(role, str) or not isinstance(count, int) or count < 0
            for role, count in role_counts.items()
        ):
            return False

        def is_sha256(value: Any) -> bool:
            return (
                isinstance(value, str)
                and len(value) == 64
                and all(character in "0123456789abcdef" for character in value)
            )

        if not is_sha256(report.get("ordered_hash")):
            return False
        if report["session_count"] != len(sessions):
            return False
        return all(
            isinstance(session, dict)
            and is_sha256(session.get("session_key_sha256"))
            and is_sha256(session.get("ordered_hash"))
            for session in sessions
        )

    @staticmethod
    def _session_selection_sha256(sessions: dict[str, dict[str, Any]]) -> str:
        stable_selection = [
            {
                field: session.get(field)
                for field in (
                    "id",
                    "source",
                    "user_id",
                    "parent_session_id",
                    "started_at",
                    "ended_at",
                    "end_reason",
                    "continuation_reason",
                )
            }
            for _session_id, session in sorted(sessions.items())
        ]
        return hashlib.sha256(_canonical(stable_selection).encode()).hexdigest()

    def _cached_source_report(
        self,
        *,
        cutover: int,
        sessions: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        cached = self.spool.get_meta(self._source_report_key)
        if (
            not isinstance(cached, dict)
            or cached.get("schema_version") != "sydney-backfill-source-report-v1"
            or cached.get("cutover") != cutover
            or cached.get("session_selection_sha256")
            != self._session_selection_sha256(sessions)
            or not self._valid_source_report(cached.get("report"))
        ):
            return None
        return json.loads(_canonical(cached["report"]))

    def _store_source_report(
        self,
        *,
        cutover: int,
        sessions: dict[str, dict[str, Any]],
        report: dict[str, Any],
    ) -> None:
        self.spool.set_meta(
            self._source_report_key,
            {
                "schema_version": "sydney-backfill-source-report-v1",
                "cutover": cutover,
                "session_selection_sha256": self._session_selection_sha256(sessions),
                "report": report,
            },
        )

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
            cutover_value = self.spool.get_meta(self._cutover_key)
            if cutover_value is None:
                cutover_row = connection.execute(
                    f"SELECT COALESCE(MAX(id), 0) FROM messages WHERE {session_filter}",
                    session_ids,
                ).fetchone()
                cutover = int(cutover_row[0] if cutover_row is not None else 0)
                self.spool.set_meta(self._cutover_key, cutover)
            else:
                cutover = int(cutover_value)
            cursor = int(self.spool.get_meta(self._cursor_key, 0) or 0)
            report = (
                self._cached_source_report(cutover=cutover, sessions=sessions)
                if cursor >= cutover
                else None
            )
            if report is None:
                report_rows = (
                    dict(row)
                    for row in connection.execute(
                        f"SELECT {', '.join(columns)} FROM messages "
                        f"WHERE {session_filter} AND id <= ? ORDER BY id",
                        (*session_ids, cutover),
                    )
                    if "observed" not in row or not bool(row["observed"])
                )
                report = self._report(sessions, report_rows)
            known_session_ids = self._known_canonical_or_staged_sessions()
            pages = 0
            while max_pages is None or pages < max_pages:
                rows = list(
                    connection.execute(
                        f"SELECT {', '.join(columns)} FROM messages "
                        f"WHERE {session_filter} AND id > ? AND id <= ? "
                        "ORDER BY id LIMIT ?",
                        (*session_ids, cursor, cutover, bounded_page),
                    )
                )
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
                                payload=self._batch(
                                    session,
                                    [event],
                                    known_session_ids=known_session_ids,
                                ),
                            )
                            known_session_ids.add(str(session["id"]))
                    cursor = int(row["id"])
                    self.spool.set_meta(self._cursor_key, cursor)
                pages += 1
            if cursor >= cutover:
                self._store_source_report(
                    cutover=cutover,
                    sessions=sessions,
                    report=report,
                )
            return report
        finally:
            connection.close()

    @staticmethod
    def _event_signature(event: dict[str, Any]) -> tuple[str, ...]:
        content = str(event.get("content") or "")
        if event.get("event_type") == "tool_call":
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            else:
                content = _canonical(parsed)
        return (
            str(event.get("event_type") or ""),
            str(event.get("role") or ""),
            str(event.get("tool_name") or ""),
            str(event.get("tool_call_id") or ""),
            hashlib.sha256(content.encode()).hexdigest(),
        )

    def _matching_live_source(
        self,
        *,
        session_id: str,
        tail_source_key: str,
        event: dict[str, Any],
        consumed_sources: set[str],
    ) -> str | None:
        if self.spool.has_tail_live_match(tail_source_key):
            return tail_source_key
        expected = self._event_signature(event)
        expected_message_id = str(
            (event.get("metadata") or {}).get("platform_message_id") or ""
        )
        expected_at = datetime.fromisoformat(
            str(event.get("occurred_at") or "").replace("Z", "+00:00")
        )
        for state in ("pending", "acknowledged"):
            for record in self.spool.matching_records(
                state=state,
                source_prefix="",
            ):
                if record.source_key.startswith(("backfill:", "tail:")):
                    continue
                delivery = self.spool._event_delivery(record)
                if delivery is None:
                    continue
                batch, _receipt = delivery
                if str(batch.get("hermes_session_id") or "") != session_id:
                    continue
                for candidate in batch.get("events") or []:
                    if not isinstance(candidate, dict):
                        continue
                    candidate_source_key = str(candidate.get("source_event_key") or "")
                    if (
                        not candidate_source_key
                        or candidate_source_key in consumed_sources
                        or self.spool.has_live_tail_match(candidate_source_key)
                    ):
                        continue
                    if self._event_signature(candidate) != expected:
                        continue
                    candidate_message_id = str(
                        (candidate.get("metadata") or {}).get("platform_message_id")
                        or ""
                    )
                    if expected_message_id:
                        if candidate_message_id == expected_message_id:
                            self.spool.record_tail_live_match(
                                tail_source_key=tail_source_key,
                                live_source_key=candidate_source_key,
                            )
                            return candidate_source_key
                        continue
                    if event.get("tool_call_id"):
                        self.spool.record_tail_live_match(
                            tail_source_key=tail_source_key,
                            live_source_key=candidate_source_key,
                        )
                        return candidate_source_key
                    try:
                        candidate_at = datetime.fromisoformat(
                            str(candidate.get("occurred_at") or "").replace(
                                "Z", "+00:00"
                            )
                        )
                    except (TypeError, ValueError):
                        continue
                    if abs((candidate_at - expected_at).total_seconds()) <= 300:
                        self.spool.record_tail_live_match(
                            tail_source_key=tail_source_key,
                            live_source_key=candidate_source_key,
                        )
                        return candidate_source_key
        return None

    def run_live_tail(
        self,
        *,
        page_size: int = 100,
        max_pages: int | None = 1,
    ) -> int:
        """Queue visible state rows written after the frozen backfill boundary."""
        cutover_value = self.spool.get_meta(self._cutover_key)
        if cutover_value is None or not self.state_db.is_file():
            return 0
        bounded_page = max(1, min(int(page_size), 100))
        cursor = max(
            int(cutover_value),
            int(self.spool.get_meta(self._live_cursor_key, cutover_value) or 0),
        )
        connection = self._connect()
        queued = 0
        consumed_sources: set[str] = set()
        try:
            sessions = self._sessions(connection)
            session_ids = tuple(sessions)
            if not session_ids:
                return 0
            known_session_ids = self._known_canonical_or_staged_sessions()
            columns = self._message_columns(connection)
            placeholders = ", ".join("?" for _ in session_ids)
            pages = 0
            while max_pages is None or pages < max_pages:
                rows = list(
                    connection.execute(
                        f"SELECT {', '.join(columns)} FROM messages "
                        f"WHERE session_id IN ({placeholders}) AND id > ? "
                        "ORDER BY id LIMIT ?",
                        (*session_ids, cursor, bounded_page),
                    )
                )
                if not rows:
                    break
                for raw in rows:
                    row = dict(raw)
                    session_id = str(row["session_id"])
                    session = sessions.get(session_id)
                    if session is not None:
                        for event in self._events_for_message(row):
                            source_key = f"tail:{event['source_event_key']}"
                            if self.spool.get_record(source_key) is not None:
                                continue
                            matched = self._matching_live_source(
                                session_id=session_id,
                                tail_source_key=source_key,
                                event=event,
                                consumed_sources=consumed_sources,
                            )
                            if matched is not None:
                                consumed_sources.add(matched)
                                continue
                            self.spool.enqueue(
                                kind="event_batch",
                                source_key=source_key,
                                payload=self._batch(
                                    session,
                                    [event],
                                    known_session_ids=known_session_ids,
                                ),
                            )
                            known_session_ids.add(session_id)
                            queued += 1
                    cursor = int(row["id"])
                    self.spool.set_meta(self._live_cursor_key, cursor)
                pages += 1
            return queued
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
            if (
                self.spool.matching_count(
                    state="pending",
                    source_prefix="backfill:",
                )
                == 0
            ):
                return 0
            result = self.spool.drain(
                lambda record: backend.ingest_events(record.payload),
                limit=100,
                source_prefix="backfill:",
            )
            remaining = self.spool.matching_count(
                state="pending", source_prefix="backfill:"
            )
            if remaining == 0:
                return 0
            if time.monotonic() >= deadline:
                return remaining
            if result.acknowledged == 0:
                time.sleep(0.25)

    def _store_reconciliation_proof(
        self,
        *,
        source: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        expectations = self.spool.reconciliation_expectations()
        self.spool.set_meta(
            self._reconciliation_proof_key,
            {
                "schema_version": "sydney-backfill-compacted-proof-v1",
                "source_sha256": hashlib.sha256(
                    _canonical(source).encode()
                ).hexdigest(),
                "report": report,
                "sessions": [
                    {
                        "hermes_session_id": session_id,
                        "identity_id": expectation["identity_id"],
                    }
                    for session_id, expectation in sorted(expectations.items())
                ],
            },
        )

    def _compacted_reconciliation_report(
        self,
        backend: Any,
        *,
        source: dict[str, Any],
        unacknowledged_count: int,
    ) -> dict[str, Any] | None:
        proof = self.spool.get_meta(self._reconciliation_proof_key)
        if (
            unacknowledged_count != 0
            or not isinstance(proof, dict)
            or proof.get("schema_version") != "sydney-backfill-compacted-proof-v1"
            or proof.get("source_sha256")
            != hashlib.sha256(_canonical(source).encode()).hexdigest()
            or not isinstance(proof.get("report"), dict)
            or not isinstance(proof.get("sessions"), list)
        ):
            return None
        report = json.loads(_canonical(proof["report"]))
        public_sessions = {
            str(row.get("session_key_sha256") or ""): row
            for row in report.get("sessions", [])
            if isinstance(row, dict)
        }
        current_expectations = self.spool.reconciliation_expectations()
        all_matched = bool(report.get("matched"))
        refreshed_sessions: list[dict[str, Any]] = []
        for stored in proof["sessions"]:
            if not isinstance(stored, dict):
                all_matched = False
                continue
            session_id = str(stored.get("hermes_session_id") or "")
            session_key = hashlib.sha256(session_id.encode()).hexdigest()
            public = public_sessions.get(session_key)
            expectation = current_expectations.get(session_id)
            if (
                public is None
                or expectation is None
                or expectation.get("identity_id") != stored.get("identity_id")
            ):
                all_matched = False
                continue
            response = backend.reconcile_session(expectation)
            backend_matched = bool(response.get("matched")) and (
                int(response.get("event_count", -1))
                == expectation["expected_event_count"]
                and str(response.get("ordered_hash") or "")
                == expectation["expected_ordered_hash"]
            )
            refreshed = {
                **public,
                "matched": bool(public.get("matched")) and backend_matched,
            }
            refreshed_sessions.append(refreshed)
            all_matched = all_matched and refreshed["matched"]
        all_matched = all_matched and len(refreshed_sessions) == len(public_sessions)
        return {
            **report,
            "matched": all_matched,
            "unacknowledged_count": unacknowledged_count,
            "source": source,
            "sessions": sorted(
                refreshed_sessions,
                key=lambda row: row["session_key_sha256"],
            ),
        }

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
        if not records:
            compacted = self._compacted_reconciliation_report(
                backend,
                source=source,
                unacknowledged_count=unacknowledged_count,
            )
            if compacted is not None:
                return compacted
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
            and int(source.get("session_count", -1)) == acknowledged["session_count"]
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
        report = self._acknowledgement_report(
            backend,
            source=source,
            unacknowledged_count=remaining,
        )
        compacted = 0
        if report.get("matched"):
            self._store_reconciliation_proof(source=source, report=report)
            for session_id in self.spool.reconciliation_expectations():
                compacted += self.spool.compact_reconciled_session(session_id)
        return {**report, "compacted_record_count": compacted}


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
