"""Gateway poller that resumes backend-leased Sydney runs after restarts."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import socket
from typing import Any

try:
    from plugins.memory.sydney import SydneyBackendClient
    from plugins.memory.sydney.sydney_spool import SydneySpool
except ImportError:
    try:
        from .sydney_memory_provider import SydneyBackendClient
        from .sydney_spool import SydneySpool
    except ImportError:
        from sydney_memory_provider import SydneyBackendClient
        from sydney_spool import SydneySpool


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
    allowed = _allowed_users()
    if not backend_url or not token or not allowed:
        return
    hermes_home = Path(os.environ.get("HERMES_HOME", "/data/.hermes"))
    spool_path = hermes_home / "sydney_spool.db"
    if not spool_path.exists():
        return
    backend = SydneyBackendClient(backend_url, token)
    lease_owner = f"hermes:{socket.gethostname()}:{os.getpid()}"
    spool = SydneySpool(spool_path)
    try:
        while getattr(gateway, "_running", False):
            identities = spool.meta_items("backend_identity:")
            for identity_id in identities.values():
                try:
                    response = await asyncio.to_thread(
                        backend.claim_runs,
                        {
                            "lease_owner": lease_owner,
                            "identity_id": identity_id,
                            "limit": 10,
                        },
                    )
                except Exception:
                    continue
                for run in response.get("runs") or []:
                    inbound = spool.find_inbound(str(run.get("platform_message_id") or ""))
                    if inbound is None:
                        continue
                    event_batch = inbound.payload.get("event_batch") or {}
                    user_id = str(event_batch.get("external_user_id") or "")
                    if user_id not in allowed:
                        continue
                    platform_name = str(event_batch.get("platform") or "")
                    chat_id = str(event_batch.get("external_chat_id") or "")
                    events = event_batch.get("events") or []
                    original = str(events[0].get("content") or "") if events else ""
                    if not platform_name or not chat_id or not original:
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
                            user_name=str(event_batch.get("display_label") or "") or None,
                            message_id=str(run.get("platform_message_id") or "") or None,
                        )
                        adapter = gateway.adapters.get(platform)
                        if adapter is None:
                            continue
                        spool.set_meta(
                            f"claimed_run:{run['id']}",
                            {"lease_owner": lease_owner, "attempt_count": run.get("attempt_count", 0)},
                        )
                        event = MessageEvent(
                            text=(
                                "[System continuation: resume this saved request after the "
                                "provider wait. Do not ask the user to restart.]\n\n" + original
                            ),
                            message_type=MessageType.TEXT,
                            source=source,
                            message_id=str(run.get("platform_message_id") or "") or None,
                            internal=True,
                        )
                        await adapter.handle_message(event)
                    except Exception:
                        continue
            await asyncio.sleep(max(0.25, float(interval)))
    finally:
        spool.close()
