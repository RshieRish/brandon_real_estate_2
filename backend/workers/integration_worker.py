"""Dedicated scheduler plus internal ASGI health server."""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import uvicorn

from config import settings
from database import AsyncSessionLocal
from services.integration_health_service import (
    record_scheduler_boot,
    record_scheduler_heartbeat,
)
from services.notification_service import run_notification_retry_pass
from workers.health_app import WorkerReadinessProbe, create_health_app


EXPECTED_MIGRATION = "82b5e3d7f0a1"
_FORBIDDEN_REGISTRY_NAME_PARTS = (
    "secret",
    "token",
    "password",
    "credential",
)


@dataclass(frozen=True)
class JobDefinition:
    name: str
    interval_seconds: int
    enabled: bool
    runner: Callable[[], Awaitable[None]]


class JobRegistry:
    def __init__(self, jobs: tuple[JobDefinition, ...]) -> None:
        self._jobs = jobs
        self._next_due_at: dict[str, datetime] = {}
        self.initialized = False

    @property
    def jobs(self) -> tuple[JobDefinition, ...]:
        if not self.initialized:
            return ()
        return tuple(sorted(self._jobs, key=lambda job: job.name))

    def initialize(self) -> None:
        names: set[str] = set()
        for job in self._jobs:
            normalized = job.name.strip().lower()
            if not normalized or len(normalized) > 128:
                raise ValueError("job name must contain 1 to 128 characters")
            if any(part in normalized for part in _FORBIDDEN_REGISTRY_NAME_PARTS):
                raise ValueError("job registry names must not contain secret values")
            if normalized in names:
                raise ValueError("duplicate job registry name")
            if job.interval_seconds < 1:
                raise ValueError("job interval must be positive")
            if not callable(job.runner):
                raise ValueError("job runner must be callable")
            names.add(normalized)
        self.initialized = True

    def readiness_snapshot(self) -> tuple[tuple[str, bool, int], ...]:
        if not self.initialized:
            return ()
        return tuple(
            (job.name, job.enabled, job.interval_seconds)
            for job in self.jobs
        )

    def due_jobs(self, cycle_at: datetime) -> tuple[JobDefinition, ...]:
        if not self.initialized:
            raise RuntimeError("job registry is not initialized")
        return tuple(
            job
            for job in self.jobs
            if job.enabled
            and (
                job.name not in self._next_due_at
                or self._next_due_at[job.name] <= cycle_at
            )
        )

    def mark_completed(self, job: JobDefinition, completed_at: datetime) -> None:
        self._next_due_at[job.name] = completed_at + timedelta(
            seconds=job.interval_seconds
        )


async def _notification_job() -> None:
    await run_notification_retry_pass(limit=20)


async def _disabled_until_provider_task_lands() -> None:
    raise RuntimeError("enabled provider job is not installed")


def build_job_registry() -> JobRegistry:
    return JobRegistry(
        (
            JobDefinition("notification_delivery", 60, True, _notification_job),
            JobDefinition(
                "gmail_history",
                120,
                settings.GMAIL_TASK_INTAKE_ENABLED,
                _disabled_until_provider_task_lands,
            ),
            JobDefinition(
                "sydney_questions",
                60,
                settings.SYDNEY_TASK_QUESTIONS_ENABLED,
                _disabled_until_provider_task_lands,
            ),
            JobDefinition(
                "instagram_health",
                86400,
                settings.INSTAGRAM_INTEGRATION_ENABLED,
                _disabled_until_provider_task_lands,
            ),
        )
    )


async def run_scheduler_cycle(
    *,
    sessionmaker,
    worker_id: str,
    registry: JobRegistry,
    cycle_at: datetime,
) -> None:
    if not registry.initialized:
        registry.initialize()
    async with sessionmaker() as db:
        await record_scheduler_boot(
            db,
            worker_id=worker_id,
            booted_at=cycle_at,
        )
        await db.commit()

    for job in registry.due_jobs(cycle_at):
        async with sessionmaker() as db:
            await record_scheduler_heartbeat(
                db,
                worker_id=worker_id,
                heartbeat_at=cycle_at,
                current_job=job.name,
            )
            await db.commit()
        await job.runner()
        registry.mark_completed(job, cycle_at)
        async with sessionmaker() as db:
            await record_scheduler_heartbeat(
                db,
                worker_id=worker_id,
                heartbeat_at=cycle_at,
                current_job=None,
                last_completed_job=job.name,
            )
            await db.commit()


async def run_scheduler(
    *,
    sessionmaker,
    worker_id: str,
    registry: JobRegistry,
) -> None:
    interval = max(1, settings.INTEGRATION_WORKER_HEARTBEAT_SECONDS)
    while True:
        await run_scheduler_cycle(
            sessionmaker=sessionmaker,
            worker_id=worker_id,
            registry=registry,
            cycle_at=datetime.now(UTC),
        )
        await asyncio.sleep(interval)


async def supervise_worker_peers(
    *,
    server,
    scheduler_peer: Coroutine[object, object, None],
    server_peer: Coroutine[object, object, None],
) -> None:
    scheduler_task = asyncio.create_task(
        scheduler_peer,
        name="integration-scheduler",
    )
    server_task = asyncio.create_task(
        server_peer,
        name="integration-health-server",
    )
    tasks = (scheduler_task, server_task)
    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        server.should_exit = True
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        outcomes = {
            task: task.exception()
            for task in tasks
            if task in done
        }
        for task in tasks:
            error = outcomes.get(task)
            if error is not None:
                raise error
        winner = scheduler_task if scheduler_task in done else server_task
        peer_name = (
            "scheduler" if winner is scheduler_task else "server"
        )
        raise RuntimeError(f"{peer_name} returned normally")
    finally:
        server.should_exit = True
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_worker() -> None:
    registry = build_job_registry()
    worker_id = (
        f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"
    )[:128]
    readiness = WorkerReadinessProbe(
        sessionmaker=AsyncSessionLocal,
        worker_id=worker_id,
        expected_migration=EXPECTED_MIGRATION,
        registry=registry,
        heartbeat_max_age=timedelta(
            seconds=max(
                1,
                settings.INTEGRATION_WORKER_HEARTBEAT_MAX_AGE_SECONDS,
            )
        ),
    )
    app = create_health_app(readiness)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=int(os.getenv("PORT", "8000")),
            log_level="info",
        )
    )
    await supervise_worker_peers(
        server=server,
        scheduler_peer=run_scheduler(
            sessionmaker=AsyncSessionLocal,
            worker_id=worker_id,
            registry=registry,
        ),
        server_peer=server.serve(),
    )


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()


__all__ = [
    "JobDefinition",
    "JobRegistry",
    "build_job_registry",
    "run_scheduler_cycle",
    "supervise_worker_peers",
]
