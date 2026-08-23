"""Minimal liveness and read-only readiness application for Railway."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from models.integration_health import IntegrationWorkerHeartbeat


class RegistryReadiness(Protocol):
    initialized: bool

    def readiness_snapshot(self) -> tuple[tuple[str, bool, int], ...]: ...


ReadinessCallable = Callable[[], Awaitable[tuple[str, ...]]]


class WorkerReadinessProbe:
    def __init__(
        self,
        *,
        sessionmaker,
        worker_id: str,
        expected_migration: str,
        registry: RegistryReadiness,
        heartbeat_max_age: timedelta,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._worker_id = worker_id
        self._expected_migration = expected_migration
        self._registry = registry
        self._heartbeat_max_age = heartbeat_max_age

    async def __call__(self) -> tuple[str, ...]:
        failures: set[str] = set()
        try:
            async with self._sessionmaker() as db:
                await db.execute(text("SELECT 1"))
                versions = list(
                    (
                        await db.execute(
                            text("SELECT version_num FROM alembic_version")
                        )
                    ).scalars()
                )
                if versions != [self._expected_migration]:
                    failures.add("migration")
                heartbeat = await db.scalar(
                    select(IntegrationWorkerHeartbeat).where(
                        IntegrationWorkerHeartbeat.worker_id == self._worker_id
                    )
                )
                if heartbeat is None:
                    failures.add("heartbeat")
                else:
                    heartbeat_at = heartbeat.heartbeat_at
                    if heartbeat_at.tzinfo is None:
                        heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
                    if datetime.now(UTC) - heartbeat_at > self._heartbeat_max_age:
                        failures.add("heartbeat")
        except Exception:
            return ("database",)

        if not self._registry.initialized:
            failures.add("job_registry")
        else:
            try:
                self._registry.readiness_snapshot()
            except Exception:
                failures.add("job_registry")
        return tuple(sorted(failures))


def create_health_app(readiness_probe: ReadinessCallable) -> FastAPI:
    app = FastAPI(
        title="Integration worker health",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "integration-worker"}

    @app.get("/ready")
    async def ready():
        try:
            failures = tuple(await readiness_probe())
        except Exception:
            failures = ("database",)
        bounded = sorted(
            {
                component
                for component in failures
                if component
                in {"database", "migration", "heartbeat", "job_registry"}
            }
        )
        if bounded:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "service": "integration-worker",
                    "failing_components": bounded,
                },
            )
        return {
            "status": "ready",
            "service": "integration-worker",
            "database": "ok",
            "migration": "ok",
            "heartbeat": "ok",
            "job_registry": "ok",
        }

    return app


__all__ = ["WorkerReadinessProbe", "create_health_app"]
