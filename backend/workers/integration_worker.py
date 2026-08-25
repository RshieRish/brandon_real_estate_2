"""Dedicated scheduler plus internal ASGI health server."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import uvicorn

from config import settings
from database import AsyncSessionLocal, engine
from services.gmail_history_database import (
    create_gmail_history_engine,
    probe_gmail_history_session_affinity,
)
from services.gmail_message_sanitizer import validate_gmail_runtime_settings
from services.integration_health_service import (
    BoundedProviderExecutor,
    record_scheduler_boot,
    record_scheduler_heartbeat,
)
from services.notification_service import (
    enqueue_notification,
    run_notification_retry_pass,
)
from workers.health_app import WorkerReadinessProbe, create_health_app
from workers.jobs.gmail_history import GmailHistoryJob, run_gmail_history_job
from workers.jobs.gmail_receipts import GmailReceiptJob, build_gmail_model_call
from workers.jobs.integration_alerts import IntegrationAlertsJob
from workers.jobs.sydney_questions import SydneyQuestionsJob


EXPECTED_MIGRATION = "85e8b7c9d4f1"
gmail_history_job_runner = run_gmail_history_job
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
        return tuple((job.name, job.enabled, job.interval_seconds) for job in self.jobs)

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


@dataclass
class WorkerRuntime:
    registry: JobRegistry
    gmail_history_ready: bool
    history_engine: Any | None = None
    provider_executor: Any | None = None
    _closed: bool = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.provider_executor is not None:
                try:
                    await self.provider_executor.wait_for_tracked_calls()
                finally:
                    self.provider_executor.shutdown()
        finally:
            if self.history_engine is not None:
                await self.history_engine.dispose()


def _validated_alert_payload(
    *,
    provider: str,
    account_id: str,
    event: str,
    incident_id: str | None = None,
    detail_path: str | None = None,
) -> dict[str, str]:
    if provider != "gmail_task_intake":
        raise ValueError("gmail_alert_provider_invalid")
    try:
        canonical_account_id = str(UUID(account_id))
    except (TypeError, ValueError):
        raise ValueError("gmail_alert_account_invalid") from None
    if not event or len(event) > 64 or not event.replace("_", "").isalnum():
        raise ValueError("gmail_alert_event_invalid")
    payload = {
        "provider": provider,
        "account_id": canonical_account_id,
        "event": event,
    }
    if incident_id is None:
        if detail_path is not None:
            raise ValueError("gmail_alert_incident_invalid")
        return payload
    try:
        canonical_incident_id = str(UUID(incident_id))
    except (TypeError, ValueError):
        raise ValueError("gmail_alert_incident_invalid") from None
    expected_path = (
        f"/api/v1/agent-control/gmail/missing-message/incidents/{canonical_incident_id}"
    )
    if detail_path != expected_path:
        raise ValueError("gmail_alert_detail_path_invalid")
    payload["incident_id"] = canonical_incident_id
    payload["detail_path"] = expected_path
    return payload


def _durable_gmail_alert_sink(sessionmaker):
    async def enqueue(
        *,
        provider: str,
        account_id: str,
        event: str,
        dedupe_key: str,
        incident_id: str | None = None,
        detail_path: str | None = None,
    ) -> None:
        if not isinstance(dedupe_key, str) or not dedupe_key or len(dedupe_key) > 255:
            raise ValueError("gmail_alert_dedupe_invalid")
        payload = _validated_alert_payload(
            provider=provider,
            account_id=account_id,
            event=event,
            incident_id=incident_id,
            detail_path=detail_path,
        )
        async with sessionmaker() as db:
            await enqueue_notification(
                db,
                event_type="integration_alert",
                payload=payload,
                provider_key=provider,
                dedupe_key=dedupe_key,
            )
            await db.commit()

    return enqueue


async def _notification_job() -> None:
    await run_notification_retry_pass(limit=20)


async def _integration_alert_job() -> None:
    await IntegrationAlertsJob(sessionmaker=AsyncSessionLocal).run()


async def _unavailable_provider_job() -> None:
    raise RuntimeError("enabled provider job is not installed")


def build_job_registry(
    *,
    config=settings,
    gmail_runner: Callable[[], Awaitable[None]] | None = None,
    receipt_runner: Callable[[], Awaitable[None]] | None = None,
    sydney_runner: Callable[[], Awaitable[None]] | None = None,
    alert_runner: Callable[[], Awaitable[None]] | None = None,
) -> JobRegistry:
    effective_gmail_runner = gmail_runner or _unavailable_provider_job
    effective_receipt_runner = receipt_runner or _unavailable_provider_job
    effective_sydney_runner = sydney_runner or _unavailable_provider_job
    effective_alert_runner = alert_runner or _integration_alert_job
    return JobRegistry(
        (
            JobDefinition("notification_delivery", 60, True, _notification_job),
            JobDefinition(
                "gmail_history",
                120,
                config.GMAIL_TASK_INTAKE_ENABLED,
                effective_gmail_runner,
            ),
            JobDefinition(
                "gmail_receipts",
                30,
                config.GMAIL_TASK_INTAKE_ENABLED,
                effective_receipt_runner,
            ),
            JobDefinition(
                "sydney_questions",
                30,
                config.SYDNEY_TASK_QUESTIONS_ENABLED,
                effective_sydney_runner,
            ),
            JobDefinition(
                "integration_alerts",
                60,
                True,
                effective_alert_runner,
            ),
            JobDefinition(
                "instagram_health",
                86400,
                config.INSTAGRAM_INTEGRATION_ENABLED,
                _unavailable_provider_job,
            ),
        )
    )


async def initialize_worker_runtime(
    *,
    config=settings,
    sessionmaker=AsyncSessionLocal,
    primary_engine=engine,
    history_engine_factory=create_gmail_history_engine,
    history_probe=probe_gmail_history_session_affinity,
    provider_executor_factory=BoundedProviderExecutor,
    gmail_job_factory=gmail_history_job_runner,
    gmail_receipt_runner: Callable[[], Awaitable[None]] | None = None,
) -> WorkerRuntime:
    """Validate and compose resources before registry readiness or heartbeat."""

    gmail = validate_gmail_runtime_settings(config)
    sydney_enabled = bool(config.SYDNEY_TASK_QUESTIONS_ENABLED)
    if not gmail.enabled and not sydney_enabled:
        registry = build_job_registry(config=config)
        registry.initialize()
        return WorkerRuntime(
            registry=registry,
            gmail_history_ready=False,
        )

    history_engine = history_engine_factory(config) if gmail.enabled else None
    provider_executor = None
    try:
        if gmail.enabled:
            await history_probe(
                history_engine=history_engine,
                primary_engine=primary_engine,
            )
        provider_executor = provider_executor_factory(
            max_workers=gmail.provider_max_workers
        )
        gmail_runner = None
        receipt_runner = None
        if gmail.enabled:
            gmail_kwargs = {
                "enabled": True,
                "sessionmaker": sessionmaker,
                "history_engine": history_engine,
                "provider_executor": provider_executor,
                "participant_hash_key": gmail.participant_hash_key,
                "workspace_client_id": gmail.workspace_oauth_client_id,
                "workspace_client_secret": gmail.workspace_oauth_client_secret,
                "socket_timeout_seconds": gmail.socket_timeout_seconds,
                "provider_deadline_seconds": gmail.provider_deadline_seconds,
                "max_pages_per_run": gmail.max_pages_per_run,
                "whole_job_deadline_seconds": gmail.whole_job_deadline_seconds,
                "receipt_processing_deadline_seconds": (
                    gmail.receipt_processing_deadline_seconds
                ),
                "receipt_processing_stale_after_seconds": (
                    gmail.receipt_processing_stale_after_seconds
                ),
                "alert_sink": _durable_gmail_alert_sink(sessionmaker),
            }
            if gmail_job_factory is gmail_history_job_runner:
                history_job = GmailHistoryJob(**gmail_kwargs)
                gmail_runner = history_job.run
                from services.gmail_obligation_reconciliation import (
                    GmailObligationReconciliationService,
                )
                from services.gmail_task_extractor import GmailTaskExtractor

                extractor = GmailTaskExtractor(
                    executor=provider_executor,
                    model_call=build_gmail_model_call(
                        api_key=config.GEMINI_API_KEY,
                        socket_timeout_seconds=gmail.socket_timeout_seconds,
                    ),
                    deadline_seconds=gmail.provider_deadline_seconds,
                )
                receipt_runner = GmailReceiptJob(
                    enabled=True,
                    sessionmaker=sessionmaker,
                    history_service_provider=history_job.bound_service,
                    extractor=extractor,
                    reconciliation_service=GmailObligationReconciliationService(
                        sessionmaker=sessionmaker
                    ),
                    stale_after_seconds=(gmail.receipt_processing_stale_after_seconds),
                ).run
            else:
                # Preserve the injected Task 3 construction seam. Production
                # always takes the fully composed branch above.
                gmail_runner = gmail_job_factory(**gmail_kwargs)
                if gmail_receipt_runner is None:
                    raise RuntimeError("gmail_receipt_runner_required")
                receipt_runner = gmail_receipt_runner

        sydney_runner = None
        if sydney_enabled:
            from services.sydney_clarification_service import (
                SydneyClarificationService,
            )
            from services.sydney_telegram_dispatcher import (
                SydneyTelegramDispatcher,
                SydneyTelegramDispatcherConfig,
                send_telegram_message,
            )

            raw_keys = json.loads(config.SYDNEY_CLARIFICATION_CODE_KEYS_JSON)
            if not isinstance(raw_keys, dict):
                raise ValueError("sydney_clarification_keys_invalid")
            code_keys = {
                int(version): base64.b64decode(value, validate=True)
                for version, value in raw_keys.items()
            }
            telegram_config = SydneyTelegramDispatcherConfig(
                enabled=True,
                bot_token=config.SYDNEY_TELEGRAM_BOT_TOKEN,
                brandon_chat_id=config.SYDNEY_TELEGRAM_BRANDON_CHAT_ID,
                clarification_code_keys=code_keys,
                active_code_key_version=(
                    config.SYDNEY_CLARIFICATION_ACTIVE_KEY_VERSION
                ),
                provider_deadline_seconds=gmail.provider_deadline_seconds,
                provider_socket_timeout_seconds=gmail.socket_timeout_seconds,
            )
            clarification_service = SydneyClarificationService(
                sessionmaker=sessionmaker,
                brandon_chat_id=telegram_config.brandon_chat_id,
                clarification_code_keys=dict(telegram_config.clarification_code_keys),
                active_code_key_version=telegram_config.active_code_key_version,
            )
            dispatcher = SydneyTelegramDispatcher(
                sessionmaker=sessionmaker,
                executor=provider_executor,
                send_message=send_telegram_message,
                config=telegram_config,
                clock=lambda: datetime.now(UTC),
            )
            sydney_runner = SydneyQuestionsJob(
                enabled=True,
                sessionmaker=sessionmaker,
                clarification_service=clarification_service,
                dispatcher=dispatcher,
            ).run
        registry = build_job_registry(
            config=config,
            gmail_runner=gmail_runner,
            receipt_runner=receipt_runner,
            sydney_runner=sydney_runner,
            alert_runner=IntegrationAlertsJob(sessionmaker=sessionmaker).run,
        )
        registry.initialize()
        return WorkerRuntime(
            registry=registry,
            gmail_history_ready=gmail.enabled,
            history_engine=history_engine,
            provider_executor=provider_executor,
        )
    except BaseException:
        runtime = WorkerRuntime(
            registry=JobRegistry(()),
            gmail_history_ready=False,
            history_engine=history_engine,
            provider_executor=provider_executor,
        )
        await runtime.close()
        raise


async def run_scheduler_cycle(
    *,
    sessionmaker,
    worker_id: str,
    registry: JobRegistry,
    cycle_at: datetime,
    clock: Callable[[], datetime] | None = None,
    heartbeat_interval_seconds: float | None = None,
    heartbeat_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    if not registry.initialized:
        registry.initialize()
    current_time = clock or (lambda: cycle_at)
    heartbeat_interval = (
        heartbeat_interval_seconds
        if heartbeat_interval_seconds is not None
        else max(1, settings.INTEGRATION_WORKER_HEARTBEAT_SECONDS)
    )
    if heartbeat_interval <= 0:
        raise ValueError("worker heartbeat interval must be positive")
    async with sessionmaker() as db:
        await record_scheduler_boot(
            db,
            worker_id=worker_id,
            booted_at=cycle_at,
        )
        await db.commit()

    for job in registry.due_jobs(cycle_at):
        started_at = current_time()
        async with sessionmaker() as db:
            await record_scheduler_heartbeat(
                db,
                worker_id=worker_id,
                heartbeat_at=started_at,
                current_job=job.name,
            )
            await db.commit()

        async def maintain_heartbeat() -> None:
            while True:
                await heartbeat_sleep(heartbeat_interval)
                async with sessionmaker() as heartbeat_db:
                    await record_scheduler_heartbeat(
                        heartbeat_db,
                        worker_id=worker_id,
                        heartbeat_at=current_time(),
                        current_job=job.name,
                    )
                    await heartbeat_db.commit()

        runner_task = asyncio.create_task(
            job.runner(),
            name=f"integration-job:{job.name}",
        )
        heartbeat_task = asyncio.create_task(
            maintain_heartbeat(),
            name=f"integration-heartbeat:{job.name}",
        )
        try:
            done, _pending = await asyncio.wait(
                (runner_task, heartbeat_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                heartbeat_error = heartbeat_task.exception()
                if heartbeat_error is None:
                    raise RuntimeError("worker heartbeat stopped unexpectedly")
                raise heartbeat_error
            await runner_task
        finally:
            for task in (runner_task, heartbeat_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                runner_task,
                heartbeat_task,
                return_exceptions=True,
            )

        completed_at = current_time()
        registry.mark_completed(job, completed_at)
        async with sessionmaker() as db:
            await record_scheduler_heartbeat(
                db,
                worker_id=worker_id,
                heartbeat_at=completed_at,
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
            clock=lambda: datetime.now(UTC),
            heartbeat_interval_seconds=interval,
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

        outcomes = {task: task.exception() for task in tasks if task in done}
        for task in tasks:
            error = outcomes.get(task)
            if error is not None:
                raise error
        winner = scheduler_task if scheduler_task in done else server_task
        peer_name = "scheduler" if winner is scheduler_task else "server"
        raise RuntimeError(f"{peer_name} returned normally")
    finally:
        server.should_exit = True
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_worker() -> None:
    runtime = await initialize_worker_runtime()
    try:
        worker_id = (f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}")[:128]
        readiness = WorkerReadinessProbe(
            sessionmaker=AsyncSessionLocal,
            worker_id=worker_id,
            expected_migration=EXPECTED_MIGRATION,
            registry=runtime.registry,
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
                registry=runtime.registry,
            ),
            server_peer=server.serve(),
        )
    finally:
        await runtime.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()


__all__ = [
    "EXPECTED_MIGRATION",
    "JobDefinition",
    "JobRegistry",
    "WorkerRuntime",
    "build_job_registry",
    "gmail_history_job_runner",
    "initialize_worker_runtime",
    "run_scheduler_cycle",
    "supervise_worker_peers",
]
