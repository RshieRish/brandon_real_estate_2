"""Gateway poller that resumes backend-leased Sydney runs after restarts."""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
from pathlib import Path
from typing import Any

try:
    from plugins.memory.sydney import (
        SydneyBackendClient,
        deliver_control_delivery_record,
    )
    from plugins.memory.sydney.sydney_spool import (
        SydneySpool,
        control_delivery_source_key,
    )
except ImportError:
    try:
        from .sydney_memory_provider import (
            SydneyBackendClient,
            deliver_control_delivery_record,
        )
        from .sydney_spool import SydneySpool, control_delivery_source_key
    except ImportError:
        from sydney_memory_provider import (
            SydneyBackendClient,
            deliver_control_delivery_record,
        )
        from sydney_spool import SydneySpool, control_delivery_source_key


_CONTINUATION_MARKER = (
    "[System continuation: resume this saved request after the provider wait. "
    "The original user turn is already present in durable history. Do not ask "
    "the user to restart.]"
)


def _continuation_channel_context(original: str) -> str:
    """Restore the durable user turn as context, separate from the new marker."""
    return "[Recovered durable user request]\n" + original


def _enabled() -> bool:
    return os.environ.get("SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _allowed_users() -> set[str]:
    return {
        value.strip()
        for value in os.environ.get(
            "SYDNEY_DURABLE_CONTEXT_ALLOWED_USER_IDS", ""
        ).split(",")
        if value.strip()
    }


def _configured_private_identity() -> tuple[str, str, str] | None:
    user_id = os.environ.get("SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID", "").strip()
    chat_id = os.environ.get("SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID", "").strip()
    if not user_id or not chat_id or user_id not in _allowed_users():
        return None
    return ("telegram", user_id, chat_id)


def _identity_meta_key(platform: str, user_id: str, chat_id: str) -> str:
    stable_key = f"{platform}\x1f{user_id}\x1f{chat_id}"
    return "backend_identity:" + hashlib.sha256(stable_key.encode()).hexdigest()


def _drain_pending_inbound_bundles(
    *,
    backend: Any,
    spool: SydneySpool,
    expected_identity: tuple[str, str, str],
    limit: int = 100,
) -> int:
    """Create backend runs for fsynced inbound rows before polling leases."""
    acknowledged = 0
    for record in spool.matching_records(
        state="pending",
        source_prefix="inbound:",
        limit=limit,
    ):
        if record.kind != "inbound_bundle":
            continue
        event_batch = record.payload.get("event_batch")
        run_start = record.payload.get("run_start")
        if not isinstance(event_batch, dict) or not isinstance(run_start, dict):
            spool.record_failure(record.id)
            break
        observed_identity = (
            str(event_batch.get("platform") or ""),
            str(event_batch.get("external_user_id") or ""),
            str(event_batch.get("external_chat_id") or ""),
        )
        if observed_identity != expected_identity:
            spool.record_failure(record.id)
            break
        try:
            ingested = backend.ingest_events(event_batch)
            event_ids = ingested.get("event_ids") or []
            identity_id = str(ingested.get("identity_id") or "")
            backend_session_id = str(ingested.get("session_id") or "")
            logical_conversation_id = str(ingested.get("logical_conversation_id") or "")
            if (
                not event_ids
                or not identity_id
                or not backend_session_id
                or not logical_conversation_id
            ):
                raise RuntimeError("backend ingest receipt is incomplete")
            run_response = backend.start_run(
                {
                    **run_start,
                    "identity_id": identity_id,
                    "inbound_event_id": event_ids[0],
                    "session_id": backend_session_id,
                    "logical_conversation_id": logical_conversation_id,
                }
            )
            run = run_response.get("run") or {}
            run_id = str(run.get("id") or "")
            if not run_id:
                raise RuntimeError("backend run receipt is incomplete")
            session_id = str(event_batch.get("hermes_session_id") or "")
            spool.set_meta(_identity_meta_key(*expected_identity), identity_id)
            if session_id:
                spool.set_meta(f"backend_session:{session_id}", backend_session_id)
            if run.get("state") in {
                "succeeded",
                "blocked_side_effect",
                "terminal_failure",
            }:
                spool.mark_run_terminal(run_id, state=str(run["state"]))
            else:
                spool.set_meta("active_run_id", run_id)
            spool.set_meta(
                f"run_deadline:{run_id}",
                run_start.get("terminal_deadline_at"),
            )
            spool.acknowledge(
                record.id,
                {
                    "ingest": ingested,
                    "run": run_response,
                    "claim": {"runs": []},
                },
            )
            acknowledged += 1
        except Exception:  # noqa: BLE001 - bounded backend recovery delivery.
            spool.record_failure(record.id)
            break
    return acknowledged


def _matches_private_identity(
    *,
    platform: str,
    external_user_id: str,
    external_chat_id: str,
    expected: tuple[str, str, str] | None,
) -> bool:
    return (
        expected is not None
        and (
            platform,
            external_user_id,
            external_chat_id,
        )
        == expected
    )


def _drain_confirmed_completion(
    *,
    backend: Any,
    spool: SydneySpool,
    run_id: str,
    lease_owner: str,
) -> bool:
    """Finish an already-confirmed send from its durable completion bundle."""
    record = spool.get_record(f"run:{run_id}:completion")
    degraded = False
    if record is None or record.kind != "run_completion_bundle":
        inbound = spool.find_inbound_for_run(run_id)
        message_id = ""
        if inbound is not None:
            message_id = str(
                inbound.payload.get("run_start", {}).get("platform_message_id") or ""
            )
        if message_id:
            record = spool.find_degraded_completion(
                platform=str(
                    inbound.payload.get("event_batch", {}).get("platform") or ""
                ),
                chat_id=str(
                    inbound.payload.get("event_batch", {}).get("external_chat_id") or ""
                ),
                platform_message_id=message_id,
            )
        if record is None or record.kind != "degraded_completion_bundle":
            return False
        degraded = True
        delivery_key = record.payload.get("delivery_key")
        if not isinstance(delivery_key, list) or len(delivery_key) != 3:
            return True
        attempt = spool.get_final_delivery(
            platform=str(delivery_key[0]),
            chat_id=str(delivery_key[1]),
            platform_message_id=str(delivery_key[2]),
        )
        if (
            not isinstance(attempt, dict)
            or attempt.get("degraded") is not True
            or not attempt.get("confirmed_at")
        ):
            return False
    if record.state == "acknowledged":
        delivery_key = record.payload.get("delivery_key")
        if isinstance(delivery_key, list) and len(delivery_key) == 3:
            spool.clear_final_delivery(
                platform=str(delivery_key[0]),
                chat_id=str(delivery_key[1]),
                platform_message_id=str(delivery_key[2]),
            )
        spool.mark_run_terminal(run_id, state="succeeded")
        return True
    if not degraded:
        spool.rebind_pending_run_lease(run_id, lease_owner)
    record = spool.get_record(record.source_key)
    if record is None:
        return True
    try:
        event_batch = record.payload["event_batch"]
        ingested = backend.ingest_events(event_batch)
        event_ids = ingested.get("event_ids") or []
        if not event_ids:
            raise RuntimeError("run completion ingest receipt is incomplete")
        update = (
            {
                "run_id": run_id,
                "state": "succeeded",
                "lease_owner": lease_owner,
                "final_response_event_id": event_ids[0],
            }
            if degraded
            else {
                **record.payload["run_update"],
                "final_response_event_id": event_ids[0],
            }
        )
        run_response = backend.update_run(update)
        delivery_key = record.payload.get("delivery_key")
        if isinstance(delivery_key, list) and len(delivery_key) == 3:
            spool.clear_final_delivery(
                platform=str(delivery_key[0]),
                chat_id=str(delivery_key[1]),
                platform_message_id=str(delivery_key[2]),
            )
        spool.acknowledge(record.id, {"ingest": ingested, "run": run_response})
        spool.mark_run_terminal(run_id, state="succeeded")
        if spool.get_meta("active_run_id") == run_id:
            spool.delete_meta("active_run_id")
        spool.delete_meta(f"claimed_run:{run_id}")
    except Exception:  # noqa: BLE001 - keep the durable completion pending.
        spool.record_failure(record.id)
    return True


def _drain_control_delivery(
    *,
    backend: Any,
    spool: SydneySpool,
    run_id: str,
    lease_owner: str,
    attempt: dict[str, Any],
    platform: str,
    chat_id: str,
    platform_message_id: str,
) -> tuple[bool, bool]:
    """Resolve a staged control send and report whether model replay is blocked."""
    delivery_kind = str(attempt.get("delivery_kind") or "")
    if delivery_kind not in {"deferred", "terminal_error"}:
        return False, False
    if str(attempt.get("run_id") or "") != run_id:
        return True, True
    source_key = str(
        attempt.get("source_key") or control_delivery_source_key(run_id, delivery_kind)
    )
    record = spool.get_record(source_key)
    try:
        if record is None:
            event_batch = attempt.get("event_batch")
            if not isinstance(event_batch, dict):
                return True, True
            if (
                str(event_batch.get("platform") or "") != platform
                or str(event_batch.get("external_chat_id") or "") != chat_id
                or not platform_message_id
            ):
                return True, True
            spool.confirm_control_delivery(
                platform=platform,
                chat_id=chat_id,
                platform_message_id=platform_message_id,
                response_sha256=str(attempt.get("response_sha256") or ""),
                delivery_kind=delivery_kind,
                ambiguous=True,
            )
            record = spool.get_record(source_key)
        if record is None:
            return True, True
        if record.state == "pending":
            spool.rebind_pending_run_lease(run_id, lease_owner)
            record = spool.get_record(source_key)
            if record is None:
                return True, True
            receipt = deliver_control_delivery_record(
                backend=backend,
                spool=spool,
                record=record,
                lease_owner=lease_owner,
            )
            spool.acknowledge(record.id, receipt)
        delivery_key = record.payload.get("delivery_key")
        if isinstance(delivery_key, list) and len(delivery_key) == 3:
            spool.clear_final_delivery(
                platform=str(delivery_key[0]),
                chat_id=str(delivery_key[1]),
                platform_message_id=str(delivery_key[2]),
            )
        return True, delivery_kind != "deferred"
    except Exception:  # noqa: BLE001 - preserve the staged marker for retry.
        if record is not None and record.state == "pending":
            spool.record_failure(record.id)
        return True, True


async def _block_uncertain_final_delivery(
    *,
    backend: Any,
    spool: SydneySpool,
    run: dict[str, Any],
    platform: str,
    chat_id: str,
) -> bool:
    """Fail closed when a prior process may already have sent the final reply."""
    message_id = str(run.get("platform_message_id") or "")
    attempt = spool.get_final_delivery(
        platform=platform,
        chat_id=chat_id,
        platform_message_id=message_id,
    )
    if attempt is None:
        return False
    run_id = str(run.get("id") or "")
    lease_owner = str(run.get("lease_owner") or "")
    if not run_id or not lease_owner:
        return True
    control_handled, control_blocks = await asyncio.to_thread(
        _drain_control_delivery,
        backend=backend,
        spool=spool,
        run_id=run_id,
        lease_owner=lease_owner,
        attempt=attempt,
        platform=platform,
        chat_id=chat_id,
        platform_message_id=message_id,
    )
    if control_handled:
        return control_blocks
    if await asyncio.to_thread(
        _drain_confirmed_completion,
        backend=backend,
        spool=spool,
        run_id=run_id,
        lease_owner=lease_owner,
    ):
        return True
    error_code = (
        "final_delivery_uncertain"
        if str(attempt.get("run_id") or "") == run_id
        else "final_delivery_ledger_conflict"
    )
    try:
        await asyncio.to_thread(
            backend.update_run,
            {
                "run_id": run_id,
                "state": "blocked_side_effect",
                "lease_owner": lease_owner,
                "provider_category": "delivery_uncertain",
                "error_code": error_code,
            },
        )
        spool.mark_run_terminal(run_id, state="blocked_side_effect")
    except Exception:  # noqa: BLE001, S110 - durable lease safety boundary.
        # Keep the live lease from being dispatched even if the backend update
        # is temporarily unavailable. A later claim will reconcile it again.
        pass
    return True


async def sydney_continuation_watcher(gateway: Any, interval: float = 2.0) -> None:
    """Claim due runs FIFO and feed one internal event through normal delivery."""
    if not _enabled():
        return
    backend_url = os.environ.get("BACKEND_API_URL") or os.environ.get(
        "BRANDON_BACKEND_URL", ""
    )
    token = os.environ.get("AGENT_CONTROL_TOKEN") or os.environ.get(
        "BRANDON_AGENT_CONTROL_TOKEN", ""
    )
    expected_identity = _configured_private_identity()
    if not backend_url or not token or expected_identity is None:
        return
    hermes_home = Path(os.environ.get("HERMES_HOME", "/data/.hermes"))
    spool_path = hermes_home / "sydney_spool.db"
    backend = SydneyBackendClient(backend_url, token)
    lease_owner = f"hermes:{socket.gethostname()}:{os.getpid()}"
    spool: SydneySpool | None = None
    delay = max(0.25, float(interval))
    try:
        while getattr(gateway, "_running", False):
            if spool is None:
                if not spool_path.exists():
                    await asyncio.sleep(delay)
                    continue
                try:
                    spool = SydneySpool(spool_path)
                except Exception:  # noqa: BLE001 - retry spool open next poll.
                    await asyncio.sleep(delay)
                    continue
            await asyncio.to_thread(
                _drain_pending_inbound_bundles,
                backend=backend,
                spool=spool,
                expected_identity=expected_identity,
            )
            configured_identity_id = spool.get_meta(
                _identity_meta_key(*expected_identity)
            )
            for identity_id in (
                [configured_identity_id] if configured_identity_id else []
            ):
                try:
                    response = await asyncio.to_thread(
                        backend.claim_runs,
                        {
                            "lease_owner": lease_owner,
                            "identity_id": identity_id,
                            "limit": 10,
                        },
                    )
                except Exception:  # noqa: BLE001, S112 - retry backend next poll.
                    continue
                for run in response.get("runs") or []:
                    inbound = spool.find_inbound(
                        str(run.get("platform_message_id") or "")
                    )
                    if inbound is None:
                        continue
                    event_batch = inbound.payload.get("event_batch") or {}
                    user_id = str(event_batch.get("external_user_id") or "")
                    platform_name = str(event_batch.get("platform") or "")
                    chat_id = str(event_batch.get("external_chat_id") or "")
                    if not _matches_private_identity(
                        platform=platform_name,
                        external_user_id=user_id,
                        external_chat_id=chat_id,
                        expected=expected_identity,
                    ):
                        continue
                    events = event_batch.get("events") or []
                    original = str(events[0].get("content") or "") if events else ""
                    if not platform_name or not chat_id or not original:
                        continue
                    if await _block_uncertain_final_delivery(
                        backend=backend,
                        spool=spool,
                        run=run,
                        platform=platform_name,
                        chat_id=chat_id,
                    ):
                        continue
                    try:
                        from gateway.config import Platform
                        from gateway.platforms.base import MessageEvent, MessageType
                        from gateway.session import SessionSource

                        platform = Platform(platform_name)
                        source = SessionSource(
                            platform=platform,
                            chat_id=chat_id,
                            chat_type="dm",
                            user_id=user_id,
                            user_name=str(event_batch.get("display_label") or "")
                            or None,
                            message_id=str(run.get("platform_message_id") or "")
                            or None,
                        )
                        adapter = gateway.adapters.get(platform)
                        if adapter is None:
                            continue
                        spool.set_meta(
                            f"claimed_run:{run['id']}",
                            {
                                "lease_owner": lease_owner,
                                "lease_expires_at": run.get("lease_expires_at"),
                                "attempt_count": run.get("attempt_count", 0),
                                "hermes_session_id": event_batch.get(
                                    "hermes_session_id"
                                ),
                            },
                        )
                        event = MessageEvent(
                            text=_CONTINUATION_MARKER,
                            message_type=MessageType.TEXT,
                            source=source,
                            message_id=str(run.get("platform_message_id") or "")
                            or None,
                            channel_context=_continuation_channel_context(original),
                            internal=True,
                        )
                        await adapter.handle_message(event)
                    except Exception:  # noqa: BLE001, S112 - isolate run dispatch.
                        continue
            await asyncio.sleep(delay)
    finally:
        if spool is not None:
            spool.close()
