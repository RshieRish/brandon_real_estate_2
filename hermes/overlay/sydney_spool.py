"""Crash-safe local write-ahead spool for Sydney durable context.

This module intentionally uses only the Python standard library because it is
copied into the pinned Hermes runtime image.
"""

from __future__ import annotations

import fcntl
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
from urllib.parse import (
    parse_qsl,
    quote,
    quote_plus,
    unquote,
    urlencode,
    urlsplit,
    urlunsplit,
)
from uuid import UUID

SCHEMA_VERSION = 1
_SECRET_KEY = re.compile(
    r"(?:^|_)(?:authorization|access_token|refresh_token|id_token|oauth_token|"
    r"password|passwd|pwd|api_key|client_secret|cookie|set_cookie|bearer_token|"
    r"token|secret|credential|credentials|handoff)(?:$|_)",
    re.IGNORECASE,
)
_AUTHORIZATION = re.compile(
    r"(?i)(\bauthorization\s*:\s*(?:bearer|basic|token)\s+)[^\s,;]+"
)
_BEARER = re.compile(r"(?i)(\bbearer\s+)[a-z0-9._~+/=-]+")
_ASSIGNMENT_VALUE = (
    r'(?:(?:"(?!\[REDACTED_)[^"\r\n]*")|'
    r"(?:'(?!\[REDACTED_)[^'\r\n]*')|"
    r'(?!\[REDACTED_)[^"\'\s&,;}#]+)'
)
_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:password|passwd|pwd|client[ _-]?secret|secret)"
    r"[\"']?\s*(?::|=|\bis\b)\s*)" + _ASSIGNMENT_VALUE + r"|"
    r"([\"']?(?:access[_-]?token|refresh[_-]?token|api[_-]?key|"
    r"oauth[_-]?token|id[_-]?token|session[_-]?token|handoff|token)"
    r"[\"']?\s*[:=]\s*)" + _ASSIGNMENT_VALUE
)
_COOKIE_HEADER = re.compile(r"(?i)(\bset-cookie\s*:\s*)[^\r\n]+")
_KNOWN_TOKEN = re.compile(
    r"\b(?:AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9_-]{20,})\b"
)
_CONTEXT_TOKEN_AFTER = re.compile(
    r"(?is)(\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b)"
    r"(?=(?:[ \t]*\r?\n){1,3}[ \t]*(?:here|this)\s+is\s+the\s+"
    r"(?:api\s+)?token\b)"
)
_CONTEXT_TOKEN_BEFORE = re.compile(
    r"(?i)(\b(?:api\s+|railway\s+|workspace\s+|account\s+)?"
    r"(?:token|credential|api[_ -]?key)\b\s*(?:is|[:=])?\s*)"
    r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9_-]{20,})"
)
_URI_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://(?:[^/\s:@]+):)([^@/\s]+)(@)")
_URL = re.compile(r"https?://[^\s<>\"']+")
_URL_SECRET_KEYS = {
    "access_token",
    "approval",
    "approval_token",
    "refresh_token",
    "id_token",
    "token",
    "session",
    "session_token",
    "nonce",
    "handoff",
    "code",
    "state",
    "signature",
    "sig",
    "api_key",
    "apikey",
    "key",
    "password",
    "client_secret",
}
_MAX_NESTED_REDACTION_DEPTH = 4
_CONFIGURED_SECRET_ENV_NAMES = (
    "DATABASE_URL",
    "GMAIL_HISTORY_DATABASE_URL",
    "GMAIL_PARTICIPANT_HASH_KEY",
    "AGENT_CONTROL_TOKEN",
    "BRANDON_AGENT_CONTROL_TOKEN",
    "GEMINI_API_KEY",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_CALENDAR_CLIENT_SECRET",
    "GOOGLE_WORKSPACE_CLIENT_SECRET",
    "GOOGLE_WORKSPACE_REFRESH_TOKEN",
    "JWT_SECRET",
    "SMTP_PASS",
    "GOOGLE_MAPS_API_KEY",
    "GOOGLE_CALENDAR_REFRESH_TOKEN",
    "RENTCAST_API_KEY",
    "R2_SECRET_ACCESS_KEY",
    "TELEGRAM_BOT_TOKEN",
    "SYDNEY_TELEGRAM_BOT_TOKEN",
    "SYDNEY_CLARIFICATION_CODE_KEYS_JSON",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
)


def _normalized_secret_key(value: str) -> str:
    separated_acronyms = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    separated_words = re.sub(
        r"([a-z0-9])([A-Z])",
        r"\1_\2",
        separated_acronyms,
    )
    return re.sub(r"[^A-Za-z0-9]+", "_", separated_words).strip("_").lower()


def _is_secret_key(value: str) -> bool:
    return bool(_SECRET_KEY.search(_normalized_secret_key(value)))


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


def _final_delivery_meta_key(
    platform: str,
    chat_id: str,
    platform_message_id: str,
) -> str:
    stable_key = f"{platform}\x1f{chat_id}\x1f{platform_message_id}"
    return "final_delivery:" + hashlib.sha256(stable_key.encode("utf-8")).hexdigest()


def control_delivery_source_key(run_id: str, delivery_kind: str) -> str:
    if delivery_kind not in {"deferred", "terminal_error"}:
        raise ValueError("control delivery kind is invalid")
    exact_run_id = str(run_id)
    if not exact_run_id:
        raise ValueError("control delivery run id is required")
    return f"run:{exact_run_id}:control:{delivery_kind}"


def _terminal_inbound_meta_key(source_key: str) -> str:
    digest = hashlib.sha256(str(source_key).encode("utf-8")).hexdigest()
    return f"terminal_inbound:{digest}"


def _tail_live_match_meta_key(direction: str, source_key: str) -> str:
    if direction not in {"tail", "live"}:
        raise ValueError("tail/live match direction is invalid")
    digest = hashlib.sha256(str(source_key).encode("utf-8")).hexdigest()
    return f"tail_live_match:{direction}:{digest}"


