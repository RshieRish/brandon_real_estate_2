"""Direct PostgreSQL engine and session-affinity proof for Gmail History."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from services.gmail_message_sanitizer import validate_gmail_runtime_settings


_AFFINITY_ERROR = "gmail_history_session_affinity_required"


@dataclass(frozen=True)
class GmailHistorySessionAffinityProof:
    backend_pid: int
    backend_pid_before_commit: int
    backend_pid_after_commit: int
    lock_survived_commit: bool
    unlock_succeeded: bool
    primary_contended_before_release: bool
    primary_acquired_after_release: bool


def create_gmail_history_engine(config: object) -> AsyncEngine:
    """Create the dedicated, non-pooled engine after enabled-only validation."""

    runtime = validate_gmail_runtime_settings(config)
    if not runtime.enabled or runtime.history_database_url is None:
        raise RuntimeError("gmail_history_database_disabled")
    url = make_url(runtime.history_database_url)
    query = dict(url.query)
    ssl_mode = query.pop("sslmode", None)
    asyncpg_ssl = query.get("ssl")
    if ssl_mode is not None:
        if asyncpg_ssl is not None and asyncpg_ssl != ssl_mode:
            raise RuntimeError("gmail_history_tls_required")
        query["ssl"] = ssl_mode
    url = url.set(query=query)
    return create_async_engine(
        url,
        poolclass=NullPool,
        pool_pre_ping=True,
    )


async def _read_backend_pid(connection: AsyncConnection) -> int:
    value = await connection.scalar(text("SELECT pg_backend_pid()"))
    if not isinstance(value, int) or value <= 0:
        raise RuntimeError(_AFFINITY_ERROR)
    return value


async def _acquire_probe_lock(connection: AsyncConnection, key: int) -> bool:
    return bool(
        await connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": key},
        )
    )


async def _release_probe_lock(connection: AsyncConnection, key: int) -> bool:
    return bool(
        await connection.scalar(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": key},
        )
    )


async def _primary_try_probe_lock(connection: AsyncConnection, key: int) -> bool:
    return await _acquire_probe_lock(connection, key)


async def probe_gmail_history_session_affinity(
    *,
    history_engine: AsyncEngine,
    primary_engine: AsyncEngine,
    after_history_lock_commit: Callable[[int], Awaitable[None]] | None = None,
) -> GmailHistorySessionAffinityProof:
    """Prove direct-session commits and the primary/history lock namespace."""

    # A positive random signed-bigint-range key avoids colliding with runtime
    # account locks while remaining valid for PostgreSQL's one-argument API.
    key = secrets.randbits(62) + 1
    history_connection: AsyncConnection | None = None
    primary_connection: AsyncConnection | None = None
    history_locked = False
    primary_locked = False
    history_unlocked = False
    before_pid = 0
    after_pid = 0
    try:
        history_connection = await history_engine.connect()

        # This bare commit/PID check intentionally precedes lock acquisition.
        # A transaction-pooling endpoint must fail without risking a leaked
        # session advisory lock.
        before_pid = await _read_backend_pid(history_connection)
        await history_connection.commit()
        after_pid = await _read_backend_pid(history_connection)
        if after_pid != before_pid:
            raise RuntimeError(_AFFINITY_ERROR)

        history_locked = await _acquire_probe_lock(history_connection, key)
        if not history_locked:
            raise RuntimeError(_AFFINITY_ERROR)
        await history_connection.commit()
        if await _read_backend_pid(history_connection) != before_pid:
            raise RuntimeError(_AFFINITY_ERROR)

        if after_history_lock_commit is not None:
            await after_history_lock_commit(key)

        primary_connection = await primary_engine.connect()
        primary_locked = await _primary_try_probe_lock(primary_connection, key)
        await primary_connection.commit()
        if primary_locked:
            # Different advisory namespaces/clusters are unsafe. Release the
            # unexpected primary-side acquisition before failing closed.
            if not await _release_probe_lock(primary_connection, key):
                raise RuntimeError(_AFFINITY_ERROR)
            primary_locked = False
            await primary_connection.commit()
            raise RuntimeError(_AFFINITY_ERROR)

        history_unlocked = await _release_probe_lock(history_connection, key)
        history_locked = False
        await history_connection.commit()
        if not history_unlocked:
            raise RuntimeError(_AFFINITY_ERROR)

        primary_locked = await _primary_try_probe_lock(primary_connection, key)
        if not primary_locked:
            raise RuntimeError(_AFFINITY_ERROR)
        primary_released = await _release_probe_lock(primary_connection, key)
        primary_locked = False
        await primary_connection.commit()
        if not primary_released:
            raise RuntimeError(_AFFINITY_ERROR)

        return GmailHistorySessionAffinityProof(
            backend_pid=before_pid,
            backend_pid_before_commit=before_pid,
            backend_pid_after_commit=after_pid,
            lock_survived_commit=True,
            unlock_succeeded=history_unlocked,
            primary_contended_before_release=True,
            primary_acquired_after_release=True,
        )
    except asyncio.CancelledError:
        raise
    except BaseException:
        raise RuntimeError(_AFFINITY_ERROR) from None
    finally:
        if primary_connection is not None:
            if primary_locked:
                try:
                    await _release_probe_lock(primary_connection, key)
                    await primary_connection.commit()
                except BaseException:
                    pass
            await primary_connection.close()
        if history_connection is not None:
            if history_locked:
                try:
                    await _release_probe_lock(history_connection, key)
                    await history_connection.commit()
                except BaseException:
                    pass
            await history_connection.close()


__all__ = [
    "GmailHistorySessionAffinityProof",
    "create_gmail_history_engine",
    "probe_gmail_history_session_affinity",
]
