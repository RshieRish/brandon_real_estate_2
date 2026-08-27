"""Admit one exact reconciled Hermes user turn for review-only recovery."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from .sydney_backfill import SydneyBackfill
    from .sydney_retry import AUTOMATIC_CONTINUATION_MESSAGE
    from .sydney_spool import SpoolConflict, SpoolRecord, SydneySpool
except ImportError:
    from sydney_backfill import SydneyBackfill
    from sydney_retry import AUTOMATIC_CONTINUATION_MESSAGE
    from sydney_spool import SpoolConflict, SpoolRecord, SydneySpool


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_PREFIXES = (
    "[system continuation:",
    "[sydney canary:",
    "[sydney control:",
    "[atlas canary:",
    "sydney durable context canary",
)


class RecoveryRejected(RuntimeError):
    """The selected legacy row is not safe and eligible for recovery."""


def _content_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_control_content(value: str) -> bool:
    normalized = value.strip().casefold()
    return (
        normalized == AUTOMATIC_CONTINUATION_MESSAGE.casefold()
        or normalized.startswith(_CONTROL_PREFIXES)
    )


class SydneyLegacyRecovery:
    """Validate and stage only one explicitly selected legacy user event."""

    def __init__(self, *, backfill: SydneyBackfill, spool: SydneySpool) -> None:
        self.backfill = backfill
        self.spool = spool

    def _lineage(self, session_id: str) -> dict[str, Any]:
        lineage = self.spool.get_session(session_id)
        if lineage is None:
            raise RecoveryRejected("selected session has no private identity proof")
        expected = (
            self.backfill.logical_conversation_id,
            self.backfill.platform,
            self.backfill.external_user_id,
            self.backfill.external_chat_id,
        )
        stored = tuple(
            str(lineage.get(key) or "")
            for key in (
                "logical_conversation_id",
                "platform",
                "external_user_id",
                "external_chat_id",
            )
        )
        if stored != expected:
            raise RecoveryRejected("selected session identity does not match")
        return lineage

    def _related_session_ids(self, lineage: dict[str, Any]) -> list[str]:
        identity = tuple(
            str(lineage.get(key) or "")
            for key in (
                "logical_conversation_id",
                "platform",
                "external_user_id",
                "external_chat_id",
            )
        )
        result = []
        for candidate in self.spool.list_sessions():
            candidate_identity = tuple(
                str(candidate.get(key) or "")
                for key in (
                    "logical_conversation_id",
                    "platform",
                    "external_user_id",
                    "external_chat_id",
                )
            )
            if candidate_identity == identity:
                result.append(str(candidate["session_id"]))
        return sorted(set(result))

    @staticmethod
    def _has_tool_calls(row: dict[str, Any]) -> bool:
        raw = row.get("tool_calls")
        if isinstance(raw, list):
            return bool(raw)
        if not isinstance(raw, str) or not raw.strip():
            return False
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        return isinstance(parsed, list) and bool(parsed)

    def _has_later_final_assistant(
        self,
        connection: sqlite3.Connection,
        *,
        lineage: dict[str, Any],
        message_id: int,
    ) -> bool:
        session_ids = self._related_session_ids(lineage)
        if not session_ids:
            return False
        columns = self.backfill._message_columns(connection)
        placeholders = ", ".join("?" for _ in session_ids)
        rows = connection.execute(
            f"SELECT {', '.join(columns)} FROM messages "
            f"WHERE session_id IN ({placeholders}) AND id > ? ORDER BY id",
            (*session_ids, message_id),
        )
        for raw in rows:
            row = dict(raw)
            if bool(row.get("observed", 0)):
                continue
            role = str(row.get("role") or "")
            if role == "user":
                if _is_control_content(str(row.get("content") or "")):
                    continue
                return False
            if role != "assistant" or self._has_tool_calls(row):
                continue
            for event in self.backfill._events_for_message(row):
                if (
                    event.get("event_type") == "assistant"
                    and str(event.get("content") or "").strip()
                    and not _is_control_content(str(event["content"]))
                ):
                    return True
        return False

    def _selected_row(
        self,
        *,
        session_id: str,
        message_id: int,
        lineage: dict[str, Any],
    ) -> dict[str, Any]:
        connection = self.backfill._connect()
        try:
            message_columns = self.backfill._message_columns(connection)
            required = {"id", "session_id", "role", "content", "timestamp"}
            if not required.issubset(message_columns):
                raise RecoveryRejected("state message schema is incomplete")
            raw = connection.execute(
                f"SELECT {', '.join(message_columns)} FROM messages "
                "WHERE id=? AND session_id=?",
                (message_id, session_id),
            ).fetchone()
            if raw is None:
                raise RecoveryRejected("selected message does not exist")
            session_columns = self.backfill._columns(connection, "sessions")
            if not {"id", "source", "user_id"}.issubset(session_columns):
                raise RecoveryRejected("state session schema is incomplete")
            session = connection.execute(
                "SELECT id, source, user_id FROM sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            if (
                session is None
                or str(session["source"] or "") != self.backfill.platform
                or session["user_id"] not in {None, self.backfill.external_user_id}
            ):
                raise RecoveryRejected("selected session identity does not match")
            if self._has_later_final_assistant(
                connection,
                lineage=lineage,
                message_id=message_id,
            ):
                raise RecoveryRejected(
                    "selected message already has a final assistant response"
                )
            return dict(raw)
        finally:
            connection.close()

    def _validated_event(
        self,
        *,
        session_id: str,
        message_id: int,
        expected_content_sha256: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not session_id or message_id < 1:
            raise RecoveryRejected("selected message identity is invalid")
        if not _SHA256.fullmatch(expected_content_sha256):
            raise RecoveryRejected("expected content hash is invalid")
        lineage = self._lineage(session_id)
        row = self._selected_row(
            session_id=session_id,
            message_id=message_id,
            lineage=lineage,
        )
        if str(row.get("role") or "") != "user" or bool(row.get("observed", 0)):
            raise RecoveryRejected("selected message is not a visible user row")
        events = self.backfill._events_for_message(row)
        if len(events) != 1 or events[0].get("event_type") != "user":
            raise RecoveryRejected("selected message is not one business user event")
        event = events[0]
        content = str(event.get("content") or "")
        if not content or _is_control_content(content):
            raise RecoveryRejected("selected message is a control or canary row")
        actual_hash = _content_sha256(content)
        if not hmac.compare_digest(actual_hash, expected_content_sha256):
            raise RecoveryRejected("selected message hash does not match")
        expectation = self.spool.reconciliation_expectation(session_id)
        if expectation is None:
            raise RecoveryRejected("selected session is not reconciled")
        canonical = self.spool.get_record(f"backfill:{event['source_event_key']}")
        if (
            canonical is None
            or canonical.kind != "event_batch"
            or canonical.state != "acknowledged"
        ):
            raise RecoveryRejected(
                "selected event has no acknowledged backfill receipt"
            )
        if canonical.payload:
            stored_events = canonical.payload.get("events")
            if not isinstance(stored_events, list) or event not in stored_events:
                raise RecoveryRejected("selected backfill receipt does not match")
        return event, lineage

    def _event_batch(
        self,
        *,
        session_id: str,
        event: dict[str, Any],
        lineage: dict[str, Any],
    ) -> dict[str, Any]:
        lineage_key = (
            "backfill_lineage:"
            + hashlib.sha256(
                f"{self.backfill.logical_conversation_id}\x1f{session_id}".encode()
            ).hexdigest()
        )
        resolution = self.spool.get_meta(lineage_key)
        if not isinstance(resolution, dict) or "parent_session_id" not in resolution:
            raise RecoveryRejected("exact backfill lineage proof is unavailable")
        parent = resolution.get("parent_session_id")
        return {
            "platform": self.backfill.platform,
            "external_user_id": self.backfill.external_user_id,
            "external_chat_id": self.backfill.external_chat_id,
            "display_label": self.backfill.display_label,
            "hermes_session_id": session_id,
            "logical_conversation_id": self.backfill.logical_conversation_id,
            "parent_hermes_session_id": str(parent) if parent else None,
            "continuation_reason": lineage.get("continuation_reason"),
            "source_version": "hermes-state-backfill-v1",
            "events": [event],
        }

    @staticmethod
    def _existing_run_id(record: SpoolRecord) -> str:
        return str(
            (((record.receipt or {}).get("run") or {}).get("run") or {}).get("id") or ""
        )

    def _validate_existing(
        self,
        record: SpoolRecord,
        *,
        batch: dict[str, Any],
        platform_message_id: str,
    ) -> None:
        run_id = self._existing_run_id(record)
        if run_id and self.spool.is_run_terminal(run_id):
            raise RecoveryRejected("selected recovery already reached a terminal state")
        if record.kind != "inbound_bundle" or not record.payload:
            raise RecoveryRejected("existing recovery record cannot be verified")
        run_start = record.payload.get("run_start")
        if (
            record.payload.get("event_batch") != batch
            or record.payload.get("local_metadata")
            != {"recovery_policy": "review_only"}
            or not isinstance(run_start, dict)
            or run_start.get("platform_message_id") != platform_message_id
            or not run_start.get("terminal_deadline_at")
        ):
            raise RecoveryRejected("existing recovery record does not match")

    @staticmethod
    def _result(
        *,
        event: dict[str, Any],
        platform_message_id: str,
        record_id: int | None,
        existing: bool,
    ) -> dict[str, Any]:
        return {
            "eligible": True,
            "enqueued": record_id is not None,
            "existing": existing,
            "recovery_policy": "review_only",
            "content_sha256": _content_sha256(str(event.get("content") or "")),
            "source_event_key_sha256": _content_sha256(
                str(event.get("source_event_key") or "")
            ),
            "platform_message_id": platform_message_id,
            "record_id": record_id,
        }

    def admit(
        self,
        *,
        session_id: str,
        message_id: int,
        expected_content_sha256: str,
        enqueue: bool = False,
    ) -> dict[str, Any]:
        event, lineage = self._validated_event(
            session_id=str(session_id),
            message_id=int(message_id),
            expected_content_sha256=str(expected_content_sha256).lower(),
        )
        stable = (
            f"{self.backfill.platform}\x1f{self.backfill.external_chat_id}"
            f"\x1f{session_id}\x1f{message_id}"
        )
        digest = hashlib.sha256(stable.encode()).hexdigest()
        platform_message_id = f"legacy-recovery:{digest}"
        source_key = f"inbound:recovery:{digest}"
        batch = self._event_batch(
            session_id=str(session_id),
            event=event,
            lineage=lineage,
        )
        existing = self.spool.get_record(source_key)
        if existing is not None:
            self._validate_existing(
                existing,
                batch=batch,
                platform_message_id=platform_message_id,
            )
            return self._result(
                event=event,
                platform_message_id=platform_message_id,
                record_id=existing.id,
                existing=True,
            )
        if not enqueue:
            return self._result(
                event=event,
                platform_message_id=platform_message_id,
                record_id=None,
                existing=False,
            )
        run_start = {
            "platform_message_id": platform_message_id,
            "terminal_deadline_at": (datetime.now(timezone.utc) + timedelta(hours=24))
            .replace(microsecond=0)
            .isoformat(),
        }
        try:
            record_id = self.spool.enqueue_inbound(
                batch,
                run_start,
                source_key=source_key,
                local_metadata={"recovery_policy": "review_only"},
            )
        except SpoolConflict:
            raced = self.spool.get_record(source_key)
            if raced is None:
                raise
            self._validate_existing(
                raced,
                batch=batch,
                platform_message_id=platform_message_id,
            )
            return self._result(
                event=event,
                platform_message_id=platform_message_id,
                record_id=raced.id,
                existing=True,
            )
        return self._result(
            event=event,
            platform_message_id=platform_message_id,
            record_id=record_id,
            existing=False,
        )


def _enabled(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _sha256_argument(value: str) -> str:
    normalized = value.strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise argparse.ArgumentTypeError("expected a 64-character SHA-256")
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-db", required=True, type=Path)
    parser.add_argument("--spool", required=True, type=Path)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--message-id", required=True, type=int)
    parser.add_argument(
        "--expected-content-sha256",
        required=True,
        type=_sha256_argument,
    )
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="Stage the exact recovery after a successful dry-run.",
    )
    args = parser.parse_args()

    external_user_id = os.environ.get(
        "SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID", ""
    ).strip()
    external_chat_id = os.environ.get(
        "SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID", ""
    ).strip()
    allowed_user_ids = {
        item.strip()
        for item in os.environ.get("SYDNEY_DURABLE_CONTEXT_ALLOWED_USER_IDS", "").split(
            ","
        )
        if item.strip()
    }
    if (
        not _enabled(os.environ.get("SYDNEY_DURABLE_CONTEXT_ENABLED", ""))
        or not external_user_id
        or not external_chat_id
        or external_user_id not in allowed_user_ids
    ):
        raise SystemExit("Sydney private identity configuration is not enabled")

    spool = SydneySpool(args.spool)
    try:
        recovery = SydneyLegacyRecovery(
            backfill=SydneyBackfill(
                state_db=args.state_db,
                spool=spool,
                platform="telegram",
                external_user_id=external_user_id,
                external_chat_id=external_chat_id,
                display_label=os.environ.get(
                    "SYDNEY_DURABLE_CONTEXT_DISPLAY_LABEL", "Brandon"
                ).strip()
                or "Brandon",
            ),
            spool=spool,
        )
        try:
            result = recovery.admit(
                session_id=args.session_id,
                message_id=args.message_id,
                expected_content_sha256=args.expected_content_sha256,
                enqueue=args.enqueue,
            )
        except RecoveryRejected as exc:
            raise SystemExit(f"recovery rejected: {exc}") from exc
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    finally:
        spool.close()


if __name__ == "__main__":
    main()