def _parsed_timestamp(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def ordered_reconciliation_hash(rows: list[dict[str, Any]]) -> str:
    """Match the backend's timestamp/UUID ordered, domain-separated digest."""
    ordered = sorted(
        rows,
        key=lambda row: (
            _parsed_timestamp(row.get("occurred_at")),
            UUID(str(row["event_id"])).bytes,
        ),
    )
    digest = hashlib.sha256(b"sws:sydney-context:reconciliation:v1\0")
    for row in ordered:
        event_type = str(row["event_type"])
        digest.update(UUID(str(row["event_id"])).bytes)
        digest.update(len(event_type.encode("utf-8")).to_bytes(2, "big"))
        digest.update(event_type.encode("utf-8"))
        digest.update(bytes.fromhex(str(row["content_sha256"])))
    return digest.hexdigest()


def _redact_query_value(key: str, value: str, *, depth: int, fragment: bool) -> str:
    if key.lower() in _URL_SECRET_KEYS:
        return "[REDACTED_SIGNED_FRAGMENT]" if fragment else "[REDACTED_OAUTH_TOKEN]"
    return _redact_nested_url_value(value, depth=depth + 1)


def _redact_url(match: re.Match[str], *, depth: int = 0) -> str:
    raw = match.group(0)
    try:
        parts = urlsplit(raw)
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        query = [
            (
                key,
                _redact_query_value(key, value, depth=depth, fragment=False),
            )
            for key, value in query_pairs
        ]
        fragment = parts.fragment
        fragment_pairs = parse_qsl(fragment, keep_blank_values=True)
        redacted_fragment_pairs = [
            (
                key,
                _redact_query_value(
                    key,
                    value,
                    depth=depth,
                    fragment=True,
                ),
            )
            for key, value in fragment_pairs
        ]
        if query == query_pairs and redacted_fragment_pairs == fragment_pairs:
            return raw
        if fragment_pairs:
            fragment = urlencode(redacted_fragment_pairs)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), fragment)
        )
    except (TypeError, ValueError):
        return "[REDACTED_URL_WITH_SECRET]"


def _redact_nested_url_value(value: str, *, depth: int) -> str:
    if depth >= _MAX_NESTED_REDACTION_DEPTH:
        decoded = unquote(value)
        if decoded != value:
            nested = _URL.sub(lambda match: _redact_url(match, depth=depth), decoded)
            if nested != decoded:
                return quote(nested, safe="")
        return value

    redacted = _URL.sub(lambda match: _redact_url(match, depth=depth), value)
    if redacted != value:
        return redacted

    if value.startswith(("?", "#")):
        prefix, query_string = value[0], value[1:]
        pairs = parse_qsl(query_string, keep_blank_values=True)
        if pairs:
            fragment = prefix == "#"
            nested = prefix + urlencode(
                [
                    (
                        key,
                        _redact_query_value(
                            key,
                            item,
                            depth=depth,
                            fragment=fragment,
                        ),
                    )
                    for key, item in pairs
                ]
            )
            if nested != value:
                return nested

    decoded = unquote(value)
    if decoded != value:
        nested = _redact_nested_url_value(decoded, depth=depth + 1)
        nested = _URL.sub(lambda match: _redact_url(match, depth=depth + 1), nested)
        if nested != decoded:
            return quote(nested, safe="")
    return value


def redact_text(value: str) -> str:
    """Irreversibly remove common credential forms without logging matches."""
    redacted = value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        safe_parsed = redact_payload(parsed)
        if safe_parsed != parsed:
            redacted = _canonical_json(safe_parsed)
    configured_secrets = {
        secret
        for name in _CONFIGURED_SECRET_ENV_NAMES
        if isinstance((secret := os.environ.get(name)), str) and len(secret) >= 8
    }
    redacted = _redact_configured_values(redacted, configured_secrets)
    redacted = _CONTEXT_TOKEN_AFTER.sub("[REDACTED_CONTEXT_TOKEN]", redacted)
    redacted = _CONTEXT_TOKEN_BEFORE.sub(r"\1[REDACTED_CONTEXT_TOKEN]", redacted)
    redacted = _URI_USERINFO.sub(r"\1[REDACTED_URI_PASSWORD]\3", redacted)
    redacted = _URL.sub(lambda match: _redact_url(match, depth=0), redacted)
    redacted = _AUTHORIZATION.sub(r"\1[REDACTED_AUTH_TOKEN]", redacted)
    redacted = _BEARER.sub(r"\1[REDACTED_BEARER_TOKEN]", redacted)
    redacted = _COOKIE_HEADER.sub(r"\1[REDACTED_COOKIE]", redacted)
    redacted = _ASSIGNMENT.sub(
        lambda match: (match.group(1) or match.group(2) or "") + "[REDACTED_SECRET]",
        redacted,
    )
    redacted = _KNOWN_TOKEN.sub("[REDACTED_PROVIDER_TOKEN]", redacted)
    redacted = re.sub(
        r"(?i)([#?&](?:access_token|approval|approval_token|api_key|apikey|"
        r"client_secret|code|handoff|id_token|key|nonce|oauth_token|password|"
        r"refresh_token|session|session_token|sig|signature|state|token)=)"
        r"[^\s&#\"']+",
        r"\1[REDACTED_SIGNED_FRAGMENT]",
        redacted,
    )
    return _redact_configured_values(redacted, configured_secrets)


