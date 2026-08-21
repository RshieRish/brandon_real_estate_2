"""Bounded integration health, heartbeat, and provider-call primitives."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_health import (
    IntegrationHealthState,
    IntegrationWorkerHeartbeat,
)


T = TypeVar("T")


class ProviderCallTimedOut(RuntimeError):
    pass


class ProviderJobStillRunning(RuntimeError):
    pass


class ProviderExecutorSaturated(RuntimeError):
    pass


_SAFE_ERROR_MESSAGES = {
    "oauth_revoked": "Authentication must be renewed.",
    "rate_limited": "Provider rate limit reached.",
    "provider_timeout": "Provider request timed out.",
    "transient_provider": "Provider request failed temporarily.",
    "malformed_provider": "Provider returned an invalid response.",
}


def integration_alert_dedupe_key(
    *,
    provider: str,
    transition_epoch: int,
    event: str,
) -> str:
    if not provider or len(provider) > 64:
        raise ValueError("provider must contain 1 to 64 characters")
    if transition_epoch < 1:
        raise ValueError("transition_epoch must be positive")
    if not event or len(event) > 32:
        raise ValueError("event must contain 1 to 32 characters")
    return (
        f"integration-health:{provider}:epoch:{transition_epoch}:{event}"
    )


def _sanitized_error_message(error_category: str) -> str:
    return _SAFE_ERROR_MESSAGES.get(
        error_category,
        "Integration check failed.",
    )


async def record_integration_failure(
    db: AsyncSession,
    *,
    provider: str,
    state: str,
    checked_at: datetime,
    error_category: str,
    raw_error: str | None = None,
) -> IntegrationHealthState:
    del raw_error
    row = await db.scalar(
        select(IntegrationHealthState)
        .where(IntegrationHealthState.provider == provider)
        .with_for_update()
    )
    if row is None:
        row = IntegrationHealthState(
            provider=provider,
            state=state,
            transition_epoch=1,
            consecutive_failures=0,
        )
        db.add(row)
    elif row.state != state:
        row.transition_epoch += 1
    row.state = state
    row.last_checked_at = checked_at
    row.last_error_category = error_category[:64]
    row.last_error_message = _sanitized_error_message(error_category)
    row.consecutive_failures += 1
    await db.flush()
    return row


async def record_integration_success(
    db: AsyncSession,
    *,
    provider: str,
    checked_at: datetime,
) -> IntegrationHealthState:
    row = await db.scalar(
        select(IntegrationHealthState)
        .where(IntegrationHealthState.provider == provider)
        .with_for_update()
    )
    if row is None:
        row = IntegrationHealthState(
            provider=provider,
            state="healthy",
            transition_epoch=1,
        )
        db.add(row)
    elif row.state != "healthy":
        row.transition_epoch += 1
        row.recovered_at = checked_at
    row.state = "healthy"
    row.last_checked_at = checked_at
    row.last_succeeded_at = checked_at
    row.last_error_category = None
    row.last_error_message = None
    row.consecutive_failures = 0
    await db.flush()
    return row


async def record_scheduler_boot(
    db: AsyncSession,
    *,
    worker_id: str,
    booted_at: datetime,
) -> IntegrationWorkerHeartbeat:
    if not worker_id or len(worker_id) > 128:
        raise ValueError("worker_id must contain 1 to 128 characters")
    heartbeat = await db.get(IntegrationWorkerHeartbeat, worker_id)
    if heartbeat is None:
        heartbeat = IntegrationWorkerHeartbeat(
            worker_id=worker_id,
            booted_at=booted_at,
            heartbeat_at=booted_at,
        )
        db.add(heartbeat)
    else:
        heartbeat.heartbeat_at = booted_at
    await db.flush()
    return heartbeat


async def record_scheduler_heartbeat(
    db: AsyncSession,
    *,
    worker_id: str,
    heartbeat_at: datetime,
    current_job: str | None,
    last_completed_job: str | None = None,
) -> IntegrationWorkerHeartbeat:
    heartbeat = await db.get(IntegrationWorkerHeartbeat, worker_id)
    if heartbeat is None:
        raise RuntimeError("scheduler boot heartbeat is missing")
    heartbeat.heartbeat_at = heartbeat_at
    heartbeat.current_job = current_job
    if last_completed_job is not None:
        heartbeat.last_completed_job = last_completed_job
    await db.flush()
    return heartbeat


class BoundedProviderExecutor:
    def __init__(self, *, max_workers: int) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._max_workers = max_workers
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="integration-provider",
        )
        self._tracked: dict[str, asyncio.Future[object]] = {}

    async def run(
        self,
        *,
        key: str,
        function: Callable[[], T],
        deadline_seconds: float,
    ) -> T:
        if deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        existing = self._tracked.get(key)
        if existing is not None and not existing.done():
            raise ProviderJobStillRunning("provider_job_already_running")
        if len([future for future in self._tracked.values() if not future.done()]) >= (
            self._max_workers
        ):
            raise ProviderExecutorSaturated("provider_executor_saturated")

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._executor, function)
        self._tracked[key] = future

        def remove_finished(completed: asyncio.Future[object]) -> None:
            if self._tracked.get(key) is completed:
                self._tracked.pop(key, None)

        future.add_done_callback(remove_finished)
        try:
            return await asyncio.wait_for(
                asyncio.shield(future),
                timeout=deadline_seconds,
            )
        except TimeoutError as exc:
            raise ProviderCallTimedOut("provider_timeout") from exc

    async def wait_for_tracked_calls(self) -> None:
        pending = tuple(
            future for future in self._tracked.values() if not future.done()
        )
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)


__all__ = [
    "BoundedProviderExecutor",
    "ProviderCallTimedOut",
    "ProviderExecutorSaturated",
    "ProviderJobStillRunning",
    "integration_alert_dedupe_key",
    "record_integration_failure",
    "record_integration_success",
    "record_scheduler_boot",
    "record_scheduler_heartbeat",
]
