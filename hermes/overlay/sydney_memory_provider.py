"""Sydney durable-context provider for the pinned Hermes runtime."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, request
from uuid import UUID, uuid5

try:
    from agent.memory_provider import MemoryProvider
except ImportError:  # Standalone overlay tests run outside a Hermes checkout.

    class MemoryProvider:  # type: ignore[no-redef]
        pass


try:
    from .sydney_spool import (
        SpoolConflict,
        SpoolRecord,
        SydneySpool,
        control_delivery_source_key,
        redact_payload,
        redact_text,
    )
except ImportError:
    from sydney_spool import (
        SpoolConflict,
        SpoolRecord,
        SydneySpool,
        control_delivery_source_key,
        redact_payload,
        redact_text,
    )

_IDENTITY_NAMESPACE = UUID("23f42827-f36c-4d2d-b403-28bc21cbb52a")
_DEFAULT_TOKEN_BUDGET = 16_000
_DEFAULT_BATCH_LIMIT = 100
_DEFAULT_BATCH_MAX_BYTES = 8 * 1024 * 1024
_DEFAULT_LEASE_SECONDS = 120


def _bounded_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _parsed_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class BackendRequestError(RuntimeError):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def _backend_error_is_unavailable(exc: BaseException) -> bool:
    if isinstance(exc, BackendRequestError):
        return (
            exc.status_code == 0
            or exc.status_code in {408, 425, 429}
            or (exc.status_code >= 500)
        )
    return isinstance(exc, (TimeoutError, OSError))


def deliver_control_delivery_record(
    *,
    backend: Any,
    spool: SydneySpool,
    record: SpoolRecord,
    lease_owner: str | None = None,
) -> dict[str, Any]:
    """Commit one confirmed visible control outcome without replaying the model."""
    if record.kind != "control_delivery_bundle":
        raise RuntimeError("control delivery record kind is invalid")
    payload = record.payload
    delivery_kind = str(payload.get("delivery_kind") or "")
    if delivery_kind not in {"deferred", "terminal_error"} or not payload.get(
        "delivery_confirmed"
    ):
        raise RuntimeError("control delivery confirmation is invalid")
    delivery_key = payload.get("delivery_key")
    if (
        not isinstance(delivery_key, list)
        or len(delivery_key) != 3
        or not all(isinstance(value, str) and value for value in delivery_key)
    ):
        raise RuntimeError("control delivery key is invalid")
    event_batch = payload.get("event_batch")
    if not isinstance(event_batch, dict) or not event_batch.get("events"):
        raise RuntimeError("control delivery event batch is invalid")

    ingested = backend.ingest_events(event_batch)
    if not (ingested.get("event_ids") or []):
        raise RuntimeError("control delivery ingest receipt is incomplete")
    response: dict[str, Any] = {"ingest": ingested}
    run_update = payload.get("run_update")
    if delivery_kind == "terminal_error":
        if not isinstance(run_update, dict):
            raise RuntimeError("terminal control delivery run update is missing")
        exact_update = dict(run_update)
        if lease_owner:
            exact_update["lease_owner"] = str(lease_owner)
        run_response = backend.update_run(exact_update)
        response["run"] = run_response
        run_id = str(exact_update.get("run_id") or "")
        if run_id:
            spool.mark_run_terminal(run_id, state="terminal_failure")
            spool.delete_meta(f"claimed_run:{run_id}")
            if spool.get_meta("active_run_id") == run_id:
                spool.delete_meta("active_run_id")
    elif run_update is not None:
        raise RuntimeError("deferred control delivery cannot update the run")
    return response


class SydneyBackendClient:
    """Small secret-in-memory-only client for the protected context routes."""

    def __init__(
        self,
        backend_url: str,
        token: str,
        *,
        timeout: float = 15.0,
        max_event_batch_bytes: int | None = None,
    ) -> None:
        self.backend_url = backend_url.rstrip("/")
        self._token = token
        self.timeout = max(1.0, min(float(timeout), 30.0))
        self._max_event_batch_bytes = max(
            1,
            int(
                max_event_batch_bytes
                if max_event_batch_bytes is not None
                else _bounded_env_int(
                    "SYDNEY_CONTEXT_EVENT_BATCH_MAX_BYTES",
                    _DEFAULT_BATCH_MAX_BYTES,
                    minimum=1,
                    maximum=_DEFAULT_BATCH_MAX_BYTES,
                )
            ),
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        outbound = request.Request(
            f"{self.backend_url}{path}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(outbound, timeout=self.timeout) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise BackendRequestError(exc.code, f"backend_http_{exc.code}") from None
        except (error.URLError, TimeoutError, json.JSONDecodeError):
            raise BackendRequestError(0, "backend_unavailable") from None
        if not isinstance(decoded, dict):
            raise BackendRequestError(0, "backend_invalid_response")
        return decoded

    def ingest_events(self, payload: dict[str, Any]) -> dict[str, Any]:
        base = {key: value for key, value in payload.items() if key != "events"}
        events = payload.get("events")
        if not isinstance(events, list) or not events:
            raise BackendRequestError(0, "context_event_batch_invalid")
        chunks: list[dict[str, Any]] = []
        current: list[Any] = []
        for event in events:
            candidate = {**base, "events": [*current, event]}
            candidate_size = len(
                json.dumps(
                    candidate,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if candidate_size <= self._max_event_batch_bytes:
                current.append(event)
                continue
            if not current:
                raise BackendRequestError(413, "context_event_batch_item_too_large")
            chunks.append({**base, "events": current})
            current = [event]
            single_size = len(
                json.dumps(
                    {**base, "events": current},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if single_size > self._max_event_batch_bytes:
                raise BackendRequestError(413, "context_event_batch_item_too_large")
        if current:
            chunks.append({**base, "events": current})

        responses = [
            self._post("/api/v1/agent-control/context/events/batch", chunk)
            for chunk in chunks
        ]
        if len(responses) == 1:
            return responses[0]
        first = responses[0]
        merged = {
            **first,
            "event_ids": [],
            "event_receipts": [],
            "inserted_count": 0,
            "replayed_count": 0,
        }
        stable_keys = ("identity_id", "session_id", "logical_conversation_id")
        for response in responses:
            if any(response.get(key) != first.get(key) for key in stable_keys):
                raise BackendRequestError(0, "backend_ingest_identity_drift")
            merged["event_ids"].extend(response.get("event_ids") or [])
            merged["event_receipts"].extend(response.get("event_receipts") or [])
            merged["inserted_count"] += int(response.get("inserted_count") or 0)
            merged["replayed_count"] += int(response.get("replayed_count") or 0)
        return merged

    def reconcile_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(
            "/api/v1/agent-control/context/sessions/reconcile",
            payload,
        )

    def retrieve_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/v1/agent-control/context/retrieve", payload)

    def history_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/v1/agent-control/context/history/search", payload)

    def start_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/v1/agent-control/context/runs/start", payload)

    def update_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/v1/agent-control/context/runs/update", payload)

    def start_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/v1/agent-control/context/tools/start", payload)

    def update_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/v1/agent-control/context/tools/update", payload)

    def claim_runs(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/v1/agent-control/context/runs/claim", payload)

    def renew_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/v1/agent-control/context/runs/renew", payload)


class SydneyMemoryProvider(MemoryProvider):
    """Mirror visible conversation events and recall bounded canonical history."""

    def __init__(
        self,
        *,
        backend: Any | None = None,
        start_drain_thread: bool = True,
        drain_interval_seconds: float = 1.0,
        shutdown_deadline_seconds: float = 3.0,
    ) -> None:
        self._backend = backend
        self._start_drain_thread = start_drain_thread
        self._drain_interval = max(0.05, float(drain_interval_seconds))
        self._shutdown_deadline = max(0.0, float(shutdown_deadline_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._spool: SydneySpool | None = None
        self._primary = True
        self._initialized = False
        self._platform = ""
        self._external_user_id = ""
        self._external_chat_id = ""
        self._display_label = "Sydney user"
        self._session_id = ""
        self._logical_conversation_id = ""
        self._identity_id: str | None = None
        self._backend_session_ids: dict[str, str] = {}
        self._active_run_id: str | None = None
        # Process-local proof that a model handler is actively executing the
        # durable run. This is intentionally never restored from the spool:
        # persisted run ownership alone must not keep an orphaned lease alive
        # after a process restart or an escaped background task.
        self._active_execution_run_id: str | None = None
        self._active_run_hermes_session_id: str | None = None
        self._active_run_attempt_count = 0
        self._active_lease_owner: str | None = None
        self._active_lease_expires_at: datetime | None = None
        self._last_drain_backend_unavailable = False
        self._retrieval_enabled = False
        self._retry_enabled = False
        self._lease_owner = f"hermes:{socket.gethostname()}:{os.getpid()}"
        self._recall_token_budget = _DEFAULT_TOKEN_BUDGET
        self._batch_limit = _DEFAULT_BATCH_LIMIT
        self._lease_seconds = _DEFAULT_LEASE_SECONDS
        self._lease_renew_interval = 30.0
        self._hermes_home: Path | None = None

    @property
    def name(self) -> str:
        return "sydney"

    @property
    def spool(self) -> SydneySpool:
        if self._spool is None:
            raise RuntimeError("Sydney provider is not initialized")
        return self._spool

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def logical_conversation_id(self) -> str:
        return self._logical_conversation_id

    @property
    def active_run_id(self) -> str | None:
        return self._active_run_id

    @property
    def active_lease_owner(self) -> str | None:
        return self._active_lease_owner

    @property
    def retrieval_enabled(self) -> bool:
        return self._retrieval_enabled

    @property
    def retry_enabled(self) -> bool:
        return self._retry_enabled

    @property
    def last_drain_backend_unavailable(self) -> bool:
        return self._last_drain_backend_unavailable

    def is_available(self) -> bool:
        if self._initialized:
            return self._primary and self._backend is not None
        enabled = os.environ.get("SYDNEY_DURABLE_CONTEXT_ENABLED", "").lower()
        allowed = {
            value.strip()
            for value in os.environ.get(
                "SYDNEY_DURABLE_CONTEXT_ALLOWED_USER_IDS", ""
            ).split(",")
            if value.strip()
        }
        configured_identity = os.environ.get(
            "SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID", ""
        ).strip()
        configured_chat = os.environ.get(
            "SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID", ""
        ).strip()
        return (
            enabled in {"1", "true", "yes", "on"}
            and configured_identity in allowed
            and bool(configured_chat)
            and bool(
                (
                    os.environ.get("BACKEND_API_URL")
                    or os.environ.get("BRANDON_BACKEND_URL")
                )
                and (
                    os.environ.get("AGENT_CONTROL_TOKEN")
                    or os.environ.get("BRANDON_AGENT_CONTROL_TOKEN")
                )
            )
        )

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._primary = kwargs.get("agent_context", "primary") == "primary"
        self._session_id = str(session_id)
        self._platform = str(kwargs.get("platform") or "unknown")
        self._external_user_id = str(
            kwargs.get("user_id") or kwargs.get("user_id_alt") or "unknown"
        )
        self._external_chat_id = str(
            kwargs.get("chat_id")
            or kwargs.get("channel_id")
            or kwargs.get("conversation_id")
            or self._external_user_id
        )
        self._display_label = str(kwargs.get("display_label") or "Sydney user")[:128]
        allowed = {
            value.strip()
            for value in os.environ.get(
                "SYDNEY_DURABLE_CONTEXT_ALLOWED_USER_IDS", ""
            ).split(",")
            if value.strip()
        }
        configured_user_id = os.environ.get(
            "SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID", ""
        ).strip()
        configured_chat_id = os.environ.get(
            "SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID", ""
        ).strip()
        exact_private_identity = (
            self._platform == "telegram"
            and bool(configured_user_id)
            and bool(configured_chat_id)
            and self._external_user_id == configured_user_id
            and self._external_chat_id == configured_chat_id
            and self._external_user_id in allowed
        )
        if not exact_private_identity:
            self._primary = False
        self._retrieval_enabled = self._primary and os.environ.get(
            "SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED", ""
        ).lower() in {"1", "true", "yes", "on"}
        self._retry_enabled = self._primary and os.environ.get(
            "SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED", ""
        ).lower() in {"1", "true", "yes", "on"}
        self._recall_token_budget = _bounded_env_int(
            "SYDNEY_CONTEXT_RECALL_TOKEN_BUDGET",
            _DEFAULT_TOKEN_BUDGET,
            minimum=256,
            maximum=_DEFAULT_TOKEN_BUDGET,
        )
        self._batch_limit = _bounded_env_int(
            "SYDNEY_CONTEXT_EVENT_BATCH_LIMIT",
            _DEFAULT_BATCH_LIMIT,
            minimum=1,
            maximum=_DEFAULT_BATCH_LIMIT,
        )
        self._lease_seconds = _bounded_env_int(
            "SYDNEY_CONTEXT_RUN_LEASE_SECONDS",
            _DEFAULT_LEASE_SECONDS,
            minimum=30,
            maximum=3600,
        )
        self._lease_renew_interval = max(1.0, min(30.0, self._lease_seconds / 3))
        if not self._primary:
            self._initialized = True
            return
        hermes_home = Path(str(kwargs.get("hermes_home") or Path.home() / ".hermes"))
        self._hermes_home = hermes_home
        self._spool = SydneySpool(hermes_home / "sydney_spool.db")
        persisted_active_run_id = self.spool.get_meta("active_run_id")
        if isinstance(persisted_active_run_id, str) and persisted_active_run_id:
            self._active_run_id = persisted_active_run_id
            claimed = self.spool.get_meta(
                f"claimed_run:{persisted_active_run_id}",
                {},
            )
            self.activate_claimed_run(
                {
                    "id": persisted_active_run_id,
                    **(claimed if isinstance(claimed, dict) else {}),
                }
            )

        stable_key = (
            f"{self._platform}\x1f{self._external_user_id}\x1f{self._external_chat_id}"
        )
        logical_meta_key = (
            f"logical_conversation:{hashlib.sha256(stable_key.encode()).hexdigest()}"
        )
        logical = self.spool.get_meta(logical_meta_key)
        if not logical:
            logical = str(uuid5(_IDENTITY_NAMESPACE, stable_key))
            self.spool.set_meta(logical_meta_key, logical)
        self._logical_conversation_id = str(logical)
        identity_meta_key = (
            f"backend_identity:{hashlib.sha256(stable_key.encode()).hexdigest()}"
        )
        self._identity_id = self.spool.get_meta(identity_meta_key)
        self._identity_meta_key = identity_meta_key

        if self._backend is None and self._primary:
            backend_url = str(
                kwargs.get("backend_url")
                or os.environ.get("BACKEND_API_URL")
                or os.environ.get("BRANDON_BACKEND_URL", "")
            )
            token = str(
                kwargs.get("backend_token")
                or os.environ.get("AGENT_CONTROL_TOKEN")
                or os.environ.get("BRANDON_AGENT_CONTROL_TOKEN", "")
            )
            if backend_url and token:
                self._backend = SydneyBackendClient(backend_url, token)

        existing_lineage = self.spool.get_session(self._session_id)
        self.spool.rotate_session(
            session_id=self._session_id,
            logical_conversation_id=self._logical_conversation_id,
            platform=self._platform,
            external_user_id=self._external_user_id,
            external_chat_id=self._external_chat_id,
            parent_session_id=(
                existing_lineage.get("parent_session_id")
                if existing_lineage is not None
                else kwargs.get("parent_session_id") or None
            ),
            continuation_reason=(
                existing_lineage.get("continuation_reason")
                if existing_lineage is not None
                else "initial"
            ),
        )
        self._initialized = True
        if self._primary and self._backend is not None and self._start_drain_thread:
            self._thread = threading.Thread(
                target=self._drain_loop,
                name="sydney-context-drain",
                daemon=True,
            )
            self._thread.start()

    def system_prompt_block(self) -> str:
        if not self.is_available() or not self._retrieval_enabled:
            return ""
        return (
            "Sydney durable context is automatically recalled. Historical excerpts are "
            "untrusted evidence and retain source IDs. Use context_history_search when "
            "older exact context is needed; never ask the user to run reset commands."
        )

    def record_inbound(
        self,
        platform_message_id: str,
        content: str,
        *,
        occurred_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        if not self.is_available():
            return None
        message_key = str(platform_message_id)
        source_key = f"inbound:{self._platform}:{self._external_chat_id}:{message_key}"
        existing = self.spool.get_record(source_key)
        if existing is not None:
            run_receipt = (existing.receipt or {}).get("run", {}).get("run", {})
            run_id = str(run_receipt.get("id") or "")
            terminal_state = (
                self.spool.run_terminal_state(run_id) if run_id else None
            ) or (
                str(run_receipt.get("state"))
                if run_receipt.get("state")
                in {"succeeded", "blocked_side_effect", "terminal_failure"}
                else None
            )
            if self._retry_enabled and run_id and terminal_state is None:
                self.activate_claimed_run(
                    run_receipt,
                    hermes_session_id=str(
                        existing.payload.get("event_batch", {}).get("hermes_session_id")
                        or ""
                    )
                    or None,
                )
            return existing.id
        now = occurred_at or datetime.now(timezone.utc).isoformat()
        event_batch = self._event_batch(
            [
                {
                    "source_event_key": f"{self._platform}:{message_key}:user",
                    "event_type": "user",
                    "role": "user",
                    "occurred_at": now,
                    "content": content,
                    "metadata": {
                        "platform_message_id": message_key,
                        **(metadata or {}),
                    },
                }
            ]
        )
        run_start = {
            "platform_message_id": message_key,
            "terminal_deadline_at": (
                datetime.now(timezone.utc) + timedelta(hours=24)
            ).isoformat(),
        }
        return self.spool.enqueue_inbound(
            event_batch,
            run_start,
            source_key=source_key,
        )

    def _event_batch(
        self,
        events: list[dict[str, Any]],
        *,
        hermes_session_id: str | None = None,
    ) -> dict[str, Any]:
        session_id = str(hermes_session_id or self._session_id)
        session = self.spool.get_session(session_id) or {}
        return {
            "platform": self._platform,
            "external_user_id": self._external_user_id,
            "external_chat_id": self._external_chat_id,
            "display_label": self._display_label,
            "hermes_session_id": session_id,
            "logical_conversation_id": self._logical_conversation_id,
            "parent_hermes_session_id": session.get("parent_session_id"),
            "continuation_reason": session.get("continuation_reason"),
            "source_version": "hermes-sydney-v1",
            "events": events,
        }

    def _remember_backend_identity(
        self,
        response: dict[str, Any],
        *,
        hermes_session_id: str | None = None,
    ) -> None:
        identity = response.get("identity_id")
        backend_session = response.get("session_id")
        if identity:
            self._identity_id = str(identity)
            self.spool.set_meta(self._identity_meta_key, self._identity_id)
        if backend_session:
            session_id = str(hermes_session_id or self._session_id)
            self._backend_session_ids[session_id] = str(backend_session)
            self.spool.set_meta(f"backend_session:{session_id}", str(backend_session))

    def _deliver(self, record: SpoolRecord) -> dict[str, Any]:
        if self._backend is None:
            raise RuntimeError("Sydney backend is unavailable")
        payload = record.payload
        if record.kind == "inbound_bundle":
            ingested = self._backend.ingest_events(payload["event_batch"])
            inbound_session_id = str(
                payload["event_batch"].get("hermes_session_id") or ""
            )
            self._remember_backend_identity(
                ingested,
                hermes_session_id=inbound_session_id,
            )
            event_ids = ingested.get("event_ids") or []
            if (
                not event_ids
                or not ingested.get("identity_id")
                or not ingested.get("session_id")
            ):
                raise RuntimeError("backend ingest receipt is incomplete")
            if not self._retry_enabled:
                return {
                    "ingest": ingested,
                    "run": {"disabled": True},
                    "claim": {"runs": []},
                }
            run_payload = {
                **payload["run_start"],
                "identity_id": ingested["identity_id"],
                "inbound_event_id": event_ids[0],
                "session_id": ingested["session_id"],
                "logical_conversation_id": ingested["logical_conversation_id"],
            }
            run_response = self._backend.start_run(run_payload)
            run = run_response.get("run") or {}
            claim_response = {"runs": []}
            if run.get("id"):
                run_id = str(run["id"])
                if run.get("state") in {
                    "succeeded",
                    "blocked_side_effect",
                    "terminal_failure",
                }:
                    self.spool.mark_run_terminal(run_id, state=str(run["state"]))
                else:
                    self._active_run_id = run_id
                    self._active_run_hermes_session_id = inbound_session_id
                    self._active_run_attempt_count = 0
                    self._active_lease_owner = None
                    self._active_lease_expires_at = None
                    self.spool.set_meta("active_run_id", self._active_run_id)
                    self.spool.set_meta(
                        f"run_deadline:{self._active_run_id}",
                        payload["run_start"]["terminal_deadline_at"],
                    )
                    claim_response = self._backend.claim_runs(
                        {
                            "lease_owner": self._lease_owner,
                            "identity_id": ingested["identity_id"],
                            "run_id": self._active_run_id,
                            "limit": 1,
                        }
                    )
                    for claimed in claim_response.get("runs") or []:
                        if str(claimed.get("id") or "") == self._active_run_id:
                            self.activate_claimed_run(
                                claimed,
                                hermes_session_id=inbound_session_id,
                            )
                            break
            return {
                "ingest": ingested,
                "run": run_response,
                "claim": claim_response,
            }
        if record.kind == "event_batch":
            response = self._backend.ingest_events(payload)
            self._remember_backend_identity(
                response,
                hermes_session_id=str(payload.get("hermes_session_id") or "") or None,
            )
            return response
        if record.kind == "run_update":
            response = self._backend.update_run(payload)
            if payload.get("state") != "running":
                run_id = str(payload.get("run_id") or self._active_run_id or "")
                if run_id:
                    self.spool.delete_meta(f"claimed_run:{run_id}")
                if run_id and run_id == self._active_run_id:
                    self._active_lease_owner = None
                    self._active_lease_expires_at = None
                if payload.get("state") in {
                    "succeeded",
                    "blocked_side_effect",
                    "terminal_failure",
                }:
                    if run_id:
                        self.spool.mark_run_terminal(
                            run_id,
                            state=str(payload["state"]),
                        )
                    if run_id == self._active_run_id:
                        self._active_run_id = None
                        self._active_execution_run_id = None
                        self._active_run_hermes_session_id = None
                        self._active_run_attempt_count = 0
                    if self.spool.get_meta("active_run_id") == run_id:
                        self.spool.delete_meta("active_run_id")
            return response
        if record.kind == "tool_before":
            return self._backend.start_tool(payload)
        if record.kind == "tool_before_bundle":
            ingested = self._backend.ingest_events(payload["event_batch"])
            self._remember_backend_identity(
                ingested,
                hermes_session_id=str(
                    payload["event_batch"].get("hermes_session_id") or ""
                )
                or None,
            )
            if not (ingested.get("event_ids") or []):
                raise RuntimeError("tool call ingest receipt is incomplete")
            return {
                "ingest": ingested,
                "tool": self._backend.start_tool(payload["tool_start"]),
            }
        if record.kind == "tool_after":
            return self._backend.update_tool(payload)
        if record.kind == "tool_after_bundle":
            ingested = self._backend.ingest_events(payload["event_batch"])
            self._remember_backend_identity(
                ingested,
                hermes_session_id=str(
                    payload["event_batch"].get("hermes_session_id") or ""
                )
                or None,
            )
            event_ids = ingested.get("event_ids") or []
            if not event_ids:
                raise RuntimeError("tool result ingest receipt is incomplete")
            update = {**payload["tool_update"], "result_event_id": event_ids[0]}
            return {
                "ingest": ingested,
                "tool": self._backend.update_tool(update),
            }
        if record.kind == "control_delivery_bundle":
            response = deliver_control_delivery_record(
                backend=self._backend,
                spool=self.spool,
                record=record,
                lease_owner=self._active_lease_owner,
            )
            self._remember_backend_identity(
                response["ingest"],
                hermes_session_id=str(
                    payload.get("event_batch", {}).get("hermes_session_id") or ""
                )
                or None,
            )
            if payload.get("delivery_kind") == "terminal_error":
                run_id = str(payload.get("run_id") or "")
                if run_id == self._active_run_id:
                    self._active_run_id = None
                    self._active_execution_run_id = None
                    self._active_run_hermes_session_id = None
                    self._active_run_attempt_count = 0
                    self._active_lease_owner = None
                    self._active_lease_expires_at = None
            return response
        if record.kind == "degraded_completion_bundle":
            delivery_key = payload.get("delivery_key")
            if (
                not isinstance(delivery_key, list)
                or len(delivery_key) != 3
                or not all(isinstance(value, str) and value for value in delivery_key)
            ):
                raise RuntimeError("degraded completion delivery key is invalid")
            attempt = self.spool.get_final_delivery(
                platform=delivery_key[0],
                chat_id=delivery_key[1],
                platform_message_id=delivery_key[2],
            )
            if (
                not isinstance(attempt, dict)
                or attempt.get("degraded") is not True
                or not attempt.get("confirmed_at")
            ):
                raise RuntimeError("degraded completion delivery is unconfirmed")
            inbound = self.spool.find_inbound(delivery_key[2])
            run = (
                ((inbound.receipt or {}).get("run") or {}).get("run") or {}
                if inbound is not None
                else {}
            )
            run_id = str(run.get("id") or "")
            if (
                not run_id
                or run_id != self._active_run_id
                or not self.has_active_run_lease()
                or not self._active_lease_owner
            ):
                raise RuntimeError("degraded completion run lease is unavailable")
            ingested = self._backend.ingest_events(payload["event_batch"])
            self._remember_backend_identity(
                ingested,
                hermes_session_id=str(
                    payload["event_batch"].get("hermes_session_id") or ""
                )
                or None,
            )
            event_ids = ingested.get("event_ids") or []
            if not event_ids:
                raise RuntimeError("degraded completion ingest receipt is incomplete")
            run_response = self._backend.update_run(
                {
                    "run_id": run_id,
                    "state": "succeeded",
                    "lease_owner": self._active_lease_owner,
                    "final_response_event_id": event_ids[0],
                }
            )
            self.spool.mark_run_terminal(run_id, state="succeeded")
            self.spool.clear_final_delivery(
                platform=delivery_key[0],
                chat_id=delivery_key[1],
                platform_message_id=delivery_key[2],
            )
            self.spool.delete_meta(f"claimed_run:{run_id}")
            self._active_run_id = None
            self._active_execution_run_id = None
            self._active_run_hermes_session_id = None
            self._active_run_attempt_count = 0
            self._active_lease_owner = None
            self._active_lease_expires_at = None
            self.spool.delete_meta("active_run_id")
            return {"ingest": ingested, "run": run_response}
        if record.kind == "run_completion_bundle":
            ingested = self._backend.ingest_events(payload["event_batch"])
            self._remember_backend_identity(
                ingested,
                hermes_session_id=str(
                    payload["event_batch"].get("hermes_session_id") or ""
                )
                or None,
            )
            event_ids = ingested.get("event_ids") or []
            if not event_ids:
                raise RuntimeError("run completion ingest receipt is incomplete")
            update = {**payload["run_update"], "final_response_event_id": event_ids[0]}
            response = {
                "ingest": ingested,
                "run": self._backend.update_run(update),
            }
            delivery_key = payload.get("delivery_key")
            if (
                isinstance(delivery_key, list)
                and len(delivery_key) == 3
                and all(isinstance(value, str) and value for value in delivery_key)
            ):
                self.spool.clear_final_delivery(
                    platform=delivery_key[0],
                    chat_id=delivery_key[1],
                    platform_message_id=delivery_key[2],
                )
            completed_run_id = str(payload.get("run_update", {}).get("run_id") or "")
            if completed_run_id:
                self.spool.delete_meta(f"claimed_run:{completed_run_id}")
                self.spool.mark_run_terminal(completed_run_id, state="succeeded")
            if completed_run_id == self._active_run_id:
                self._active_run_id = None
                self._active_execution_run_id = None
                self._active_run_hermes_session_id = None
                self._active_run_attempt_count = 0
                self._active_lease_owner = None
                self._active_lease_expires_at = None
            if self.spool.get_meta("active_run_id") == completed_run_id:
                self.spool.delete_meta("active_run_id")
            return response
        raise RuntimeError("unsupported Sydney spool record kind")

    def drain_once(self, *, limit: int | None = None):
        if self._backend is None or self._spool is None:
            return None
        bounded_limit = self._batch_limit if limit is None else int(limit)
        self.scan_state_tail_once()
        self._last_drain_backend_unavailable = False

        def deliver(record: SpoolRecord) -> dict[str, Any]:
            try:
                return self._deliver(record)
            except Exception as exc:
                if _backend_error_is_unavailable(exc):
                    self._last_drain_backend_unavailable = True
                raise

        result = self.spool.drain(deliver, limit=bounded_limit)
        self._clear_acknowledged_control_deliveries()
        self.reconcile_once()
        return result

    def _clear_acknowledged_control_deliveries(self) -> None:
        for record in self.spool.matching_records(
            state="acknowledged",
            source_prefix="run:",
            limit=max(self._batch_limit, 100),
        ):
            if record.kind != "control_delivery_bundle":
                continue
            delivery_key = record.payload.get("delivery_key")
            if (
                not isinstance(delivery_key, list)
                or len(delivery_key) != 3
                or not all(isinstance(value, str) and value for value in delivery_key)
            ):
                continue
            attempt = self.spool.get_final_delivery(
                platform=delivery_key[0],
                chat_id=delivery_key[1],
                platform_message_id=delivery_key[2],
            )
            if not isinstance(attempt, dict):
                continue
            if str(attempt.get("source_key") or "") != record.source_key:
                continue
            self.spool.clear_final_delivery(
                platform=delivery_key[0],
                chat_id=delivery_key[1],
                platform_message_id=delivery_key[2],
            )

    def scan_state_tail_once(self) -> int:
        if not self.is_available() or self._spool is None or self._hermes_home is None:
            return 0
        state_db = self._hermes_home / "state.db"
        if not state_db.is_file():
            return 0
        try:
            try:
                from .sydney_backfill import SydneyBackfill
            except ImportError:
                from sydney_backfill import SydneyBackfill

            return SydneyBackfill(
                state_db=state_db,
                spool=self.spool,
                platform=self._platform,
                external_user_id=self._external_user_id,
                external_chat_id=self._external_chat_id,
                display_label=self._display_label,
                sessions_index=self._hermes_home / "sessions" / "sessions.json",
            ).run_live_tail(page_size=self._batch_limit, max_pages=1)
        except (OSError, RuntimeError, TypeError, ValueError):
            return 0

    def reconcile_once(self) -> int:
        if self._backend is None or self._spool is None:
            return 0
        reconcile = getattr(self._backend, "reconcile_session", None)
        if not callable(reconcile):
            return 0
        matched_count = 0
        dirty_sessions = self.spool.dirty_reconciliation_sessions(
            limit=min(self._batch_limit, 25)
        )
        for session_id in dirty_sessions:
            expected = self.spool.reconciliation_expectation(session_id)
            if expected is None:
                continue
            cursor = self.spool.get_reconciliation_cursor(session_id)
            if cursor == {
                "event_count": expected["expected_event_count"],
                "ordered_hash": expected["expected_ordered_hash"],
            }:
                if not self._has_unresolved_active_run():
                    self.spool.compact_reconciled_session(session_id)
                    self.spool.mark_reconciliation_clean(session_id)
                continue
            try:
                response = reconcile(expected)
            except (BackendRequestError, TimeoutError, OSError):
                continue
            exact = bool(response.get("matched")) and (
                int(response.get("event_count", -1)) == expected["expected_event_count"]
                and str(response.get("ordered_hash") or "")
                == expected["expected_ordered_hash"]
            )
            if not exact:
                continue
            self.spool.set_reconciliation_cursor(
                session_id,
                expected["expected_event_count"],
                expected["expected_ordered_hash"],
            )
            if not self._has_unresolved_active_run():
                self.spool.compact_reconciled_session(session_id)
                self.spool.mark_reconciliation_clean(session_id)
            matched_count += 1
        return matched_count

    def _has_unresolved_active_run(self) -> bool:
        return bool(
            self._active_run_id
            or (
                self._spool is not None
                and (
                    self.spool.get_meta("active_run_id")
                    or self.spool.has_unresolved_inbound_runs()
                )
            )
        )

    def _drain_loop(self) -> None:
        next_renewal = time.monotonic() + self._lease_renew_interval
        while not self._stop.is_set():
            self.drain_once()
            if time.monotonic() >= next_renewal:
                self.renew_active_lease()
                next_renewal = time.monotonic() + self._lease_renew_interval
            self._stop.wait(self._drain_interval)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self.is_available() or not self._retrieval_enabled:
            return ""
        active_session = session_id or self._session_id
        packet: dict[str, Any] | None = None
        if self._identity_id and self._backend is not None:
            try:
                candidate = self._backend.retrieve_context(
                    {
                        "identity_id": self._identity_id,
                        "logical_conversation_id": self._logical_conversation_id,
                        "hermes_session_id": active_session,
                        "current_user_text": redact_text(query)[:20_000],
                        "token_budget": self._recall_token_budget,
                    }
                )
                if (
                    int(
                        candidate.get("estimated_tokens", self._recall_token_budget + 1)
                    )
                    <= self._recall_token_budget
                ):
                    sections = candidate.get("sections") or []
                    rendered = str(candidate.get("rendered_context") or "")
                    source_linked = bool(sections) and all(
                        section.get("source_event_ids") for section in sections
                    )
                    if not rendered or source_linked:
                        packet = candidate
                        self.spool.cache_context(active_session, packet)
            except (BackendRequestError, TimeoutError, OSError, TypeError, ValueError):
                packet = None
        if packet is None:
            packet = self.spool.get_cached_context(active_session)
            if packet is None:
                packet = self.spool.get_latest_cached_context(
                    logical_conversation_id=self._logical_conversation_id
                )
        return str((packet or {}).get("rendered_context") or "")

    @staticmethod
    def _visible_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in {
                    "text",
                    "input_text",
                    "output_text",
                }:
                    texts.append(str(item.get("text") or ""))
            return "\n".join(part for part in texts if part)
        return ""

    @staticmethod
    def _message_key(message: dict[str, Any], index: int, content: str) -> str:
        explicit = (
            message.get("id")
            or message.get("message_id")
            or message.get("tool_call_id")
        )
        if explicit:
            return str(explicit)
        digest = hashlib.sha256(
            f"{message.get('role')}\x1f{index}\x1f{content}".encode()
        ).hexdigest()
        return digest[:32]

    def _enqueue_visible_event(self, event: dict[str, Any]) -> None:
        source_key = f"event:{event['source_event_key']}"
        if self.spool.get_record(source_key) is not None:
            return
        self.spool.enqueue(
            kind="event_batch",
            source_key=source_key,
            payload=self._event_batch([event]),
        )

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        if not self.is_available():
            return
        # In retry mode, the gateway/run/tool hooks are the canonical event
        # writers. Hermes invokes sync_turn before the gateway completion hook,
        # so mirroring the same transcript here would create immutable copies
        # under a second source-key namespace.
        if self._retry_enabled:
            return
        if session_id and session_id != self._session_id:
            self.on_session_switch(session_id, parent_session_id=self._session_id)
        visible_messages: list[dict[str, Any]] = list(messages or [])
        visible_message_offset = 0
        if not visible_messages:
            visible_messages = [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_content},
            ]
        else:
            matching_user_index: int | None = None
            fallback_user_index: int | None = None
            for index, message in enumerate(visible_messages):
                if str(message.get("role") or "") != "user":
                    continue
                fallback_user_index = index
                if self._visible_content(message.get("content")) == user_content:
                    matching_user_index = index
            current_user_index = (
                matching_user_index
                if matching_user_index is not None
                else fallback_user_index
            )
            if current_user_index is not None:
                visible_message_offset = current_user_index + 1
                visible_messages = visible_messages[current_user_index + 1 :]
            else:
                # A complete transcript without a current-user boundary cannot
                # be distinguished safely from rows already covered by backfill.
                visible_messages = [{"role": "assistant", "content": assistant_content}]
        now = datetime.now(timezone.utc).isoformat()
        for index, message in enumerate(visible_messages):
            role = str(message.get("role") or "")
            if role not in {"user", "assistant", "tool"}:
                continue
            # The Telegram gateway hook owns inbound user events in both
            # shadow and retry modes. Shadow sync only fills assistant/tool
            # evidence, for which execution hooks are intentionally disabled.
            if role == "user":
                continue
            content = self._visible_content(message.get("content"))
            key = self._message_key(message, visible_message_offset + index, content)
            occurred_at = str(
                message.get("timestamp") or message.get("created_at") or now
            )
            if content:
                event_type = "tool_result" if role == "tool" else role
                self._enqueue_visible_event(
                    {
                        "source_event_key": f"hermes:{self._session_id}:{key}:{event_type}",
                        "event_type": event_type,
                        "role": role,
                        "occurred_at": occurred_at,
                        "content": content,
                        "tool_name": message.get("name"),
                        "tool_call_id": message.get("tool_call_id"),
                        "metadata": {},
                    }
                )
            if role == "assistant":
                for tool_index, tool_call in enumerate(message.get("tool_calls") or []):
                    function = tool_call.get("function") or {}
                    tool_call_id = str(tool_call.get("id") or f"{key}-{tool_index}")
                    self._enqueue_visible_event(
                        {
                            "source_event_key": f"hermes:{self._session_id}:{tool_call_id}:tool_call",
                            "event_type": "tool_call",
                            "role": "assistant",
                            "occurred_at": occurred_at,
                            "content": str(function.get("arguments") or "{}"),
                            "tool_name": function.get("name"),
                            "tool_call_id": tool_call_id,
                            "metadata": {},
                        }
                    )

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs: Any,
    ) -> None:
        if self._spool is None:
            return
        previous = parent_session_id or self._session_id
        reason = str(kwargs.get("reason") or ("reset" if reset else "continuation"))[
            :64
        ]
        self.spool.rotate_session(
            session_id=str(new_session_id),
            logical_conversation_id=self._logical_conversation_id,
            platform=self._platform,
            external_user_id=self._external_user_id,
            external_chat_id=self._external_chat_id,
            parent_session_id=previous or None,
            continuation_reason=reason,
        )
        self._session_id = str(new_session_id)
        backend_session = self.spool.get_meta(f"backend_session:{self._session_id}")
        if backend_session:
            self._backend_session_ids[self._session_id] = str(backend_session)

    def record_tool_before(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        side_effect_class: str,
        caller_idempotency_key: str | None = None,
    ) -> int | None:
        if (
            not self.is_available()
            or run_id != self._active_run_id
            or not self.has_active_run_lease()
        ):
            return None
        safe_arguments = redact_payload(arguments)
        source_key = f"tool:{run_id}:{tool_call_id}:before"
        tool_start = {
            "run_id": run_id,
            "lease_owner": self._active_lease_owner,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": safe_arguments,
            "side_effect_class": side_effect_class,
            "caller_idempotency_key": caller_idempotency_key,
        }
        existing = self.spool.get_record(source_key)
        if existing is not None:
            if existing.kind != "tool_before_bundle":
                raise SpoolConflict("tool call replay kind does not match")
            stored_start = existing.payload.get("tool_start")
            if not isinstance(stored_start, dict):
                if existing.receipt == {"compacted": True}:
                    return existing.id
                raise SpoolConflict("tool call replay payload is missing")
            stable_stored = {
                key: value
                for key, value in stored_start.items()
                if key != "lease_owner"
            }
            stable_candidate = {
                key: value for key, value in tool_start.items() if key != "lease_owner"
            }
            if stable_stored != stable_candidate:
                raise SpoolConflict("tool call replay does not match stored intent")
            return existing.id
        event_batch = self._event_batch(
            [
                {
                    "source_event_key": f"run:{run_id}:tool:{tool_call_id}:call",
                    "event_type": "tool_call",
                    "role": "assistant",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "content": json.dumps(
                        safe_arguments,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "metadata": {},
                }
            ],
            hermes_session_id=self._active_run_hermes_session_id,
        )
        return self.spool.enqueue(
            kind="tool_before_bundle",
            source_key=source_key,
            payload={
                "event_batch": event_batch,
                "tool_start": tool_start,
            },
        )

    def tool_replay_receipt(self, source_key: str) -> dict[str, Any] | None:
        record = self.spool.get_record(source_key)
        return record.receipt if record is not None else None

    def refresh_tool_replay(self, source_key: str) -> dict[str, Any] | None:
        """Re-read one acknowledged invocation from the canonical backend ledger."""
        record = self.spool.get_record(source_key)
        if record is None:
            return None
        if record.kind != "tool_before_bundle":
            raise SpoolConflict("tool call replay kind does not match")
        tool_start = record.payload.get("tool_start")
        if not isinstance(tool_start, dict):
            return record.receipt
        if self._backend is None or not self.has_active_run_lease():
            return None
        try:
            return self._backend.start_tool(
                {
                    **tool_start,
                    "lease_owner": self._active_lease_owner,
                }
            )
        except (BackendRequestError, TimeoutError, OSError, TypeError, ValueError):
            return None

    def record_tool_after(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        state: str,
        result_event_id: str | None = None,
        result_content: str | None = None,
        tool_name: str | None = None,
        attempt_key: str | None = None,
    ) -> int | None:
        if (
            not self.is_available()
            or run_id != self._active_run_id
            or not self.has_active_run_lease()
        ):
            return None
        if result_event_id is None and result_content is not None:
            attempt_digest = hashlib.sha256(
                str(attempt_key or f"legacy:{tool_call_id}:{state}").encode()
            ).hexdigest()
            event_batch = self._event_batch(
                [
                    {
                        "source_event_key": (
                            f"run:{run_id}:tool:{tool_call_id}:result:{attempt_digest}"
                        ),
                        "event_type": "tool_result",
                        "role": "tool",
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                        "content": result_content,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "metadata": {"tool_state": state},
                    }
                ],
                hermes_session_id=self._active_run_hermes_session_id,
            )
            return self.spool.enqueue(
                kind="tool_after_bundle",
                source_key=(
                    f"tool:{run_id}:{tool_call_id}:after:{state}:{attempt_digest}"
                ),
                payload={
                    "event_batch": event_batch,
                    "tool_update": {
                        "run_id": run_id,
                        "lease_owner": self._active_lease_owner,
                        "tool_call_id": tool_call_id,
                        "state": state,
                    },
                },
            )
        return self.spool.enqueue_tool_after(
            run_id=run_id,
            lease_owner=str(self._active_lease_owner),
            tool_call_id=tool_call_id,
            state=state,
            result_event_id=result_event_id,
        )

    def activate_claimed_run(
        self,
        run: dict[str, Any],
        *,
        hermes_session_id: str | None = None,
    ) -> None:
        run_id = run.get("id")
        if run_id:
            self._active_run_id = str(run_id)
            self.spool.set_meta("active_run_id", self._active_run_id)
            claimed = self.spool.get_meta(f"claimed_run:{self._active_run_id}", {})
            claimed_session_id = (
                claimed.get("hermes_session_id") if isinstance(claimed, dict) else None
            )
            exact_session_id = str(
                hermes_session_id
                or run.get("hermes_session_id")
                or claimed_session_id
                or self._active_run_hermes_session_id
                or self._session_id
            )
            self._active_run_hermes_session_id = exact_session_id
            attempt_counts = [
                value
                for value in (
                    run.get("attempt_count"),
                    claimed.get("attempt_count") if isinstance(claimed, dict) else None,
                )
                if type(value) is int and value >= 0
            ]
            self._active_run_attempt_count = max(attempt_counts, default=0)
            lease_owner = run.get("lease_owner") or (
                claimed.get("lease_owner") if isinstance(claimed, dict) else None
            )
            lease_expires_at = _parsed_datetime(run.get("lease_expires_at")) or (
                _parsed_datetime(claimed.get("lease_expires_at"))
                if isinstance(claimed, dict)
                else None
            )
            now = datetime.now(timezone.utc)
            if not lease_owner or lease_expires_at is None or lease_expires_at <= now:
                self._active_lease_owner = None
                self._active_lease_expires_at = None
                self.spool.delete_meta(f"claimed_run:{self._active_run_id}")
                return
            self._active_lease_owner = str(lease_owner)
            self._active_lease_expires_at = lease_expires_at
            if self._active_lease_owner:
                self.spool.rebind_pending_run_lease(
                    self._active_run_id,
                    self._active_lease_owner,
                )
                self.spool.set_meta(
                    f"claimed_run:{self._active_run_id}",
                    {
                        "lease_owner": self._active_lease_owner,
                        "lease_expires_at": lease_expires_at.isoformat(),
                        "attempt_count": self._active_run_attempt_count,
                        "hermes_session_id": exact_session_id,
                    },
                )

    def has_active_run_lease(self) -> bool:
        now = datetime.now(timezone.utc)
        if (
            not self._active_run_id
            or not self._active_lease_owner
            or self._active_lease_expires_at is None
            or self._active_lease_expires_at <= now
        ):
            self._active_lease_owner = None
            self._active_lease_expires_at = None
            return False
        return True

    def owns_run_lease(self, platform_message_id: str) -> bool:
        if not self.has_active_run_lease():
            return False
        inbound = self.spool.find_inbound(str(platform_message_id))
        run = ((inbound.receipt or {}).get("run", {}).get("run", {})) if inbound else {}
        return str(run.get("id") or "") == self._active_run_id

    def begin_active_execution(self, platform_message_id: str) -> str | None:
        """Bind lease renewal to one live, process-local model execution."""
        if not self.owns_run_lease(platform_message_id):
            return None
        run_id = self._active_run_id
        if not run_id:
            return None
        self._active_execution_run_id = run_id
        return run_id

    def end_active_execution(self, run_id: str | None) -> None:
        """Release renewal proof without disturbing a newer execution."""
        if run_id and run_id == self._active_execution_run_id:
            self._active_execution_run_id = None

    def activate_claimed_inbound(self, platform_message_id: str) -> bool:
        """Load a watcher-acquired lease into a reused in-process provider."""
        if not self.is_available() or not self._retry_enabled:
            return False
        inbound = self.spool.find_inbound(str(platform_message_id))
        run = ((inbound.receipt or {}).get("run", {}).get("run", {})) if inbound else {}
        run_id = str(run.get("id") or "")
        if not run_id:
            return False
        claimed = self.spool.get_meta(f"claimed_run:{run_id}", {})
        if not isinstance(claimed, dict):
            return False
        hermes_session_id = str(
            (inbound.payload.get("event_batch") or {}).get("hermes_session_id") or ""
        )
        self.activate_claimed_run(
            {**claimed, "id": run_id},
            hermes_session_id=hermes_session_id or None,
        )
        return self.owns_run_lease(platform_message_id)

    def inbound_terminal_state(self, platform_message_id: str) -> str | None:
        source_key = (
            f"inbound:{self._platform}:{self._external_chat_id}:{platform_message_id!s}"
        )
        inbound = self.spool.get_record(source_key)
        run = ((inbound.receipt or {}).get("run", {}).get("run", {})) if inbound else {}
        run_id = str(run.get("id") or "")
        persisted = self.spool.run_terminal_state(run_id) if run_id else None
        receipt_state = run.get("state")
        if persisted is not None:
            return persisted
        return (
            str(receipt_state)
            if receipt_state in {"succeeded", "blocked_side_effect", "terminal_failure"}
            else None
        )

    def inbound_is_pending(self, platform_message_id: str) -> bool:
        inbound = self.spool.find_inbound(str(platform_message_id))
        return inbound is not None and inbound.state == "pending"

    def has_pending_run_finalization(
        self,
        delivery_key: tuple[str, str, str] | None = None,
    ) -> bool:
        """Return true while a delivered response still owns the active run."""
        run_id = self._active_run_id
        if not run_id:
            return False
        completion = self.spool.get_record(f"run:{run_id}:completion")
        if completion is not None and completion.state == "pending":
            return True
        if delivery_key is None or len(delivery_key) != 3:
            return False
        attempt = self.spool.get_final_delivery(
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
        )
        return isinstance(attempt, dict) and str(attempt.get("run_id") or "") == run_id

    def renew_active_lease(self) -> bool:
        if (
            not self.is_available()
            or not self._retry_enabled
            or self._backend is None
            or not self.has_active_run_lease()
            or self._active_execution_run_id != self._active_run_id
        ):
            return False
        renew = getattr(self._backend, "renew_run", None)
        if not callable(renew):
            return False
        try:
            response = renew(
                {
                    "run_id": self._active_run_id,
                    "lease_owner": self._active_lease_owner,
                }
            )
        except (BackendRequestError, TimeoutError, OSError):
            return False
        if not isinstance(response, dict):
            return False
        self.activate_claimed_run(response)
        return self.has_active_run_lease()

    def defer_retry(self, error: BaseException, *, attempt: int) -> str | None:
        if not self.is_available() or not self._retry_enabled:
            return None
        if not self._active_run_id or not self._active_lease_owner:
            self.drain_once()
        if not self._active_run_id or not self._active_lease_owner:
            return None
        try:
            from .sydney_retry import plan_retry
        except ImportError:
            from sydney_retry import plan_retry

        deadline_raw = self.spool.get_meta(f"run_deadline:{self._active_run_id}")
        try:
            deadline = datetime.fromisoformat(str(deadline_raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            deadline = datetime.now(timezone.utc) + timedelta(hours=24)
        now = datetime.now(timezone.utc)
        durable_attempt = max(1, self._active_run_attempt_count)
        retry_index = max(max(0, int(attempt)), durable_attempt - 1)
        decision = plan_retry(
            error,
            attempt=retry_index,
            now=now,
            deadline=deadline,
            rng=lambda: 0.5,
        )
        if decision.action != "waiting_retry" or decision.next_attempt_at is None:
            return None
        payload = {
            "run_id": self._active_run_id,
            "state": "waiting_retry",
            "lease_owner": self._active_lease_owner,
            "next_attempt_at": decision.next_attempt_at.isoformat(),
            "provider_category": decision.classification,
            "error_code": f"provider_{getattr(error, 'status_code', 0) or 0}",
            "parsed_retry_delay_seconds": decision.delay.total_seconds()
            if decision.delay
            else None,
        }
        self.spool.enqueue(
            kind="run_update",
            source_key=(
                f"run:{self._active_run_id}:waiting:{durable_attempt}:provider"
            ),
            payload=payload,
        )
        self.drain_once()
        return decision.message

    def defer_compression_exhaustion(self) -> str | None:
        """Save an oversized turn for the fresh session Hermes creates next."""
        if not self.is_available() or not self._retry_enabled:
            return None
        if not self._active_run_id or not self._active_lease_owner:
            self.drain_once()
        if not self._active_run_id or not self._active_lease_owner:
            return None
        try:
            from .sydney_retry import AUTOMATIC_CONTINUATION_MESSAGE
        except ImportError:
            from sydney_retry import AUTOMATIC_CONTINUATION_MESSAGE

        next_attempt = datetime.now(timezone.utc) + timedelta(seconds=1)
        durable_attempt = max(1, self._active_run_attempt_count)
        self.spool.enqueue(
            kind="run_update",
            source_key=(
                f"run:{self._active_run_id}:waiting:{durable_attempt}:"
                "compression-exhausted"
            ),
            payload={
                "run_id": self._active_run_id,
                "state": "waiting_retry",
                "lease_owner": self._active_lease_owner,
                "next_attempt_at": next_attempt.isoformat(),
                "provider_category": "context_exhausted",
                "error_code": "compression_exhausted",
            },
        )
        self.drain_once()
        return AUTOMATIC_CONTINUATION_MESSAGE

    def supersede_active_run(self) -> int | None:
        """Terminally release an interrupted turn before its newer replacement."""
        if (
            not self.is_available()
            or not self._retry_enabled
            or not self.has_active_run_lease()
        ):
            return None
        if self.has_pending_run_finalization():
            self.drain_once()
            if self.has_pending_run_finalization():
                return None
        run_id = self._active_run_id
        local_id = self.spool.enqueue(
            kind="run_update",
            source_key=f"run:{run_id}:terminal:superseded",
            payload={
                "run_id": run_id,
                "state": "terminal_failure",
                "lease_owner": self._active_lease_owner,
                "error_code": "superseded_by_newer_inbound",
            },
        )
        self.drain_once()
        return local_id

    def fail_active_run(self, *, error_code: str) -> int | None:
        """Persist one bounded terminal outcome for a non-retryable model turn."""
        if (
            not self.is_available()
            or not self._retry_enabled
            or not self.has_active_run_lease()
        ):
            return None
        run_id = self._active_run_id
        lease_owner = self._active_lease_owner
        if not run_id or not lease_owner:
            return None
        local_id = self.spool.enqueue(
            kind="run_update",
            source_key=f"run:{run_id}:terminal:{error_code}",
            payload={
                "run_id": run_id,
                "state": "terminal_failure",
                "lease_owner": lease_owner,
                "error_code": str(error_code)[:64],
            },
        )
        self.drain_once()
        return local_id

    def control_delivery_kind(
        self,
        delivery_key: tuple[str, str, str],
    ) -> str | None:
        if len(delivery_key) != 3:
            return None
        attempt = self.spool.get_final_delivery(
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
        )
        if isinstance(attempt, dict) and attempt.get("delivery_kind") in {
            "deferred",
            "terminal_error",
        }:
            return str(attempt["delivery_kind"])
        inbound = self.spool.find_inbound(delivery_key[2])
        run_id = (
            str(
                (((inbound.receipt or {}).get("run") or {}).get("run") or {}).get("id")
                or ""
            )
            if inbound is not None
            else ""
        )
        if not run_id:
            return None
        for delivery_kind in ("deferred", "terminal_error"):
            record = self.spool.get_record(
                control_delivery_source_key(run_id, delivery_kind)
            )
            if record is not None:
                return delivery_kind
        return None

    def resolve_staged_control_delivery(
        self,
        delivery_key: tuple[str, str, str],
    ) -> str | None:
        """Fail closed on a replay whose prior control send may have landed."""
        delivery_kind = self.control_delivery_kind(delivery_key)
        if delivery_kind is None:
            return None
        attempt = self.spool.get_final_delivery(
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
        )
        if isinstance(attempt, dict) and attempt.get("delivery_kind") == delivery_kind:
            self.spool.confirm_control_delivery(
                platform=delivery_key[0],
                chat_id=delivery_key[1],
                platform_message_id=delivery_key[2],
                response_sha256=str(attempt.get("response_sha256") or ""),
                delivery_kind=delivery_kind,
                ambiguous=True,
            )
        self.drain_once()
        return delivery_kind

    def resolve_staged_final_delivery(
        self,
        delivery_key: tuple[str, str, str],
    ) -> str | None:
        """Block model replay when a prior final platform send is uncertain."""
        if len(delivery_key) != 3:
            return None
        attempt = self.spool.get_final_delivery(
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
        )
        if not isinstance(attempt, dict) or attempt.get("delivery_kind") in {
            "deferred",
            "terminal_error",
        }:
            return None

        run_id = str(attempt.get("run_id") or "")
        if run_id:
            completion = self.spool.get_record(f"run:{run_id}:completion")
            if completion is not None and completion.state == "pending":
                self.drain_once()
                remaining = self.spool.get_final_delivery(
                    platform=delivery_key[0],
                    chat_id=delivery_key[1],
                    platform_message_id=delivery_key[2],
                )
                return (
                    "final_delivery_confirmed"
                    if remaining is None
                    else "final_delivery_completion_pending"
                )

        if (
            run_id
            and run_id == self._active_run_id
            and self.has_active_run_lease()
            and self._active_lease_owner
        ):
            self.spool.enqueue(
                kind="run_update",
                source_key=f"run:{run_id}:blocked:final-delivery-uncertain",
                payload={
                    "run_id": run_id,
                    "state": "blocked_side_effect",
                    "lease_owner": self._active_lease_owner,
                    "provider_category": "delivery_uncertain",
                    "error_code": "final_delivery_uncertain",
                },
            )
            self.drain_once()
        return "final_delivery_uncertain"

    def stage_control_delivery(
        self,
        delivery_key: tuple[str, str, str],
        response: str,
        *,
        delivery_kind: str,
        error_code: str = "model_terminal_failure",
    ) -> str:
        """Stage a deferred acknowledgement or visible terminal error."""
        if (
            not self.is_available()
            or len(delivery_key) != 3
            or delivery_key[0] != self._platform
            or delivery_key[1] != self._external_chat_id
            or not response
            or not self._active_run_id
        ):
            return "unavailable"
        if delivery_kind not in {"deferred", "terminal_error"}:
            return "unavailable"
        if delivery_kind == "terminal_error" and not self.has_active_run_lease():
            return "unavailable"
        run_id = self._active_run_id
        lease_owner = self._active_lease_owner
        event_type = "assistant" if delivery_kind == "deferred" else "error"
        source_suffix = (
            "deferred_ack" if delivery_kind == "deferred" else "terminal_error"
        )
        event_batch = self._event_batch(
            [
                {
                    "source_event_key": f"run:{run_id}:{source_suffix}",
                    "event_type": event_type,
                    "role": "assistant",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "content": response,
                    "metadata": {
                        "run_control_message": True,
                        "delivery_kind": delivery_kind,
                    },
                }
            ],
            hermes_session_id=self._active_run_hermes_session_id,
        )
        run_update = (
            {
                "run_id": run_id,
                "state": "terminal_failure",
                "lease_owner": lease_owner,
                "error_code": str(error_code)[:64],
            }
            if delivery_kind == "terminal_error"
            else None
        )
        return self.spool.stage_control_delivery(
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
            run_id=run_id,
            lease_owner=lease_owner,
            response_sha256=hashlib.sha256(response.encode("utf-8")).hexdigest(),
            delivery_kind=delivery_kind,
            event_batch=event_batch,
            run_update=run_update,
        )

    def confirm_control_delivery(
        self,
        delivery_key: tuple[str, str, str],
        response: str,
        *,
        delivery_kind: str,
    ) -> None:
        if len(delivery_key) != 3 or not response:
            return
        self.spool.confirm_control_delivery(
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
            response_sha256=hashlib.sha256(response.encode("utf-8")).hexdigest(),
            delivery_kind=delivery_kind,
        )
        self.drain_once()

    def stage_final_delivery(
        self,
        delivery_key: tuple[str, str, str],
        final_response: str,
    ) -> bool:
        """Persist an ambiguous-until-confirmed outbound boundary in SQLite."""
        if (
            not self.has_active_run_lease()
            or len(delivery_key) != 3
            or delivery_key[0] != self._platform
            or delivery_key[1] != self._external_chat_id
            or not final_response
            or not self._active_run_id
            or not self._active_lease_owner
        ):
            return False
        self.spool.stage_final_delivery(
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
            run_id=self._active_run_id,
            lease_owner=self._active_lease_owner,
            response_sha256=hashlib.sha256(final_response.encode("utf-8")).hexdigest(),
        )
        return True

    def stage_degraded_delivery(
        self,
        delivery_key: tuple[str, str, str],
        final_response: str,
    ) -> bool:
        """Persist a backend-outage response before the platform send boundary."""
        if (
            len(delivery_key) != 3
            or delivery_key[0] != self._platform
            or delivery_key[1] != self._external_chat_id
            or not final_response
            or not self.inbound_is_pending(delivery_key[2])
        ):
            return False
        response_sha256 = hashlib.sha256(final_response.encode("utf-8")).hexdigest()
        event_batch = self._event_batch(
            [
                {
                    "source_event_key": (
                        f"degraded:{self._platform}:{delivery_key[2]}:final_response"
                    ),
                    "event_type": "assistant",
                    "role": "assistant",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "content": final_response,
                    "metadata": {
                        "run_completion": True,
                        "backend_degraded": True,
                    },
                }
            ]
        )
        self.spool.enqueue_degraded_completion(
            event_batch,
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
        )
        self.spool.stage_degraded_final_delivery(
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
            response_sha256=response_sha256,
        )
        return True

    def confirm_degraded_delivery(
        self,
        delivery_key: tuple[str, str, str],
        final_response: str,
    ) -> None:
        if len(delivery_key) != 3 or not final_response:
            return
        self.spool.confirm_degraded_final_delivery(
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
            response_sha256=hashlib.sha256(final_response.encode("utf-8")).hexdigest(),
        )
        self.drain_once()

    def clear_final_delivery(self, delivery_key: tuple[str, str, str]) -> None:
        if len(delivery_key) != 3:
            return
        self.spool.clear_final_delivery(
            platform=delivery_key[0],
            chat_id=delivery_key[1],
            platform_message_id=delivery_key[2],
        )

    def complete_active_run(
        self,
        final_response: str,
        *,
        delivery_key: tuple[str, str, str] | None = None,
    ) -> int | None:
        if (
            not self.is_available()
            or not self._retry_enabled
            or not self.has_active_run_lease()
            or not final_response
        ):
            return None
        run_id = self._active_run_id
        event_batch = self._event_batch(
            [
                {
                    "source_event_key": f"run:{run_id}:final_response",
                    "event_type": "assistant",
                    "role": "assistant",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "content": final_response,
                    "metadata": {"run_completion": True},
                }
            ],
            hermes_session_id=self._active_run_hermes_session_id,
        )
        local_id = self.spool.enqueue(
            kind="run_completion_bundle",
            source_key=f"run:{run_id}:completion",
            payload={
                "event_batch": event_batch,
                "run_update": {
                    "run_id": run_id,
                    "state": "succeeded",
                    "lease_owner": self._active_lease_owner,
                },
                "delivery_key": list(delivery_key) if delivery_key else None,
            },
        )
        self.drain_once()
        return local_id

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        if not self._retrieval_enabled:
            return []
        return [
            {
                "name": "context_history_search",
                "description": (
                    "Search Sydney's durable conversation history by text, date, "
                    "type, event window, or recent conversation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 500,
                        },
                        "event_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 8,
                        },
                        "started_at": {"type": "string", "format": "date-time"},
                        "ended_at": {"type": "string", "format": "date-time"},
                        "around_event_id": {"type": "string", "format": "uuid"},
                        "recent_conversations": {"type": "boolean"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                        "window_size": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "anyOf": [
                        {"required": ["query"]},
                        {"required": ["around_event_id"]},
                        {
                            "properties": {"recent_conversations": {"const": True}},
                            "required": ["recent_conversations"],
                        },
                    ],
                    "additionalProperties": False,
                },
            }
        ]

    def handle_tool_call(
        self, tool_name: str, args: dict[str, Any], **kwargs: Any
    ) -> str:
        if tool_name != "context_history_search":
            return json.dumps({"error": "unsupported_memory_tool"})
        if (
            not self._retrieval_enabled
            or not self._identity_id
            or self._backend is None
        ):
            return json.dumps({"error": "durable_context_identity_unavailable"})
        allowed = {
            "query",
            "event_types",
            "started_at",
            "ended_at",
            "around_event_id",
            "recent_conversations",
            "limit",
            "window_size",
        }
        payload = {key: value for key, value in args.items() if key in allowed}
        payload["identity_id"] = self._identity_id
        try:
            return json.dumps(self._backend.history_search(payload), ensure_ascii=False)
        except (BackendRequestError, TimeoutError, OSError, TypeError, ValueError):
            return json.dumps({"error": "durable_context_history_unavailable"})

    def shutdown(self) -> None:
        self._active_execution_run_id = None
        self._stop.set()
        deadline = time.monotonic() + self._shutdown_deadline
        while (
            self._spool is not None
            and self.spool.pending_count
            and time.monotonic() < deadline
        ):
            result = self.drain_once()
            if result is None or result.failed:
                break
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if self._spool is not None:
            self._spool.close()
            self._spool = None


def register(ctx: Any) -> None:
    """Register Sydney through Hermes' standard memory plugin hook."""
    ctx.register_memory_provider(SydneyMemoryProvider())