def _redact_configured_values(value: str, configured_secrets: set[str]) -> str:
    variants: set[str] = set()
    for secret in configured_secrets:
        frontier = {secret}
        variants.add(secret)
        for _depth in range(_MAX_NESTED_REDACTION_DEPTH):
            encoded = {
                candidate
                for item in frontier
                for candidate in (quote(item, safe=""), quote_plus(item, safe=""))
            }
            encoded -= variants
            if not encoded:
                break
            variants.update(encoded)
            frontier = encoded
    redacted = value
    for variant in sorted(variants, key=len, reverse=True):
        if "%" not in variant:
            redacted = redacted.replace(variant, "[REDACTED_CONFIGURED_SECRET]")
            continue
        pieces: list[str] = []
        index = 0
        while index < len(variant):
            if (
                variant[index] == "%"
                and index + 2 < len(variant)
                and all(
                    character in "0123456789abcdefABCDEF"
                    for character in variant[index + 1 : index + 3]
                )
            ):
                first, second = variant[index + 1 : index + 3]
                pieces.append(
                    "%"
                    + (
                        f"[{first.lower()}{first.upper()}]"
                        if first.isalpha()
                        else first
                    )
                    + (
                        f"[{second.lower()}{second.upper()}]"
                        if second.isalpha()
                        else second
                    )
                )
                index += 3
                continue
            pieces.append(re.escape(variant[index]))
            index += 1
        redacted = re.sub(
            "".join(pieces),
            "[REDACTED_CONFIGURED_SECRET]",
            redacted,
        )
    return redacted


def redact_payload(
    value: Any,
    *,
    key: str = "",
    secret_context: bool = False,
) -> Any:
    """Return a JSON-safe, recursively redacted copy of ``value``."""
    inside_secret = secret_context or bool(key and _is_secret_key(key))
    if isinstance(value, str):
        if inside_secret:
            return "[REDACTED_SECRET]"
        return redact_text(value)
    if isinstance(value, dict):
        return {
            str(item_key): redact_payload(
                item,
                key=str(item_key),
                secret_context=inside_secret,
            )
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_payload(item, secret_context=inside_secret) for item in value]
    if inside_secret:
        return "[REDACTED_SECRET]"
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
        self._drain_lock_path = Path(f"{self.path}.drain.lock")
        drain_descriptor = os.open(
            self._drain_lock_path,
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        os.close(drain_descriptor)
        os.chmod(self._drain_lock_path, 0o600)
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
                    CREATE TABLE IF NOT EXISTS outbox_tombstones (
                        source_key TEXT PRIMARY KEY,
                        original_id INTEGER NOT NULL,
                        kind TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        compacted_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS reconciliation_events (
                        event_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        identity_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        content_sha256 TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS ix_sydney_reconciliation_events_session
                        ON reconciliation_events (session_id, occurred_at, event_id);
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
                    CREATE TABLE IF NOT EXISTS reconciliation_state (
                        session_id TEXT PRIMARY KEY,
                        identity_id TEXT NOT NULL,
                        event_count INTEGER NOT NULL,
                        ordered_hash TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS reconciliation_dirty (
                        session_id TEXT PRIMARY KEY,
                        dirty_at TEXT NOT NULL
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
                initialized = self.connection.execute(
                    "SELECT 1 FROM spool_meta "
                    "WHERE key='reconciliation_state_initialized_v1'"
                ).fetchone()
                if initialized is None:
                    dirty_sessions = {
                        str(row["session_id"])
                        for row in self.connection.execute(
                            "SELECT DISTINCT session_id FROM reconciliation_events"
                        ).fetchall()
                    }
                    rows = self.connection.execute(
                        "SELECT * FROM outbox WHERE state='acknowledged' ORDER BY id"
                    ).fetchall()
                    for row in rows:
                        delivery = self._event_delivery(self._record(row))
                        if delivery is not None and delivery[0].get(
                            "hermes_session_id"
                        ):
                            session_id = self._index_reconciliation_delivery(*delivery)
                            dirty_sessions.add(session_id)
                    with self.connection:
                        for session_id in sorted(dirty_sessions):
                            self._refresh_reconciliation_state(session_id)
                            self.connection.execute(
                                "INSERT OR IGNORE INTO reconciliation_dirty"
                                "(session_id, dirty_at) VALUES(?, ?)",
                                (session_id, _utc_now()),
                            )
                        self.connection.execute(
                            "INSERT INTO spool_meta(key, value_json, updated_at) "
                            "VALUES('reconciliation_state_initialized_v1', 'true', ?)",
                            (_utc_now(),),
                        )
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

    def has_tail_live_match(self, tail_source_key: str) -> bool:
        value = self.get_meta(_tail_live_match_meta_key("tail", tail_source_key))
        if value is None:
            return False
        if not isinstance(value, dict) or not re.fullmatch(
            r"[0-9a-f]{64}", str(value.get("live_source_sha256") or "")
        ):
            raise SpoolConflict("tail/live match metadata is invalid")
        return True

    def has_live_tail_match(self, live_source_key: str) -> bool:
        value = self.get_meta(_tail_live_match_meta_key("live", live_source_key))
        if value is None:
            return False
        if not isinstance(value, dict) or not re.fullmatch(
            r"[0-9a-f]{64}", str(value.get("tail_source_sha256") or "")
        ):
            raise SpoolConflict("live/tail match metadata is invalid")
        return True

    def record_tail_live_match(
        self,
        *,
        tail_source_key: str,
        live_source_key: str,
    ) -> None:
        """Persist one crash-safe one-to-one recovery match without raw content."""
        tail_digest = hashlib.sha256(tail_source_key.encode("utf-8")).hexdigest()
        live_digest = hashlib.sha256(live_source_key.encode("utf-8")).hexdigest()
        pairs = (
            (
                _tail_live_match_meta_key("tail", tail_source_key),
                {"live_source_sha256": live_digest},
            ),
            (
                _tail_live_match_meta_key("live", live_source_key),
                {"tail_source_sha256": tail_digest},
            ),
        )
        with self._lock, self.connection:
            for key, expected in pairs:
                row = self.connection.execute(
                    "SELECT value_json FROM spool_meta WHERE key=?", (key,)
                ).fetchone()
                if row is not None and json.loads(row["value_json"]) != expected:
                    raise SpoolConflict("tail/live source was already matched")
            now = _utc_now()
            for key, expected in pairs:
                self.connection.execute(
                    """
                    INSERT INTO spool_meta(key, value_json, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    (key, _canonical_json(expected), now),
                )

    def delete_meta(self, key: str) -> None:
        with self._lock, self.connection:
            self.connection.execute("DELETE FROM spool_meta WHERE key=?", (key,))

    def stage_final_delivery(
        self,
        *,
        platform: str,
        chat_id: str,
        platform_message_id: str,
        run_id: str,
        lease_owner: str,
        response_sha256: str,
    ) -> None:
        """Durably mark the final platform-send boundary before any send."""
        values = {
            "platform": platform,
            "chat_id": chat_id,
            "platform_message_id": platform_message_id,
            "run_id": run_id,
            "lease_owner": lease_owner,
        }
        if not all(isinstance(value, str) and value for value in values.values()):
            raise ValueError("final delivery identity is incomplete")
        if not re.fullmatch(r"[0-9a-f]{64}", str(response_sha256)):
            raise ValueError("final delivery response hash is invalid")
        key = _final_delivery_meta_key(platform, chat_id, platform_message_id)
        existing = self.get_meta(key)
        candidate = {
            "run_id": run_id,
            "lease_owner": lease_owner,
            "response_sha256": response_sha256,
        }
        if isinstance(existing, dict):
            stored = {name: existing.get(name) for name in candidate}
            if stored != candidate:
                raise SpoolConflict("final delivery replay does not match")
            return
        self.set_meta(key, {**candidate, "staged_at": _utc_now()})

    def stage_control_delivery(
        self,
        *,
        platform: str,
        chat_id: str,
        platform_message_id: str,
        run_id: str,
        lease_owner: str | None,
        response_sha256: str,
        delivery_kind: str,
        event_batch: dict[str, Any],
        run_update: dict[str, Any] | None,
    ) -> str:
        """Stage one visible non-final run outcome before the platform send."""
        values = (platform, chat_id, platform_message_id, run_id)
        if not all(isinstance(value, str) and value for value in values):
            raise ValueError("control delivery identity is incomplete")
        if delivery_kind not in {"deferred", "terminal_error"}:
            raise ValueError("control delivery kind is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", str(response_sha256)):
            raise ValueError("control delivery response hash is invalid")
        if not isinstance(event_batch, dict) or not event_batch.get("events"):
            raise ValueError("control delivery event batch is invalid")
        if delivery_kind == "terminal_error" and not isinstance(run_update, dict):
            raise ValueError("terminal control delivery requires a run update")
        if delivery_kind == "deferred" and run_update is not None:
            raise ValueError("deferred control delivery cannot terminalize the run")

        source_key = control_delivery_source_key(run_id, delivery_kind)
        prior_record = self.get_record(source_key)
        if prior_record is not None:
            return "delivered" if prior_record.state == "acknowledged" else "pending"

        key = _final_delivery_meta_key(platform, chat_id, platform_message_id)
        candidate = redact_payload(
            {
                "delivery_kind": delivery_kind,
                "run_id": run_id,
                "lease_owner": lease_owner,
                "response_sha256": response_sha256,
                "event_batch": event_batch,
                "run_update": run_update,
                "source_key": source_key,
            }
        )
        existing = self.get_meta(key)
        if isinstance(existing, dict):
            stored = {name: existing.get(name) for name in candidate}
            if stored != candidate:
                raise SpoolConflict("control delivery replay does not match")
            return "pending"
        self.set_meta(key, {**candidate, "staged_at": _utc_now()})
        return "staged"

    def confirm_control_delivery(
        self,
        *,
        platform: str,
        chat_id: str,
        platform_message_id: str,
        response_sha256: str,
        delivery_kind: str,
        ambiguous: bool = False,
    ) -> int:
        """Promote a staged control outcome into the durable backend outbox."""
        key = _final_delivery_meta_key(platform, chat_id, platform_message_id)
        existing = self.get_meta(key)
        if (
            not isinstance(existing, dict)
            or existing.get("delivery_kind") != delivery_kind
            or existing.get("response_sha256") != response_sha256
            or not existing.get("run_id")
            or not isinstance(existing.get("event_batch"), dict)
        ):
            raise SpoolConflict("control delivery confirmation does not match")
        source_key = str(
            existing.get("source_key")
            or control_delivery_source_key(str(existing["run_id"]), delivery_kind)
        )
        local_id = self.enqueue(
            kind="control_delivery_bundle",
            source_key=source_key,
            payload={
                "run_id": str(existing["run_id"]),
                "delivery_kind": delivery_kind,
                "delivery_confirmed": True,
                "delivery_ambiguous": bool(ambiguous),
                "response_sha256": response_sha256,
                "event_batch": existing["event_batch"],
                "run_update": existing.get("run_update"),
                "delivery_key": [platform, chat_id, platform_message_id],
            },
        )
        self.set_meta(
            key,
            {
                **existing,
                "confirmed_at": existing.get("confirmed_at") or _utc_now(),
                "delivery_ambiguous": bool(
                    existing.get("delivery_ambiguous") or ambiguous
                ),
            },
        )
        return local_id

    def get_final_delivery(
        self,
        *,
        platform: str,
        chat_id: str,
        platform_message_id: str,
    ) -> dict[str, Any] | None:
        value = self.get_meta(
            _final_delivery_meta_key(platform, chat_id, platform_message_id)
        )
        return value if isinstance(value, dict) else None

    def clear_final_delivery(
        self,
        *,
        platform: str,
        chat_id: str,
        platform_message_id: str,
    ) -> None:
        self.delete_meta(
            _final_delivery_meta_key(platform, chat_id, platform_message_id)
        )

    def stage_degraded_final_delivery(
        self,
        *,
        platform: str,
        chat_id: str,
        platform_message_id: str,
        response_sha256: str,
    ) -> None:
        """Stage a locally produced response while the backend is unavailable."""
        values = (platform, chat_id, platform_message_id)
        if not all(isinstance(value, str) and value for value in values):
            raise ValueError("degraded final delivery identity is incomplete")
        if not re.fullmatch(r"[0-9a-f]{64}", str(response_sha256)):
            raise ValueError("degraded final delivery response hash is invalid")
        key = _final_delivery_meta_key(platform, chat_id, platform_message_id)
        existing = self.get_meta(key)
        candidate = {
            "degraded": True,
            "response_sha256": response_sha256,
        }
        if isinstance(existing, dict):
            stored = {name: existing.get(name) for name in candidate}
            if stored != candidate:
                raise SpoolConflict("degraded final delivery replay does not match")
            return
        self.set_meta(key, {**candidate, "staged_at": _utc_now()})

    def confirm_degraded_final_delivery(
        self,
        *,
        platform: str,
        chat_id: str,
        platform_message_id: str,
        response_sha256: str,
    ) -> None:
        """Record authoritative platform confirmation for a degraded response."""
        key = _final_delivery_meta_key(platform, chat_id, platform_message_id)
        existing = self.get_meta(key)
        if (
            not isinstance(existing, dict)
            or existing.get("degraded") is not True
            or existing.get("response_sha256") != response_sha256
        ):
            raise SpoolConflict("degraded final delivery confirmation does not match")
        if existing.get("confirmed_at"):
            return
        self.set_meta(key, {**existing, "confirmed_at": _utc_now()})

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
            tombstone = self.connection.execute(
                "SELECT original_id, kind, payload_sha256 FROM outbox_tombstones "
                "WHERE source_key=?",
                (source_key,),
            ).fetchone()
            if tombstone is not None:
                if tombstone["kind"] != kind or tombstone["payload_sha256"] != digest:
                    raise SpoolConflict(
                        "source key replay does not match compacted payload"
                    )
                return int(tombstone["original_id"])
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

    def enqueue_degraded_completion(
        self,
        event_batch: dict[str, Any],
        *,
        platform: str,
        chat_id: str,
        platform_message_id: str,
    ) -> int:
        stable_key = f"{platform}\x1f{chat_id}\x1f{platform_message_id}"
        source_key = (
            "degraded_completion:"
            + hashlib.sha256(stable_key.encode("utf-8")).hexdigest()
        )
        return self.enqueue(
            kind="degraded_completion_bundle",
            source_key=source_key,
            payload={
                "event_batch": event_batch,
                "delivery_key": [platform, chat_id, platform_message_id],
            },
        )

    def find_degraded_completion(
        self,
        *,
        platform: str,
        chat_id: str,
        platform_message_id: str,
    ) -> SpoolRecord | None:
        stable_key = f"{platform}\x1f{chat_id}\x1f{platform_message_id}"
        return self.get_record(
            "degraded_completion:"
            + hashlib.sha256(stable_key.encode("utf-8")).hexdigest()
        )

    def enqueue_tool_before(
        self,
        *,
        run_id: str,
        lease_owner: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        side_effect_class: str,
        caller_idempotency_key: str | None = None,
    ) -> int:
        payload = {
            "run_id": run_id,
            "lease_owner": lease_owner,
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
        lease_owner: str,
        tool_call_id: str,
        state: str,
        result_event_id: str | None = None,
    ) -> int:
        return self.enqueue(
            kind="tool_after",
            source_key=f"tool:{run_id}:{tool_call_id}:after:{state}",
            payload={
                "run_id": run_id,
                "lease_owner": lease_owner,
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
            # Existing private spools may contain a legacy null counter even
            # though current schemas default this column to zero. Treat it as
            # the pre-attempt state instead of crashing the drain thread.
            attempt_count=int(row["attempt_count"] or 0),
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

    def rebind_pending_run_lease(self, run_id: str, lease_owner: str) -> int:
        """Fence exact pending run records to a newly acquired backend lease."""
        exact_run_id = str(run_id)
        exact_lease_owner = str(lease_owner)
        if not exact_run_id or not exact_lease_owner:
            raise ValueError("run_id and lease_owner are required")
        lease_paths = {
            "run_update": (),
            "tool_before": (),
            "tool_before_bundle": ("tool_start",),
            "tool_after": (),
            "tool_after_bundle": ("tool_update",),
            "run_completion_bundle": ("run_update",),
            "control_delivery_bundle": ("run_update",),
        }
        rebound = 0
        with self._lock, self.connection:
            rows = self.connection.execute(
                "SELECT id, kind, payload_json FROM outbox "
                "WHERE state='pending' ORDER BY id"
            ).fetchall()
            for row in rows:
                path = lease_paths.get(str(row["kind"]))
                if path is None:
                    continue
                payload = json.loads(row["payload_json"])
                target = payload
                for key in path:
                    if not isinstance(target, dict):
                        target = None
                        break
                    target = target.get(key)
                if (
                    not isinstance(target, dict)
                    or str(target.get("run_id") or "") != exact_run_id
                    or "lease_owner" not in target
                    or str(target.get("lease_owner") or "") == exact_lease_owner
                ):
                    continue
                target["lease_owner"] = exact_lease_owner
                safe_payload = redact_payload(payload)
                encoded = _canonical_json(safe_payload)
                digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
                cursor = self.connection.execute(
                    "UPDATE outbox SET payload_json=?, payload_sha256=? "
                    "WHERE id=? AND state='pending'",
                    (encoded, digest, int(row["id"])),
                )
                rebound += int(cursor.rowcount == 1)
        return rebound

    def rebind_pending_session_parent(
        self,
        session_id: str,
        parent_session_id: str | None,
    ) -> int:
        """Atomically apply one canonical parent to undelivered event batches."""
        exact_session_id = str(session_id)
        if not exact_session_id:
            raise ValueError("session_id is required")
        exact_parent_session_id = (
            str(parent_session_id) if parent_session_id is not None else None
        )
        if exact_parent_session_id == "":
            raise ValueError("parent_session_id cannot be empty")
        rebound = 0
        with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                rows = self.connection.execute(
                    "SELECT id, kind, payload_json FROM outbox "
                    "WHERE state='pending' ORDER BY id"
                ).fetchall()
                for row in rows:
                    payload = json.loads(row["payload_json"])
                    event_batch = (
                        payload
                        if str(row["kind"]) == "event_batch"
                        else payload.get("event_batch")
                    )
                    if (
                        not isinstance(event_batch, dict)
                        or str(event_batch.get("hermes_session_id") or "")
                        != exact_session_id
                        or event_batch.get("parent_hermes_session_id")
                        == exact_parent_session_id
                    ):
                        continue
                    event_batch["parent_hermes_session_id"] = exact_parent_session_id
                    safe_payload = redact_payload(payload)
                    encoded = _canonical_json(safe_payload)
                    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
                    cursor = self.connection.execute(
                        "UPDATE outbox SET payload_json=?, payload_sha256=? "
                        "WHERE id=? AND state='pending'",
                        (encoded, digest, int(row["id"])),
                    )
                    rebound += int(cursor.rowcount == 1)
                staged_rows = self.connection.execute(
                    "SELECT key, value_json FROM spool_meta "
                    "WHERE key LIKE 'final_delivery:%' ORDER BY key"
                ).fetchall()
                for row in staged_rows:
                    staged = json.loads(row["value_json"])
                    if not isinstance(staged, dict):
                        continue
                    event_batch = staged.get("event_batch")
                    if (
                        not isinstance(event_batch, dict)
                        or str(event_batch.get("hermes_session_id") or "")
                        != exact_session_id
                        or event_batch.get("parent_hermes_session_id")
                        == exact_parent_session_id
                    ):
                        continue
                    source_key = str(staged.get("source_key") or "")
                    delivered = (
                        self.connection.execute(
                            "SELECT state FROM outbox WHERE source_key=?",
                            (source_key,),
                        ).fetchone()
                        if source_key
                        else None
                    )
                    if delivered is not None and delivered["state"] == "acknowledged":
                        continue
                    event_batch["parent_hermes_session_id"] = exact_parent_session_id
                    encoded = _canonical_json(redact_payload(staged))
                    self.connection.execute(
                        "UPDATE spool_meta SET value_json=?, updated_at=? WHERE key=?",
                        (encoded, _utc_now(), str(row["key"])),
                    )
                self.connection.execute("COMMIT")
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise
        return rebound

    def matching_records(
        self,
        *,
        state: str,
        source_prefix: str,
        limit: int | None = None,
    ) -> list[SpoolRecord]:
        if state not in {"pending", "acknowledged"}:
            raise ValueError("unsupported spool state")
        bounded_limit = None if limit is None else max(1, min(int(limit), 10_000))
        sql = "SELECT * FROM outbox WHERE state=? AND source_key LIKE ? ORDER BY id"
        parameters: list[Any] = [state, f"{source_prefix}%"]
        if bounded_limit is not None:
            sql += " LIMIT ?"
            parameters.append(bounded_limit)
        rows = self.connection.execute(sql, parameters).fetchall()
        return [self._record(row) for row in rows]

    def matching_count(self, *, state: str, source_prefix: str) -> int:
        if state not in {"pending", "acknowledged"}:
            raise ValueError("unsupported spool state")
        row = self.connection.execute(
            "SELECT count(*) FROM outbox WHERE state=? AND source_key LIKE ?",
            (state, f"{source_prefix}%"),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _event_delivery(
        record: SpoolRecord,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if record.kind == "event_batch":
            return record.payload, record.receipt or {}
        if record.kind in {
            "inbound_bundle",
            "tool_before_bundle",
            "tool_after_bundle",
            "run_completion_bundle",
            "degraded_completion_bundle",
            "control_delivery_bundle",
        }:
            batch = record.payload.get("event_batch")
            receipt = (record.receipt or {}).get("ingest")
            if isinstance(batch, dict) and isinstance(receipt, dict):
                return batch, receipt
        return None

    def _index_reconciliation_delivery(
        self,
        batch: dict[str, Any],
        receipt: dict[str, Any],
    ) -> str:
        session_id = str(batch.get("hermes_session_id") or "")
        identity_id = str(receipt.get("identity_id") or "")
        events = batch.get("events")
        event_receipts = receipt.get("event_receipts")
        if (
            not session_id
            or not identity_id
            or not isinstance(events, list)
            or not isinstance(event_receipts, list)
            or len(events) != len(event_receipts)
        ):
            raise SpoolConflict("backend ingest receipt is incomplete")
        for row in event_receipts:
            if not isinstance(row, dict):
                raise SpoolConflict("backend event receipt is invalid")
            values = (
                str(row.get("event_id") or ""),
                session_id,
                identity_id,
                str(row.get("event_type") or ""),
                str(row.get("occurred_at") or ""),
                str(row.get("content_sha256") or ""),
            )
            if not all(values):
                raise SpoolConflict("backend event receipt is incomplete")
            existing = self.connection.execute(
                "SELECT event_id, session_id, identity_id, event_type, "
                "occurred_at, content_sha256 FROM reconciliation_events "
                "WHERE event_id=?",
                (values[0],),
            ).fetchone()
            if existing is not None and tuple(existing) != values:
                raise SpoolConflict("backend event receipt replay changed")
            if existing is None:
                self.connection.execute(
                    """
                    INSERT INTO reconciliation_events(
                        event_id, session_id, identity_id, event_type,
                        occurred_at, content_sha256
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
        return session_id

    def _refresh_reconciliation_state(self, session_id: str) -> None:
        rows = self.connection.execute(
            "SELECT event_id, identity_id, event_type, occurred_at, content_sha256 "
            "FROM reconciliation_events WHERE session_id=? "
            "ORDER BY occurred_at, event_id",
            (str(session_id),),
        ).fetchall()
        if not rows:
            self.connection.execute(
                "DELETE FROM reconciliation_state WHERE session_id=?",
                (str(session_id),),
            )
            return
        identities = {str(row["identity_id"]) for row in rows}
        if len(identities) != 1:
            raise SpoolConflict("backend identity changed for a session")
        receipt_rows = [
            {
                "event_id": str(row["event_id"]),
                "event_type": str(row["event_type"]),
                "occurred_at": str(row["occurred_at"]),
                "content_sha256": str(row["content_sha256"]),
            }
            for row in rows
        ]
        self.connection.execute(
            """
            INSERT INTO reconciliation_state(
                session_id, identity_id, event_count, ordered_hash, updated_at
            ) VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                identity_id=excluded.identity_id,
                event_count=excluded.event_count,
                ordered_hash=excluded.ordered_hash,
                updated_at=excluded.updated_at
            """,
            (
                str(session_id),
                identities.pop(),
                len(receipt_rows),
                ordered_reconciliation_hash(receipt_rows),
                _utc_now(),
            ),
        )

    def dirty_reconciliation_sessions(self, *, limit: int = 25) -> list[str]:
        bounded = max(1, min(int(limit), 100))
        rows = self.connection.execute(
            "SELECT session_id FROM reconciliation_dirty "
            "ORDER BY dirty_at, session_id LIMIT ?",
            (bounded,),
        ).fetchall()
        return [str(row["session_id"]) for row in rows]

    def mark_reconciliation_clean(self, session_id: str) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "DELETE FROM reconciliation_dirty WHERE session_id=?",
                (str(session_id),),
            )

    def reconciliation_expectation(self, session_id: str) -> dict[str, Any] | None:
        """Build one exact expectation without scanning lifetime history."""
        exact_session_id = str(session_id)
        if not exact_session_id:
            raise ValueError("session_id is required")
        for record in self.matching_records(state="pending", source_prefix=""):
            delivery = self._event_delivery(record)
            if (
                delivery is not None
                and str(delivery[0].get("hermes_session_id") or "") == exact_session_id
            ):
                return None

        state = self.connection.execute(
            "SELECT identity_id, event_count, ordered_hash "
            "FROM reconciliation_state WHERE session_id=?",
            (exact_session_id,),
        ).fetchone()
        if state is None:
            return None
        return {
            "identity_id": str(state["identity_id"]),
            "hermes_session_id": exact_session_id,
            "expected_event_count": int(state["event_count"]),
            "expected_ordered_hash": str(state["ordered_hash"]),
        }

    def reconciliation_expectations(self) -> dict[str, dict[str, Any]]:
        """Build all expectations for explicit backfill/reconciliation commands."""
        session_ids = {
            str(row["session_id"])
            for row in self.connection.execute(
                "SELECT session_id FROM reconciliation_state ORDER BY session_id"
            ).fetchall()
        }
        expectations: dict[str, dict[str, Any]] = {}
        for session_id in sorted(session_ids):
            expectation = self.reconciliation_expectation(session_id)
            if expectation is not None:
                expectations[session_id] = expectation
        return expectations

    @staticmethod
    def _payload_run_id(record: SpoolRecord) -> str:
        payload = record.payload
        for path in (
            (),
            ("tool_start",),
            ("tool_update",),
            ("run_update",),
        ):
            candidate: Any = payload
            for key in path:
                candidate = candidate.get(key) if isinstance(candidate, dict) else None
            if isinstance(candidate, dict) and candidate.get("run_id"):
                return str(candidate["run_id"])
        return ""

    @staticmethod
    def _inbound_receipt_run_id(record: SpoolRecord) -> str:
        if record.kind != "inbound_bundle":
            return ""
        return str(
            (((record.receipt or {}).get("run") or {}).get("run") or {}).get("id") or ""
        )

    def mark_run_terminal(self, run_id: str, *, state: str) -> None:
        if state not in {"succeeded", "blocked_side_effect", "terminal_failure"}:
            raise ValueError("run terminal state is invalid")
        exact_run_id = str(run_id)
        if not exact_run_id:
            raise ValueError("run id is required")
        self.set_meta(f"run_terminal:{exact_run_id}", {"state": state})

    def run_terminal_state(self, run_id: str) -> str | None:
        value = self.get_meta(f"run_terminal:{run_id!s}")
        state = value.get("state") if isinstance(value, dict) else None
        return (
            str(state)
            if state in {"succeeded", "blocked_side_effect", "terminal_failure"}
            else None
        )

    def is_run_terminal(self, run_id: str) -> bool:
        return self.run_terminal_state(run_id) is not None

    def has_unresolved_inbound_runs(self) -> bool:
        for record in self.matching_records(state="pending", source_prefix="inbound:"):
            if record.kind == "inbound_bundle":
                return True
        for record in self.matching_records(
            state="acknowledged",
            source_prefix="inbound:",
        ):
            run_id = self._inbound_receipt_run_id(record)
            if run_id and not self.is_run_terminal(run_id):
                return True
        return False

    def compact_reconciled_session(self, session_id: str) -> int:
        """Discard reconciled bodies while retaining fixed replay/proof rows."""
        exact_session_id = str(session_id)
        cursor = self.get_reconciliation_cursor(exact_session_id)
        expectation = self.reconciliation_expectation(exact_session_id)
        if (
            cursor is None
            or expectation is None
            or cursor
            != {
                "event_count": expectation["expected_event_count"],
                "ordered_hash": expectation["expected_ordered_hash"],
            }
        ):
            return 0
        acknowledged = self.matching_records(
            state="acknowledged",
            source_prefix="",
        )
        candidate_ids: set[int] = set()
        run_ids: set[str] = set()
        for record in acknowledged:
            delivery = self._event_delivery(record)
            if delivery is None:
                continue
            batch, _receipt = delivery
            if str(batch.get("hermes_session_id") or "") != exact_session_id:
                continue
            candidate_ids.add(record.id)
            if record.kind == "inbound_bundle":
                run_id = str(
                    (((record.receipt or {}).get("run") or {}).get("run") or {}).get(
                        "id"
                    )
                    or ""
                )
                if run_id:
                    run_ids.add(run_id)
        for record in acknowledged:
            if self._payload_run_id(record) in run_ids:
                candidate_ids.add(record.id)
        unresolved_run_ids = {
            run_id for run_id in run_ids if not self.is_run_terminal(run_id)
        }
        for record in acknowledged:
            record_run_id = self._inbound_receipt_run_id(
                record
            ) or self._payload_run_id(record)
            if record_run_id in unresolved_run_ids:
                candidate_ids.discard(record.id)
        if not candidate_ids:
            return 0
        for record in self.matching_records(state="pending", source_prefix=""):
            delivery = self._event_delivery(record)
            if (
                delivery is not None
                and str(delivery[0].get("hermes_session_id") or "") == exact_session_id
            ):
                return 0
            if self._payload_run_id(record) in run_ids:
                return 0
        compacted = 0
        with self._lock, self.connection:
            for record in acknowledged:
                if record.id not in candidate_ids:
                    continue
                row = self.connection.execute(
                    "SELECT payload_sha256 FROM outbox WHERE id=? AND state='acknowledged'",
                    (record.id,),
                ).fetchone()
                if row is None:
                    continue
                if record.kind == "inbound_bundle":
                    run_id = self._inbound_receipt_run_id(record)
                    terminal_state = self.run_terminal_state(run_id) if run_id else None
                    if run_id and terminal_state:
                        self.connection.execute(
                            """
                            INSERT INTO spool_meta(key, value_json, updated_at)
                            VALUES(?, ?, ?)
                            ON CONFLICT(key) DO UPDATE SET
                                value_json=excluded.value_json,
                                updated_at=excluded.updated_at
                            """,
                            (
                                _terminal_inbound_meta_key(record.source_key),
                                _canonical_json(
                                    {"run_id": run_id, "state": terminal_state}
                                ),
                                _utc_now(),
                            ),
                        )
                self.connection.execute(
                    """
                    INSERT INTO outbox_tombstones(
                        source_key, original_id, kind, payload_sha256, compacted_at
                    ) VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(source_key) DO NOTHING
                    """,
                    (
                        record.source_key,
                        record.id,
                        record.kind,
                        str(row["payload_sha256"]),
                        _utc_now(),
                    ),
                )
                cursor = self.connection.execute(
                    "DELETE FROM outbox WHERE id=? AND state='acknowledged'",
                    (record.id,),
                )
                compacted += int(cursor.rowcount == 1)
        if compacted:
            self.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
        return compacted

    def get_record(self, source_key: str) -> SpoolRecord | None:
        row = self.connection.execute(
            "SELECT * FROM outbox WHERE source_key=?", (source_key,)
        ).fetchone()
        if row is not None:
            return self._record(row)
        tombstone = self.connection.execute(
            "SELECT * FROM outbox_tombstones WHERE source_key=?", (source_key,)
        ).fetchone()
        if tombstone is None:
            return None
        receipt: dict[str, Any] = {"compacted": True}
        if str(tombstone["kind"]) == "inbound_bundle":
            terminal = self.get_meta(
                _terminal_inbound_meta_key(str(tombstone["source_key"]))
            )
            if (
                isinstance(terminal, dict)
                and terminal.get("run_id")
                and terminal.get("state")
                in {"succeeded", "blocked_side_effect", "terminal_failure"}
            ):
                receipt["run"] = {
                    "run": {
                        "id": str(terminal["run_id"]),
                        "state": str(terminal["state"]),
                    }
                }
        return SpoolRecord(
            id=int(tombstone["original_id"]),
            kind=str(tombstone["kind"]),
            source_key=str(tombstone["source_key"]),
            payload={},
            state="acknowledged",
            attempt_count=0,
            created_at=str(tombstone["compacted_at"]),
            last_attempt_at=None,
            acknowledged_at=str(tombstone["compacted_at"]),
            receipt=receipt,
        )

    def find_inbound(self, platform_message_id: str) -> SpoolRecord | None:
        rows = self.connection.execute(
            "SELECT * FROM outbox WHERE kind='inbound_bundle' ORDER BY id DESC"
        ).fetchall()
        for row in rows:
            record = self._record(row)
            if str(
                record.payload.get("run_start", {}).get("platform_message_id")
            ) == str(platform_message_id):
                return record
        return None

    def find_inbound_for_run(self, run_id: str) -> SpoolRecord | None:
        exact_run_id = str(run_id)
        rows = self.connection.execute(
            "SELECT * FROM outbox WHERE kind='inbound_bundle' "
            "AND state='acknowledged' ORDER BY id DESC"
        ).fetchall()
        for row in rows:
            record = self._record(row)
            if self._inbound_receipt_run_id(record) == exact_run_id:
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
            row = self.connection.execute(
                "SELECT * FROM outbox WHERE id=? AND state='acknowledged'",
                (record_id,),
            ).fetchone()
            if row is None:
                raise SpoolConflict("acknowledged outbox record is missing")
            delivery = self._event_delivery(self._record(row))
            if delivery is not None and delivery[0].get("hermes_session_id"):
                session_id = self._index_reconciliation_delivery(*delivery)
                self._refresh_reconciliation_state(session_id)
                self.connection.execute(
                    """
                    INSERT INTO reconciliation_dirty(session_id, dirty_at)
                    VALUES(?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET dirty_at=excluded.dirty_at
                    """,
                    (session_id, _utc_now()),
                )

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
        source_prefix: str = "",
    ) -> DrainResult:
        descriptor = os.open(
            self._drain_lock_path,
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        try:
            os.chmod(self._drain_lock_path, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            attempted = acknowledged = failed = 0
            records = self.matching_records(
                state="pending",
                source_prefix=source_prefix,
                limit=limit,
            )
            for record in records:
                attempted += 1
                try:
                    receipt = handler(record)
                    if not isinstance(receipt, dict):
                        raise TypeError("spool delivery must return a receipt object")
                    self.acknowledge(record.id, receipt)
                    acknowledged += 1
                except Exception:  # noqa: BLE001 - external delivery boundary.
                    self.record_failure(record.id)
                    failed += 1
                    break
            return DrainResult(attempted, acknowledged, failed)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

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

    def get_latest_cached_context(
        self, *, logical_conversation_id: str
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT context_cache.packet_json
            FROM context_cache
            JOIN session_lineage
              ON session_lineage.session_id = context_cache.session_id
            WHERE session_lineage.logical_conversation_id = ?
            ORDER BY context_cache.fetched_at DESC, context_cache.session_id DESC
            LIMIT 1
            """,
            (logical_conversation_id,),
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
