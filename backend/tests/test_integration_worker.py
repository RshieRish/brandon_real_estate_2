from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "85e8b7c9d4f1"
UTC = timezone.utc


@pytest.fixture(scope="module")
def runtime_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def worker_database(runtime_database):
    url, sync_engine = runtime_database
    with sync_engine.begin() as connection:
        connection.execute(
            sa.text(
                "TRUNCATE TABLE gmail_sync_accounts, notification_jobs, settings, "
                "integration_health_states, integration_worker_heartbeats CASCADE"
            )
        )
    engine = create_async_engine(async_test_url(url), pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessionmaker
    finally:
        await engine.dispose()


def test_worker_feature_flags_default_off_and_web_app_starts_no_integration_loop() -> (
    None
):
    from config import Settings

    settings = Settings(JWT_SECRET="test-secret")
    assert settings.GMAIL_TASK_INTAKE_ENABLED is False
    assert settings.SYDNEY_TASK_QUESTIONS_ENABLED is False
    assert settings.INSTAGRAM_INTEGRATION_ENABLED is False

    main_source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    assert "workers.integration_worker" not in main_source
    assert "GMAIL_TASK_INTAKE_ENABLED" not in main_source
    assert "SYDNEY_TASK_QUESTIONS_ENABLED" not in main_source
    assert "INSTAGRAM_INTEGRATION_ENABLED" not in main_source


def test_gmail_model_uses_strict_json_schema_provider_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.gmail_task_extractor import GmailObligationModelResponse
    from workers.jobs.gmail_receipts import build_gmail_model_call

    observed: dict[str, object] = {}

    class _ModelClient:
        def __init__(self, **_kwargs):
            self.models = self

        def generate_content(self, **kwargs):
            observed.update(kwargs)
            return SimpleNamespace(
                text=(
                    '{\n  "schema_version": "gmail-task-v1",\n'
                    '  "actions": []\n}'
                ),
                parsed={
                    "schema_version": "gmail-task-v1",
                    "actions": [],
                },
            )

    monkeypatch.setattr("google.genai.Client", _ModelClient)
    model_call = build_gmail_model_call(
        api_key="test-gemini-key",
        socket_timeout_seconds=1,
    )
    result = model_call(
        SimpleNamespace(
            prompt="Controlled schema probe.",
            system_instruction="Return only the supplied schema.",
            response_model=GmailObligationModelResponse,
        )
    )

    config = observed["config"]
    assert config.response_schema is None
    schema = config.response_json_schema
    assert isinstance(schema, dict)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["GmailObligationModelAction"][
        "additionalProperties"
    ] is False

    def assert_provider_supported(value: object) -> None:
        if isinstance(value, dict):
            assert "default" not in value
            assert "maxItems" not in value
            assert "maxLength" not in value
            assert "minLength" not in value
            for nested in value.values():
                assert_provider_supported(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_provider_supported(nested)

    assert_provider_supported(schema)
    assert result == {
        "schema_version": "gmail-task-v1",
        "actions": [],
    }


def test_gmail_runtime_requires_inner_socket_timeout_below_outer_deadline() -> None:
    from services.gmail_message_sanitizer import validate_gmail_runtime_settings

    config = SimpleNamespace(
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
        INTEGRATION_PROVIDER_MAX_WORKERS=1,
        INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS=30,
        INTEGRATION_PROVIDER_DEADLINE_SECONDS=30,
        GMAIL_HISTORY_MAX_PAGES_PER_RUN=1,
        GMAIL_HISTORY_JOB_DEADLINE_SECONDS=60,
        GMAIL_RECEIPT_PROCESSING_DEADLINE_SECONDS=30,
        GMAIL_RECEIPT_PROCESSING_STALE_AFTER_SECONDS=120,
        GOOGLE_WORKSPACE_CLIENT_ID="worker-client-id",
        GOOGLE_WORKSPACE_CLIENT_SECRET="worker-client-secret",
        GOOGLE_WORKSPACE_REDIRECT_URI="https://example.test/oauth/callback",
        DATABASE_URL="postgresql+asyncpg://worker@localhost/task_intake",
        GMAIL_HISTORY_DATABASE_URL=(
            "postgresql+asyncpg://worker@localhost/task_intake?ssl=require"
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="^provider_socket_timeout_exceeds_deadline$",
    ):
        validate_gmail_runtime_settings(config)


def test_gmail_runtime_reserves_receipt_finalization_after_provider_deadline() -> None:
    from services.gmail_message_sanitizer import validate_gmail_runtime_settings

    config = SimpleNamespace(
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
        INTEGRATION_PROVIDER_MAX_WORKERS=1,
        INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS=5,
        INTEGRATION_PROVIDER_DEADLINE_SECONDS=30,
        GMAIL_HISTORY_MAX_PAGES_PER_RUN=1,
        GMAIL_HISTORY_JOB_DEADLINE_SECONDS=60,
        GMAIL_RECEIPT_PROCESSING_DEADLINE_SECONDS=34.999,
        GMAIL_RECEIPT_PROCESSING_STALE_AFTER_SECONDS=120,
        GOOGLE_WORKSPACE_CLIENT_ID="worker-client-id",
        GOOGLE_WORKSPACE_CLIENT_SECRET="worker-client-secret",
        GOOGLE_WORKSPACE_REDIRECT_URI="https://example.test/oauth/callback",
        DATABASE_URL="postgresql+asyncpg://worker@localhost/task_intake",
        GMAIL_HISTORY_DATABASE_URL=(
            "postgresql+asyncpg://worker@localhost/task_intake?ssl=require"
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="^gmail_receipt_processing_deadline_invalid$",
    ):
        validate_gmail_runtime_settings(config)


def test_worker_targets_current_head_and_registers_real_gmail_job_symbol() -> None:
    from workers import integration_worker
    from workers.jobs.gmail_history import run_gmail_history_job

    assert integration_worker.EXPECTED_MIGRATION == REVISION
    assert integration_worker.gmail_history_job_runner is run_gmail_history_job
    source = (
        Path(__file__).parents[1] / "workers" / "integration_worker.py"
    ).read_text(encoding="utf-8")
    assert (
        "_disabled_until_provider_task_lands"
        not in source.split('"gmail_history"', 1)[1].split('"sydney_questions"', 1)[0]
    )


def test_task9_job_modules_are_real_and_registry_uses_deterministic_schedules() -> None:
    from config import Settings
    from workers.integration_worker import build_job_registry
    from workers.jobs.gmail_receipts import GmailReceiptJob
    from workers.jobs.integration_alerts import IntegrationAlertsJob
    from workers.jobs.sydney_questions import SydneyQuestionsJob

    async def no_op() -> None:
        return None

    config = Settings(
        JWT_SECRET="test-secret",
        GMAIL_TASK_INTAKE_ENABLED=True,
        SYDNEY_TASK_QUESTIONS_ENABLED=True,
    )
    registry = build_job_registry(
        config=config,
        gmail_runner=no_op,
        receipt_runner=no_op,
        sydney_runner=no_op,
        alert_runner=no_op,
    )
    registry.initialize()
    assert registry.readiness_snapshot() == (
        ("gmail_history", True, 120),
        ("gmail_receipts", True, 30),
        ("instagram_health", False, 86400),
        ("integration_alerts", True, 60),
        ("notification_delivery", True, 60),
        ("sydney_questions", True, 30),
    )
    assert GmailReceiptJob.__module__ == "workers.jobs.gmail_receipts"
    assert SydneyQuestionsJob.__module__ == "workers.jobs.sydney_questions"
    assert IntegrationAlertsJob.__module__ == "workers.jobs.integration_alerts"


@pytest.mark.asyncio
async def test_integration_alert_job_leases_and_deduplicates_transition_events(
    worker_database,
) -> None:
    from models.integration_health import IntegrationHealthState
    from models.notification_job import NotificationJob
    from services.integration_health_service import (
        record_integration_failure,
        record_integration_success,
    )
    from workers.jobs.integration_alerts import IntegrationAlertsJob

    _engine, sessionmaker = worker_database
    current = datetime(2026, 8, 24, 14, 0, tzinfo=UTC)

    async with sessionmaker() as session:
        await record_integration_failure(
            session,
            provider="gmail_task_intake",
            state="degraded",
            checked_at=current,
            error_category="provider_timeout",
            raw_error="must not persist",
        )
        await session.commit()

    clock_value = current
    job = IntegrationAlertsJob(
        sessionmaker=sessionmaker,
        clock=lambda: clock_value,
    )
    await job.run()
    await job.run()

    clock_value = current + timedelta(hours=24)
    await job.run()
    await job.run()

    async with sessionmaker() as session:
        await record_integration_success(
            session,
            provider="gmail_task_intake",
            checked_at=current + timedelta(hours=25),
        )
        await session.commit()
    clock_value = current + timedelta(hours=25)
    await job.run()
    await job.run()
    clock_value = current + timedelta(hours=26)
    await job.run()

    async with sessionmaker() as session:
        await record_integration_failure(
            session,
            provider="gmail_task_intake",
            state="degraded",
            checked_at=current + timedelta(hours=27),
            error_category="provider_timeout",
            raw_error="must not persist again",
        )
        await session.commit()
    clock_value = current + timedelta(hours=27)
    await job.run()
    await job.run()

    async with sessionmaker() as session:
        health = await session.get(IntegrationHealthState, "gmail_task_intake")
        notifications = list(
            (
                await session.scalars(
                    sa.select(NotificationJob).order_by(NotificationJob.created_at)
                )
            ).all()
        )
    assert len(notifications) == 4
    assert [job.payload_dict["event"] for job in notifications] == [
        "opened",
        "reminder",
        "recovered",
        "opened",
    ]
    assert len({job.dedupe_key for job in notifications}) == 4
    assert all("must not persist" not in job.payload_json for job in notifications)
    assert health is not None
    assert health.last_alerted_at == current + timedelta(hours=27)


@pytest.mark.asyncio
async def test_receipt_job_only_claims_the_oauth_bound_gmail_account(
    worker_database,
) -> None:
    from models.gmail_task_intake import GmailMessageReceipt, GmailSyncAccount
    from workers.jobs.gmail_receipts import GmailReceiptJob

    _engine, sessionmaker = worker_database
    first_account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="first@example.test",
        mode="shadow",
    )
    second_account = GmailSyncAccount(
        id=uuid4(),
        workspace_email="second@example.test",
        mode="shadow",
    )
    first_receipt = GmailMessageReceipt(
        account_id=first_account.id,
        gmail_message_id="bound-account-message",
        gmail_thread_id="bound-account-thread",
        direction="received",
        message_at=datetime(2026, 8, 24, 14, 0, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
    )
    second_receipt = GmailMessageReceipt(
        account_id=second_account.id,
        gmail_message_id="other-account-message",
        gmail_thread_id="other-account-thread",
        direction="received",
        message_at=datetime(2026, 8, 24, 14, 0, tzinfo=UTC),
        labels_json='["INBOX"]',
        processing_state="pending",
    )
    async with sessionmaker() as session:
        session.add_all((first_account, second_account))
        await session.flush()
        session.add_all((first_receipt, second_receipt))
        await session.commit()

    seen: list[object] = []

    class _BoundHistoryService:
        async def process_receipt(self, receipt_id, *, consumer):
            del consumer
            seen.append(receipt_id)

    async def bound_service():
        return first_account.id, _BoundHistoryService()

    job = GmailReceiptJob(
        enabled=True,
        sessionmaker=sessionmaker,
        history_service_provider=bound_service,
        extractor=object(),
        reconciliation_service=object(),
    )
    await job.run()
    assert seen == [first_receipt.id]


def test_task9_jobs_are_not_scheduled_from_fastapi_main_lifespan() -> None:
    main_source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    for forbidden in (
        "gmail_receipts",
        "sydney_questions",
        "integration_alerts",
        "run_gmail_history_job",
        "run_gmail_receipts_job",
        "run_sydney_questions_job",
        "run_integration_alerts_job",
    ):
        assert forbidden not in main_source


def test_job_registry_validates_before_becoming_readiness_eligible() -> None:
    from workers.integration_worker import JobDefinition, JobRegistry

    async def no_op() -> None:
        return None

    registry = JobRegistry(
        (
            JobDefinition(
                name="notification_delivery",
                interval_seconds=60,
                enabled=True,
                runner=no_op,
            ),
            JobDefinition(
                name="gmail_history",
                interval_seconds=120,
                enabled=False,
                runner=no_op,
            ),
        )
    )
    assert registry.initialized is False
    assert registry.readiness_snapshot() == ()
    registry.initialize()
    assert registry.initialized is True
    assert registry.readiness_snapshot() == (
        ("gmail_history", False, 120),
        ("notification_delivery", True, 60),
    )

    with pytest.raises(ValueError, match="duplicate"):
        JobRegistry(
            (
                JobDefinition("same", 60, True, no_op),
                JobDefinition("same", 120, False, no_op),
            )
        ).initialize()
    with pytest.raises(ValueError, match="secret"):
        JobRegistry((JobDefinition("gmail_token", 60, True, no_op),)).initialize()
    with pytest.raises(ValueError, match="interval"):
        JobRegistry((JobDefinition("invalid_interval", 0, True, no_op),)).initialize()


def test_default_gmail_job_requires_a_runtime_participant_hash_key() -> None:
    from workers.jobs.gmail_history import GmailHistoryJob

    with pytest.raises(ValueError, match="^participant_hash_key_required$"):
        GmailHistoryJob(
            enabled=True,
            sessionmaker=object(),
            history_engine=object(),
            provider_executor=object(),
        )


async def test_enabled_gmail_startup_probes_before_job_registration_or_heartbeat(
    worker_database,
    runtime_database,
) -> None:
    from config import Settings
    from models.integration_health import IntegrationWorkerHeartbeat
    from workers.integration_worker import initialize_worker_runtime

    primary_engine, sessionmaker = worker_database
    url, _sync_engine = runtime_database
    direct_url = async_test_url(url).render_as_string(hide_password=False)
    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=direct_url,
        GMAIL_HISTORY_DATABASE_URL=direct_url,
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="h" * 32,
        GOOGLE_WORKSPACE_CLIENT_ID="worker-client-id",
        GOOGLE_WORKSPACE_CLIENT_SECRET="worker-client-secret",
        INTEGRATION_PROVIDER_MAX_WORKERS=3,
        INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS=7,
        INTEGRATION_PROVIDER_DEADLINE_SECONDS=20,
        GMAIL_HISTORY_MAX_PAGES_PER_RUN=17,
        GMAIL_HISTORY_JOB_DEADLINE_SECONDS=55,
        GMAIL_RECEIPT_PROCESSING_DEADLINE_SECONDS=25,
        GMAIL_RECEIPT_PROCESSING_STALE_AFTER_SECONDS=60,
    )
    calls: list[str] = []

    class _HistoryEngine:
        disposed = False

        async def dispose(self):
            self.disposed = True
            calls.append("dispose")

    history_engine = _HistoryEngine()

    def engine_factory(_config):
        calls.append("history_engine")
        return history_engine

    async def probe(*, history_engine, primary_engine):
        assert history_engine is not None
        assert primary_engine is primary_engine_fixture
        calls.append("probe")
        return SimpleNamespace(backend_pid=54321)

    class _SharedExecutor:
        async def wait_for_tracked_calls(self):
            calls.append("executor_wait")

        def shutdown(self):
            calls.append("executor_shutdown")

    shared_executor = _SharedExecutor()

    def executor_factory(*, max_workers):
        calls.append(f"executor:{max_workers}")
        return shared_executor

    async def gmail_runner():
        return None

    def job_factory(**kwargs):
        calls.append("gmail_job")
        assert kwargs["history_engine"] is history_engine
        assert kwargs["provider_executor"] is shared_executor
        assert kwargs["participant_hash_key"] == b"h" * 32
        assert kwargs["workspace_client_id"] == "worker-client-id"
        assert kwargs["workspace_client_secret"] == "worker-client-secret"
        assert kwargs["socket_timeout_seconds"] == 7
        assert kwargs["provider_deadline_seconds"] == 20
        assert kwargs["max_pages_per_run"] == 17
        assert kwargs["whole_job_deadline_seconds"] == 55
        assert kwargs["receipt_processing_deadline_seconds"] == 25
        assert kwargs["receipt_processing_stale_after_seconds"] == 60
        return gmail_runner

    primary_engine_fixture = primary_engine
    runtime = await initialize_worker_runtime(
        config=config,
        sessionmaker=sessionmaker,
        primary_engine=primary_engine,
        history_engine_factory=engine_factory,
        history_probe=probe,
        provider_executor_factory=executor_factory,
        gmail_job_factory=job_factory,
        gmail_receipt_runner=gmail_runner,
    )
    try:
        assert calls == [
            "history_engine",
            "probe",
            "executor:3",
            "gmail_job",
        ]
        assert runtime.registry.initialized is True
        gmail_job = next(
            job for job in runtime.registry.jobs if job.name == "gmail_history"
        )
        assert gmail_job.enabled is True
        assert gmail_job.runner is gmail_runner
        receipt_job = next(
            job for job in runtime.registry.jobs if job.name == "gmail_receipts"
        )
        assert receipt_job.enabled is True
        assert receipt_job.runner is gmail_runner
        async with sessionmaker() as session:
            assert (
                await session.scalar(
                    sa.select(sa.func.count()).select_from(IntegrationWorkerHeartbeat)
                )
                == 0
            )
    finally:
        await runtime.close()
    assert calls[-3:] == ["executor_wait", "executor_shutdown", "dispose"]


@pytest.mark.asyncio
async def test_sydney_only_startup_registers_real_question_job_without_gmail_probe(
    worker_database,
) -> None:
    import base64
    import json

    from config import Settings
    from workers.integration_worker import initialize_worker_runtime
    from workers.jobs.sydney_questions import SydneyQuestionsJob

    primary_engine, sessionmaker = worker_database
    config = Settings(
        JWT_SECRET="test-secret",
        SYDNEY_TASK_QUESTIONS_ENABLED=True,
        SYDNEY_TELEGRAM_BOT_TOKEN="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd",
        SYDNEY_TELEGRAM_BRANDON_CHAT_ID="99887766",
        SYDNEY_CLARIFICATION_CODE_KEYS_JSON=json.dumps(
            {"1": base64.b64encode(b"s" * 32).decode("ascii")}
        ),
        SYDNEY_CLARIFICATION_ACTIVE_KEY_VERSION=1,
    )
    calls: list[str] = []

    class _SharedExecutor:
        async def wait_for_tracked_calls(self):
            calls.append("executor_wait")

        def shutdown(self):
            calls.append("executor_shutdown")

    def executor_factory(*, max_workers):
        calls.append(f"executor:{max_workers}")
        return _SharedExecutor()

    def forbidden_history_engine(_config):
        raise AssertionError("gmail_history_engine_must_stay_disabled")

    async def forbidden_probe(**_kwargs):
        raise AssertionError("gmail_affinity_probe_must_stay_disabled")

    runtime = await initialize_worker_runtime(
        config=config,
        sessionmaker=sessionmaker,
        primary_engine=primary_engine,
        history_engine_factory=forbidden_history_engine,
        history_probe=forbidden_probe,
        provider_executor_factory=executor_factory,
    )
    try:
        question_job = next(
            job for job in runtime.registry.jobs if job.name == "sydney_questions"
        )
        assert question_job.enabled is True
        assert isinstance(question_job.runner.__self__, SydneyQuestionsJob)
        dispatcher_clock = question_job.runner.__self__._dispatcher._clock
        assert callable(dispatcher_clock)
        assert dispatcher_clock().tzinfo is UTC
        assert runtime.gmail_history_ready is False
        assert runtime.history_engine is None
        assert calls == ["executor:4"]
    finally:
        await runtime.close()
    assert calls == ["executor:4", "executor_wait", "executor_shutdown"]


async def test_registered_default_gmail_runner_uses_real_service_with_direct_engine(
    worker_database,
    runtime_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import Settings
    from models.gmail_task_intake import GmailSyncAccount
    from models.notification_job import NotificationJob
    from models.setting import Setting
    import services.gmail_history_adapter as adapter_module
    import services.gmail_history_service as history_service_module
    from services.gmail_origin_service import GmailOriginService
    from services.integration_health_service import BoundedProviderExecutor
    from services.notification_service import render_notification_email
    from sqlalchemy.pool import NullPool
    import workers.integration_worker as worker_module
    from workers.integration_worker import (
        build_job_registry,
        initialize_worker_runtime,
        run_scheduler_cycle,
    )

    primary_engine, sessionmaker = worker_database
    url, _sync_engine = runtime_database
    direct_url = async_test_url(url).render_as_string(hide_password=False)
    account = GmailSyncAccount(
        workspace_email="default-worker@example.test",
        committed_history_id=None,
        mode="shadow",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add_all(
            [
                Setting(
                    key="google_workspace_gmail_account_id",
                    value=str(account.id),
                ),
                Setting(
                    key="google_workspace_refresh_token",
                    value="default-worker-database-token",
                ),
            ]
        )
        await session.commit()
        account_id = account.id

    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=direct_url,
        GMAIL_HISTORY_DATABASE_URL=direct_url,
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="p" * 32,
        GOOGLE_WORKSPACE_CLIENT_ID="default-worker-client-id",
        GOOGLE_WORKSPACE_CLIENT_SECRET="default-worker-client-secret",
        GOOGLE_WORKSPACE_REDIRECT_URI="https://example.test/workspace/callback",
        INTEGRATION_PROVIDER_MAX_WORKERS=1,
        INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS=0.1,
        INTEGRATION_PROVIDER_DEADLINE_SECONDS=0.25,
        GMAIL_HISTORY_MAX_PAGES_PER_RUN=19,
        GMAIL_HISTORY_JOB_DEADLINE_SECONDS=45,
        GMAIL_RECEIPT_PROCESSING_DEADLINE_SECONDS=8,
        GMAIL_RECEIPT_PROCESSING_STALE_AFTER_SECONDS=40,
    )
    direct_history_engine = create_async_engine(
        direct_url,
        poolclass=NullPool,
    )
    shared_executor = BoundedProviderExecutor(max_workers=1)
    observed: dict[str, object] = {}
    retry_values: list[int] = []
    provider_calls: list[str] = []
    model_entered = threading.Event()
    model_release = threading.Event()

    class _ModelClient:
        def __init__(self, **kwargs):
            observed["model_client_kwargs"] = kwargs
            self.models = self

        def generate_content(self, **kwargs):
            observed["model_generate_kwargs"] = kwargs
            model_entered.set()
            model_release.wait(timeout=2)
            return SimpleNamespace(
                text='{"schema_version":"gmail-task-v1","actions":[]}'
            )

    monkeypatch.setattr("google.genai.Client", _ModelClient)

    class _ProviderError(RuntimeError):
        def __init__(self, status: int):
            super().__init__("provider fixture error")
            self.resp = SimpleNamespace(status=status)

    class _Request:
        def __init__(self, payload=None, *, error: Exception | None = None):
            self.payload = payload
            self.error = error

        def execute(self, *, num_retries):
            retry_values.append(num_retries)
            if self.error is not None:
                raise self.error
            return self.payload

    class _Users:
        def getProfile(self, **kwargs):
            provider_calls.append("profile")
            observed["profile_request"] = kwargs
            return _Request(
                {
                    "emailAddress": account.workspace_email,
                    "historyId": "900",
                }
            )

        def history(self):
            return self

        def list(self, **_kwargs):
            provider_calls.append("history")
            return _Request(
                {
                    "historyId": "901",
                    "history": [
                        {
                            "id": "901",
                            "messagesAdded": [
                                {
                                    "message": {
                                        "id": "deleted-message",
                                        "threadId": "deleted-thread",
                                    }
                                }
                            ],
                        }
                    ],
                }
            )

        def messages(self):
            return self

        def get(self, **_kwargs):
            provider_calls.append("message_metadata")
            return _Request(error=_ProviderError(404))

    class _Gmail:
        def users(self):
            return _Users()

    def build_bound_client(**kwargs):
        observed["client_kwargs"] = kwargs
        return _Gmail()

    real_adapter_init = adapter_module.GmailHistoryAdapter.__init__

    def record_adapter_init(self, **kwargs):
        observed["adapter_kwargs"] = dict(kwargs)
        real_adapter_init(self, **kwargs)

    real_service_init = history_service_module.GmailHistoryService.__init__

    def record_service_init(self, **kwargs):
        observed["service_kwargs"] = dict(kwargs)
        real_service_init(self, **kwargs)

    monkeypatch.setattr(adapter_module, "build_gmail_service", build_bound_client)
    monkeypatch.setattr(
        adapter_module.GmailHistoryAdapter,
        "__init__",
        record_adapter_init,
    )
    monkeypatch.setattr(
        history_service_module.GmailHistoryService,
        "__init__",
        record_service_init,
    )

    async def successful_probe(*, history_engine, primary_engine):
        assert history_engine is direct_history_engine
        assert primary_engine is primary_engine_fixture
        return SimpleNamespace(backend_pid=61234)

    delivery_passes: list[int] = []

    async def deliver_pending_alerts(*, limit: int) -> int:
        assert limit == 20
        async with sessionmaker() as session:
            alerts = list(
                (
                    await session.scalars(
                        sa.select(NotificationJob).where(
                            NotificationJob.status == "pending"
                        )
                    )
                ).all()
            )
            for queued in alerts:
                queued.status = "delivered"
            await session.commit()
        delivery_passes.append(len(alerts))
        return len(alerts)

    monkeypatch.setattr(
        worker_module,
        "run_notification_retry_pass",
        deliver_pending_alerts,
    )

    runtime = None
    primary_engine_fixture = primary_engine
    try:
        runtime = await initialize_worker_runtime(
            config=config,
            sessionmaker=sessionmaker,
            primary_engine=primary_engine,
            history_engine_factory=lambda _config: direct_history_engine,
            history_probe=successful_probe,
            provider_executor_factory=lambda **_kwargs: shared_executor,
        )
        gmail_job = next(
            job for job in runtime.registry.jobs if job.name == "gmail_history"
        )
        assert gmail_job.enabled is True
        assert tuple(job.name for job in runtime.registry.jobs) == (
            "gmail_history",
            "gmail_receipts",
            "instagram_health",
            "integration_alerts",
            "notification_delivery",
            "sydney_questions",
        )
        receipt_job = next(
            job.runner.__self__
            for job in runtime.registry.jobs
            if job.name == "gmail_receipts"
        )
        from services.gmail_message_sanitizer import SanitizedGmailMessage
        from services.gmail_task_extractor import GmailTaskExtractionError

        model_message = SanitizedGmailMessage(
            message_id="production-model-timeout-message",
            thread_id="production-model-timeout-thread",
            direction="received",
            message_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
            sender_hmac="a" * 64,
            recipient_hmacs=("b" * 64,),
            subject_preview="Bounded model request",
            body_hash=hashlib.sha256(b"bounded model request").hexdigest(),
            labels=("INBOX",),
            processing_state="processing",
            classification="eligible",
            transient_body_text="Please prepare the bounded model request.",
            body_truncated=False,
        )
        started = time.monotonic()
        with pytest.raises(GmailTaskExtractionError) as timed_out:
            await receipt_job._extractor.extract(
                account_id=account_id,
                message=model_message,
            )
        assert str(timed_out.value) == "gmail_extraction_timeout"
        assert time.monotonic() - started < 1
        assert model_entered.is_set()
        model_client_kwargs = observed["model_client_kwargs"]
        assert model_client_kwargs["api_key"] == config.GEMINI_API_KEY
        assert model_client_kwargs["http_options"].timeout == 100
        assert model_client_kwargs["http_options"].timeout < int(
            config.INTEGRATION_PROVIDER_DEADLINE_SECONDS * 1000
        )
        assert len(shared_executor._tracked) == 1
        assert not next(iter(shared_executor._tracked.values())).done()
        with pytest.raises(GmailTaskExtractionError) as still_running:
            await receipt_job._extractor.extract(
                account_id=account_id,
                message=model_message,
            )
        assert str(still_running.value) == "gmail_extraction_already_running"
        model_release.set()
        await shared_executor.wait_for_tracked_calls()
        assert shared_executor._tracked == {}
        cycle_at = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
        await run_scheduler_cycle(
            sessionmaker=sessionmaker,
            worker_id="default-composition-worker",
            registry=runtime.registry,
            cycle_at=cycle_at,
        )
        async with sessionmaker() as session:
            stored = await session.get(GmailSyncAccount, account_id)
            assert stored.committed_history_id == "900"
        assert delivery_passes == [0]

        await run_scheduler_cycle(
            sessionmaker=sessionmaker,
            worker_id="default-composition-worker",
            registry=runtime.registry,
            cycle_at=cycle_at + timedelta(seconds=120),
        )

        service_kwargs = observed["service_kwargs"]
        assert isinstance(service_kwargs["origin_observer"], GmailOriginService)
        alert_sink = service_kwargs["alert_sink"]
        assert callable(alert_sink)
        async with sessionmaker() as session:
            alert = await session.scalar(
                sa.select(NotificationJob).where(
                    NotificationJob.provider_key == "gmail_task_intake"
                )
            )
            assert alert is not None
            assert alert.event_type == "integration_alert"
            assert alert.dedupe_key
            incident_id = alert.payload_dict["incident_id"]
            incident_detail_path = (
                f"/api/v1/agent-control/gmail/missing-message/incidents/{incident_id}"
            )
            assert alert.status == "delivered"
            assert alert.payload_dict == {
                "provider": "gmail_task_intake",
                "account_id": str(account_id),
                "event": "message_not_found",
                "incident_id": incident_id,
                "detail_path": incident_detail_path,
            }
            _subject, rendered_body = render_notification_email(
                alert.event_type,
                alert.payload_dict,
                subject_override=alert.subject,
            )
            assert incident_id in rendered_body
            assert incident_detail_path in rendered_body
            incident_dedupe_key = alert.dedupe_key

        assert delivery_passes == [0, 1]
        calls_before_restart = tuple(provider_calls)
        reconstructed_registry = build_job_registry(
            config=config,
            gmail_runner=gmail_job.runner,
            receipt_runner=next(
                job.runner
                for job in runtime.registry.jobs
                if job.name == "gmail_receipts"
            ),
            alert_runner=next(
                job.runner
                for job in runtime.registry.jobs
                if job.name == "integration_alerts"
            ),
        )
        reconstructed_registry.initialize()
        await run_scheduler_cycle(
            sessionmaker=sessionmaker,
            worker_id="reconstructed-composition-worker",
            registry=reconstructed_registry,
            cycle_at=cycle_at + timedelta(seconds=121),
        )
        assert tuple(provider_calls) == calls_before_restart
        assert delivery_passes == [0, 1, 0]

        for _attempt in range(2):
            await alert_sink(
                provider="gmail_task_intake",
                account_id=str(account_id),
                event="message_not_found",
                dedupe_key=incident_dedupe_key,
                incident_id=incident_id,
                detail_path=incident_detail_path,
            )
        async with sessionmaker() as session:
            incident_alert = await session.scalar(
                sa.select(NotificationJob).where(
                    NotificationJob.provider_key == "gmail_task_intake",
                    NotificationJob.dedupe_key == incident_dedupe_key,
                )
            )
            assert incident_alert is not None
            assert incident_alert.payload_dict == {
                "provider": "gmail_task_intake",
                "account_id": str(account_id),
                "event": "message_not_found",
                "incident_id": incident_id,
                "detail_path": incident_detail_path,
            }
            assert (
                await session.scalar(
                    sa.select(sa.func.count()).select_from(NotificationJob)
                )
                == 1
            )
        assert not {
            "message_id",
            "thread_id",
            "page_token",
            "subject",
            "body",
            "refresh_token",
        }.intersection(incident_alert.payload_dict)
    finally:
        model_release.set()
        if runtime is not None:
            await runtime.close()
        else:
            await shared_executor.wait_for_tracked_calls()
            shared_executor.shutdown()
            await direct_history_engine.dispose()

    assert observed["client_kwargs"] == {
        "refresh_token": "default-worker-database-token",
        "client_id": "default-worker-client-id",
        "client_secret": "default-worker-client-secret",
        "socket_timeout_seconds": 0.1,
    }
    adapter_kwargs = observed["adapter_kwargs"]
    assert adapter_kwargs["executor"] is shared_executor
    assert adapter_kwargs["deadline_seconds"] == 0.25
    assert adapter_kwargs["socket_timeout_seconds"] == 0.1
    service_kwargs = observed["service_kwargs"]
    assert service_kwargs["engine"] is direct_history_engine
    assert service_kwargs["adapter"].__class__ is adapter_module.GmailHistoryAdapter
    assert service_kwargs["participant_hash_key"] == b"p" * 32
    assert service_kwargs["max_pages_per_run"] == 19
    assert service_kwargs["receipt_processing_deadline_seconds"] == 8
    assert service_kwargs["receipt_processing_stale_after_seconds"] == 40
    assert observed["profile_request"] == {"userId": "me"}
    assert retry_values == [0, 0, 0]


async def test_failed_gmail_affinity_probe_disposes_and_registers_nothing(
    worker_database,
    runtime_database,
) -> None:
    from config import Settings
    from models.integration_health import IntegrationWorkerHeartbeat
    from workers.integration_worker import initialize_worker_runtime

    primary_engine, sessionmaker = worker_database
    url, _sync_engine = runtime_database
    direct_url = async_test_url(url).render_as_string(hide_password=False)
    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=direct_url,
        GMAIL_HISTORY_DATABASE_URL=direct_url,
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="x" * 32,
        GOOGLE_WORKSPACE_CLIENT_ID="probe-client-id",
        GOOGLE_WORKSPACE_CLIENT_SECRET="probe-client-secret",
    )
    calls: list[str] = []

    class _HistoryEngine:
        async def dispose(self):
            calls.append("dispose")

    def engine_factory(_config):
        calls.append("history_engine")
        return _HistoryEngine()

    async def failing_probe(**_kwargs):
        calls.append("probe")
        raise RuntimeError("gmail_history_session_affinity_required")

    def forbidden_factory(**_kwargs):
        calls.append("forbidden")
        raise AssertionError("provider/job construction must follow the probe")

    with pytest.raises(RuntimeError, match="^gmail_history_session_affinity_required$"):
        await initialize_worker_runtime(
            config=config,
            sessionmaker=sessionmaker,
            primary_engine=primary_engine,
            history_engine_factory=engine_factory,
            history_probe=failing_probe,
            provider_executor_factory=forbidden_factory,
            gmail_job_factory=forbidden_factory,
        )
    assert calls == ["history_engine", "probe", "dispose"]
    async with sessionmaker() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(IntegrationWorkerHeartbeat)
            )
            == 0
        )


async def test_disabled_gmail_skips_direct_database_validation_probe_and_provider_setup(
    worker_database,
) -> None:
    from config import Settings
    from workers.integration_worker import initialize_worker_runtime

    primary_engine, sessionmaker = worker_database
    config = Settings(
        JWT_SECRET="test-secret",
        GMAIL_TASK_INTAKE_ENABLED=False,
        GMAIL_HISTORY_DATABASE_URL="",
        GMAIL_PARTICIPANT_HASH_KEY="",
        INTEGRATION_PROVIDER_MAX_WORKERS=0,
        INTEGRATION_PROVIDER_DEADLINE_SECONDS=0,
        INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS=999,
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("disabled Gmail must not initialize provider resources")

    runtime = await initialize_worker_runtime(
        config=config,
        sessionmaker=sessionmaker,
        primary_engine=primary_engine,
        history_engine_factory=forbidden,
        history_probe=forbidden,
        provider_executor_factory=forbidden,
        gmail_job_factory=forbidden,
    )
    try:
        gmail_job = next(
            job for job in runtime.registry.jobs if job.name == "gmail_history"
        )
        assert gmail_job.enabled is False
        assert runtime.gmail_history_ready is False
    finally:
        await runtime.close()


async def test_gmail_job_reuses_one_executor_and_db_bound_token_across_runs(
    worker_database,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from workers.jobs.gmail_history import GmailHistoryJob

    _primary_engine, sessionmaker = worker_database
    account = GmailSyncAccount(
        workspace_email="brandon@example.test",
        committed_history_id="job-100",
        mode="shadow",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add_all(
            [
                Setting(
                    key="google_workspace_gmail_account_id",
                    value=str(account.id),
                ),
                Setting(
                    key="google_workspace_refresh_token",
                    value="job-database-refresh-token",
                ),
            ]
        )
        await session.commit()

    shared_executor = object()
    direct_history_engine = object()
    factory_calls: list[tuple[object, str, str]] = []
    sync_calls: list = []

    class _Service:
        async def sync_account(self, account_id):
            sync_calls.append(account_id)

    def service_factory(
        *, history_engine, provider_executor, refresh_token, workspace_email, **_kwargs
    ):
        assert history_engine is direct_history_engine
        factory_calls.append((provider_executor, refresh_token, workspace_email))
        return _Service()

    job = GmailHistoryJob(
        enabled=True,
        sessionmaker=sessionmaker,
        history_engine=direct_history_engine,
        provider_executor=shared_executor,
        service_factory=service_factory,
        whole_job_deadline_seconds=1,
        max_accounts_per_run=1,
    )
    await job.run()
    await job.run()

    assert factory_calls == [
        (shared_executor, "job-database-refresh-token", "brandon@example.test"),
        (shared_executor, "job-database-refresh-token", "brandon@example.test"),
    ]
    assert sync_calls == [account.id, account.id]


async def test_gmail_job_rejects_a_rotated_database_credential_generation(
    worker_database,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers.workspace import _WORKSPACE_GMAIL_BINDING_LOCK_KEY as route_lock_key
    from workers.jobs.gmail_history import (
        GmailHistoryJob,
        _WORKSPACE_GMAIL_BINDING_LOCK_KEY as worker_lock_key,
    )

    engine, sessionmaker = worker_database
    assert worker_lock_key == route_lock_key
    account = GmailSyncAccount(
        workspace_email="rotation@example.test",
        committed_history_id="job-rotation-100",
        mode="shadow",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add_all(
            [
                Setting(
                    key="google_workspace_gmail_account_id",
                    value=str(account.id),
                ),
                Setting(
                    key="google_workspace_refresh_token",
                    value="database-generation-one",
                ),
            ]
        )
        await session.commit()

    provider_started = asyncio.Event()
    credential_rotated = asyncio.Event()
    current_results: list[bool] = []

    class _Service:
        def __init__(self, credential_is_current):
            self._credential_is_current = credential_is_current

        async def sync_account(self, _account_id):
            provider_started.set()
            await credential_rotated.wait()
            async with sessionmaker() as session:
                await session.execute(
                    sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": route_lock_key},
                )
                current_results.append(await self._credential_is_current(session))
                await session.rollback()

    def service_factory(*, refresh_token, credential_is_current, **_kwargs):
        assert refresh_token == "database-generation-one"
        return _Service(credential_is_current)

    lock_statements: list[str] = []

    def capture_lock_statement(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if "pg_advisory_xact_lock" in normalized:
            lock_statements.append(normalized)

    sa.event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        capture_lock_statement,
    )
    job = GmailHistoryJob(
        enabled=True,
        sessionmaker=sessionmaker,
        history_engine=engine,
        provider_executor=object(),
        service_factory=service_factory,
        whole_job_deadline_seconds=1,
        max_accounts_per_run=1,
    )
    try:
        pending = asyncio.create_task(job.run())
        await asyncio.wait_for(provider_started.wait(), timeout=1)
        async with sessionmaker() as session:
            await session.execute(
                sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": route_lock_key},
            )
            token = await session.scalar(
                sa.select(Setting).where(
                    Setting.key == "google_workspace_refresh_token"
                )
            )
            token.value = "database-generation-two"
            await session.commit()
        credential_rotated.set()
        await asyncio.wait_for(pending, timeout=1)
    finally:
        credential_rotated.set()
        sa.event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            capture_lock_statement,
        )

    assert current_results == [False]
    assert len(lock_statements) >= 3
    async with sessionmaker() as session:
        stored_token = await session.scalar(
            sa.select(Setting.value).where(
                Setting.key == "google_workspace_refresh_token"
            )
        )
    assert stored_token == "database-generation-two"


async def test_default_gmail_composition_holds_binding_lock_through_oauth_failure_commit(
    worker_database,
    runtime_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import Settings
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from routers.workspace import _WORKSPACE_GMAIL_BINDING_LOCK_KEY
    import services.gmail_history_adapter as adapter_module
    import services.gmail_history_service as history_service_module
    from services.integration_health_service import BoundedProviderExecutor
    from sqlalchemy.pool import NullPool
    from workers.integration_worker import initialize_worker_runtime

    primary_engine, sessionmaker = worker_database
    url, _sync_engine = runtime_database
    direct_url = async_test_url(url).render_as_string(hide_password=False)
    account = GmailSyncAccount(
        workspace_email="atomic-rotation@example.test",
        committed_history_id=None,
        mode="shadow",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add_all(
            [
                Setting(
                    key="google_workspace_gmail_account_id",
                    value=str(account.id),
                ),
                Setting(
                    key="google_workspace_refresh_token",
                    value="atomic-database-generation-one",
                ),
            ]
        )
        await session.commit()
        account_id = account.id

    class _ProviderError(RuntimeError):
        def __init__(self):
            super().__init__("provider fixture error")
            self.resp = SimpleNamespace(status=401)

    class _Request:
        def execute(self, *, num_retries):
            assert num_retries == 0
            raise _ProviderError

    class _Users:
        def getProfile(self, **kwargs):
            assert kwargs == {"userId": "me"}
            return _Request()

    class _Gmail:
        def users(self):
            return _Users()

    monkeypatch.setattr(
        adapter_module,
        "build_gmail_service",
        lambda **_kwargs: _Gmail(),
    )

    generation_checked = asyncio.Event()
    allow_failure_commit = asyncio.Event()
    real_service_init = history_service_module.GmailHistoryService.__init__

    def install_generation_barrier(self, **kwargs):
        credential_is_current = kwargs["credential_is_current"]
        assert callable(credential_is_current)

        async def check_then_pause(session):
            is_current = await credential_is_current(session)
            assert is_current is True
            generation_checked.set()
            await allow_failure_commit.wait()
            return is_current

        kwargs["credential_is_current"] = check_then_pause
        real_service_init(self, **kwargs)

    monkeypatch.setattr(
        history_service_module.GmailHistoryService,
        "__init__",
        install_generation_barrier,
    )

    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=direct_url,
        GMAIL_HISTORY_DATABASE_URL=direct_url,
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="r" * 32,
        GOOGLE_WORKSPACE_CLIENT_ID="atomic-worker-client-id",
        GOOGLE_WORKSPACE_CLIENT_SECRET="atomic-worker-client-secret",
        INTEGRATION_PROVIDER_MAX_WORKERS=1,
    )
    direct_history_engine = create_async_engine(
        direct_url,
        poolclass=NullPool,
    )
    shared_executor = BoundedProviderExecutor(max_workers=1)

    async def successful_probe(*, history_engine, primary_engine):
        assert history_engine is direct_history_engine
        assert primary_engine is primary_engine_fixture
        return SimpleNamespace(backend_pid=62345)

    runtime = None
    primary_engine_fixture = primary_engine
    rotation_lock_attempted = asyncio.Event()
    rotation_lock_acquired = asyncio.Event()

    async def rotate_credential() -> None:
        async with sessionmaker() as session:
            rotation_lock_attempted.set()
            await session.execute(
                sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _WORKSPACE_GMAIL_BINDING_LOCK_KEY},
            )
            rotation_lock_acquired.set()
            token = await session.scalar(
                sa.select(Setting).where(
                    Setting.key == "google_workspace_refresh_token"
                )
            )
            stored_account = await session.get(GmailSyncAccount, account_id)
            token.value = "atomic-database-generation-two"
            stored_account.blocked_reason = None
            stored_account.last_error_category = None
            stored_account.last_error_message = None
            await session.commit()

    job_task = None
    rotation_task = None
    try:
        runtime = await initialize_worker_runtime(
            config=config,
            sessionmaker=sessionmaker,
            primary_engine=primary_engine,
            history_engine_factory=lambda _config: direct_history_engine,
            history_probe=successful_probe,
            provider_executor_factory=lambda **_kwargs: shared_executor,
        )
        gmail_job = next(
            job for job in runtime.registry.jobs if job.name == "gmail_history"
        )
        job_task = asyncio.create_task(gmail_job.runner())
        await asyncio.wait_for(generation_checked.wait(), timeout=1)

        rotation_task = asyncio.create_task(rotate_credential())
        await asyncio.wait_for(rotation_lock_attempted.wait(), timeout=1)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                asyncio.shield(rotation_lock_acquired.wait()),
                timeout=0.05,
            )

        allow_failure_commit.set()
        await asyncio.wait_for(job_task, timeout=1)
        await asyncio.wait_for(rotation_task, timeout=1)

        async with sessionmaker() as session:
            stored_token = await session.scalar(
                sa.select(Setting.value).where(
                    Setting.key == "google_workspace_refresh_token"
                )
            )
            stored_account = await session.get(GmailSyncAccount, account_id)
        assert stored_token == "atomic-database-generation-two"
        assert stored_account.blocked_reason is None
        assert stored_account.last_error_category is None
        assert stored_account.last_error_message is None
    finally:
        allow_failure_commit.set()
        for task in (job_task, rotation_task):
            if task is not None and not task.done():
                task.cancel()
        if job_task is not None or rotation_task is not None:
            await asyncio.gather(
                *(task for task in (job_task, rotation_task) if task is not None),
                return_exceptions=True,
            )
        if runtime is not None:
            await runtime.close()
        else:
            await shared_executor.wait_for_tracked_calls()
            shared_executor.shutdown()
            await direct_history_engine.dispose()


@pytest.mark.parametrize(
    "stall_point",
    ("credential_verifier", "durable_alert_sink", "final_lock_release"),
)
async def test_default_gmail_job_deadline_survives_service_cleanup_boundaries(
    worker_database,
    runtime_database,
    monkeypatch: pytest.MonkeyPatch,
    stall_point: str,
) -> None:
    from config import Settings
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    import services.gmail_history_adapter as adapter_module
    import services.gmail_history_service as history_service_module
    from services.integration_health_service import BoundedProviderExecutor
    from sqlalchemy.pool import NullPool
    import workers.integration_worker as worker_module
    from workers.integration_worker import initialize_worker_runtime
    from workers.jobs.gmail_history import GmailHistoryJob

    primary_engine, sessionmaker = worker_database
    url, _sync_engine = runtime_database
    direct_url = async_test_url(url).render_as_string(hide_password=False)
    account = GmailSyncAccount(
        workspace_email="deadline-boundary@example.test",
        committed_history_id=None,
        mode="shadow",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add_all(
            [
                Setting(
                    key="google_workspace_gmail_account_id",
                    value=str(account.id),
                ),
                Setting(
                    key="google_workspace_refresh_token",
                    value="deadline-boundary-database-generation",
                ),
            ]
        )
        await session.commit()

    entered_boundary = asyncio.Event()

    class _ProviderError(RuntimeError):
        def __init__(self):
            super().__init__("provider fixture error")
            self.resp = SimpleNamespace(status=401)

    class _Request:
        def execute(self, *, num_retries):
            assert num_retries == 0
            if stall_point == "credential_verifier":
                raise _ProviderError
            return {
                "emailAddress": (
                    "mismatch@example.test"
                    if stall_point == "durable_alert_sink"
                    else account.workspace_email
                ),
                "historyId": "500",
            }

    class _Users:
        def getProfile(self, **kwargs):
            assert kwargs == {"userId": "me"}
            return _Request()

    class _Gmail:
        def users(self):
            return _Users()

    monkeypatch.setattr(
        adapter_module,
        "build_gmail_service",
        lambda **_kwargs: _Gmail(),
    )

    if stall_point == "credential_verifier":

        async def stalled_verifier(
            self,
            session,
            *,
            account_id,
            expected_generation,
        ) -> bool:
            del self, session, account_id, expected_generation
            entered_boundary.set()
            await asyncio.Event().wait()
            return True

        monkeypatch.setattr(
            GmailHistoryJob,
            "_credential_is_current",
            stalled_verifier,
        )
    elif stall_point == "durable_alert_sink":

        async def stalled_enqueue_notification(*_args, **_kwargs):
            entered_boundary.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(
            worker_module,
            "enqueue_notification",
            stalled_enqueue_notification,
        )
    else:

        async def stalled_release(*_args, **_kwargs):
            entered_boundary.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(
            history_service_module,
            "release_session_advisory_lock",
            stalled_release,
        )

    config = Settings(
        JWT_SECRET="test-secret",
        DATABASE_URL=direct_url,
        GMAIL_HISTORY_DATABASE_URL=direct_url,
        GMAIL_TASK_INTAKE_ENABLED=True,
        GMAIL_PARTICIPANT_HASH_KEY="d" * 32,
        GOOGLE_WORKSPACE_CLIENT_ID="deadline-worker-client-id",
        GOOGLE_WORKSPACE_CLIENT_SECRET="deadline-worker-client-secret",
        INTEGRATION_PROVIDER_MAX_WORKERS=1,
        GMAIL_HISTORY_JOB_DEADLINE_SECONDS=0.25,
    )
    direct_history_engine = create_async_engine(
        direct_url,
        poolclass=NullPool,
    )
    shared_executor = BoundedProviderExecutor(max_workers=1)

    async def successful_probe(*, history_engine, primary_engine):
        assert history_engine is direct_history_engine
        assert primary_engine is primary_engine_fixture
        return SimpleNamespace(backend_pid=63456)

    runtime = None
    job_task = None
    primary_engine_fixture = primary_engine
    try:
        runtime = await initialize_worker_runtime(
            config=config,
            sessionmaker=sessionmaker,
            primary_engine=primary_engine,
            history_engine_factory=lambda _config: direct_history_engine,
            history_probe=successful_probe,
            provider_executor_factory=lambda **_kwargs: shared_executor,
        )
        gmail_job = next(
            job for job in runtime.registry.jobs if job.name == "gmail_history"
        )
        job_task = asyncio.create_task(gmail_job.runner())
        await asyncio.wait_for(entered_boundary.wait(), timeout=1)
        with pytest.raises(RuntimeError, match="^gmail_history_job_timeout$"):
            await asyncio.wait_for(job_task, timeout=2)
    finally:
        if job_task is not None and not job_task.done():
            job_task.cancel()
            await asyncio.gather(job_task, return_exceptions=True)
        if runtime is not None:
            await runtime.close()
        else:
            await shared_executor.wait_for_tracked_calls()
            shared_executor.shutdown()
            await direct_history_engine.dispose()


async def test_gmail_job_missing_binding_never_guesses_account_or_calls_provider(
    worker_database,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from workers.jobs.gmail_history import GmailHistoryJob

    engine, sessionmaker = worker_database
    async with sessionmaker() as session:
        session.add(
            GmailSyncAccount(
                workspace_email="only-row@example.test",
                committed_history_id="job-200",
                mode="shadow",
            )
        )
        await session.commit()

    calls = 0

    def forbidden_factory(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("an unbound row must never be guessed")

    job = GmailHistoryJob(
        enabled=True,
        sessionmaker=sessionmaker,
        history_engine=engine,
        provider_executor=object(),
        service_factory=forbidden_factory,
        whole_job_deadline_seconds=1,
        max_accounts_per_run=1,
    )
    with pytest.raises(RuntimeError, match="^gmail_account_binding_missing$"):
        await job.run()
    assert calls == 0


async def test_gmail_job_has_whole_job_deadline_and_sanitized_progress_heartbeat(
    worker_database,
) -> None:
    from models.gmail_task_intake import GmailSyncAccount
    from models.setting import Setting
    from workers.jobs.gmail_history import GmailHistoryJob

    engine, sessionmaker = worker_database
    account = GmailSyncAccount(
        workspace_email="brandon@example.test",
        committed_history_id="job-300",
        mode="shadow",
    )
    async with sessionmaker() as session:
        session.add(account)
        await session.flush()
        session.add_all(
            [
                Setting(
                    key="google_workspace_gmail_account_id",
                    value=str(account.id),
                ),
                Setting(
                    key="google_workspace_refresh_token",
                    value="job-timeout-token-canary",
                ),
            ]
        )
        await session.commit()

    entered = asyncio.Event()
    release = asyncio.Event()
    heartbeats: list[str] = []

    class _StalledService:
        async def sync_account(self, _account_id):
            entered.set()
            await release.wait()

    async def heartbeat(state: str):
        heartbeats.append(state)

    job = GmailHistoryJob(
        enabled=True,
        sessionmaker=sessionmaker,
        history_engine=engine,
        provider_executor=object(),
        service_factory=lambda **_kwargs: _StalledService(),
        progress_heartbeat=heartbeat,
        whole_job_deadline_seconds=0.05,
        max_accounts_per_run=1,
    )
    try:
        pending = asyncio.create_task(job.run())
        await asyncio.wait_for(entered.wait(), timeout=1)
        with pytest.raises(RuntimeError, match="^gmail_history_job_timeout$"):
            await pending
    finally:
        release.set()

    assert heartbeats == ["started", "timed_out"]


def test_health_is_exact_liveness_and_touches_no_dependency() -> None:
    from workers.health_app import create_health_app

    calls = 0

    async def exploding_readiness():
        nonlocal calls
        calls += 1
        raise RuntimeError("database oauth registry provider secret@example.test")

    client = TestClient(create_health_app(exploding_readiness))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "integration-worker",
    }
    assert calls == 0

    failed_ready = client.get("/ready")
    assert failed_ready.status_code == 503
    assert failed_ready.json() == {
        "status": "not_ready",
        "service": "integration-worker",
        "failing_components": ["database"],
    }
    assert "secret@example.test" not in failed_ready.text


async def test_scheduler_validates_registry_then_owns_boot_and_heartbeat_writes(
    worker_database,
) -> None:
    from models.integration_health import IntegrationWorkerHeartbeat
    from workers.integration_worker import (
        JobDefinition,
        JobRegistry,
        run_scheduler_cycle,
    )

    _engine, sessionmaker = worker_database
    observed_current_job: list[str | None] = []

    async def inspect_committed_heartbeat() -> None:
        async with sessionmaker() as session:
            heartbeat = await session.get(
                IntegrationWorkerHeartbeat,
                "worker-scheduler",
            )
            observed_current_job.append(heartbeat.current_job)

    registry = JobRegistry(
        (
            JobDefinition(
                "notification_delivery",
                60,
                True,
                inspect_committed_heartbeat,
            ),
        )
    )
    assert registry.initialized is False
    cycle_at = datetime(2026, 8, 20, 13, 0, tzinfo=UTC)
    await run_scheduler_cycle(
        sessionmaker=sessionmaker,
        worker_id="worker-scheduler",
        registry=registry,
        cycle_at=cycle_at,
    )
    assert registry.initialized is True
    assert observed_current_job == ["notification_delivery"]
    async with sessionmaker() as session:
        heartbeat = await session.get(
            IntegrationWorkerHeartbeat,
            "worker-scheduler",
        )
        assert heartbeat.booted_at == cycle_at
        assert heartbeat.heartbeat_at == cycle_at
        assert heartbeat.current_job is None
        assert heartbeat.last_completed_job == "notification_delivery"

    later_cycle = cycle_at + timedelta(seconds=30)
    await run_scheduler_cycle(
        sessionmaker=sessionmaker,
        worker_id="worker-scheduler",
        registry=registry,
        cycle_at=later_cycle,
    )
    assert observed_current_job == ["notification_delivery"]
    async with sessionmaker() as session:
        heartbeat = await session.get(
            IntegrationWorkerHeartbeat,
            "worker-scheduler",
        )
        assert heartbeat.booted_at == cycle_at
        assert heartbeat.heartbeat_at == later_cycle
        assert heartbeat.last_completed_job == "notification_delivery"


async def test_scheduler_refreshes_heartbeat_during_long_job_and_uses_actual_completion_time(
    worker_database,
) -> None:
    from models.integration_health import IntegrationWorkerHeartbeat
    from workers.integration_worker import (
        JobDefinition,
        JobRegistry,
        run_scheduler_cycle,
    )

    _engine, sessionmaker = worker_database
    started = asyncio.Event()
    release_job = asyncio.Event()
    periodic_write_finished = asyncio.Event()
    fake_now = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
    cycle_at = fake_now
    sleep_calls = 0

    async def long_job() -> None:
        started.set()
        await release_job.wait()

    def clock() -> datetime:
        return fake_now

    async def barrier_sleep(_seconds: float) -> None:
        nonlocal fake_now, sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            fake_now = cycle_at + timedelta(seconds=121)
            return
        periodic_write_finished.set()
        await asyncio.Event().wait()

    registry = JobRegistry(
        (JobDefinition("notification_delivery", 60, True, long_job),)
    )
    cycle = asyncio.create_task(
        run_scheduler_cycle(
            sessionmaker=sessionmaker,
            worker_id="worker-long-job",
            registry=registry,
            cycle_at=cycle_at,
            clock=clock,
            heartbeat_interval_seconds=30,
            heartbeat_sleep=barrier_sleep,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.wait_for(periodic_write_finished.wait(), timeout=1)

    async with sessionmaker() as session:
        heartbeat = await session.get(
            IntegrationWorkerHeartbeat,
            "worker-long-job",
        )
        assert heartbeat.booted_at == cycle_at
        assert heartbeat.heartbeat_at == fake_now
        assert heartbeat.current_job == "notification_delivery"
        assert fake_now - heartbeat.heartbeat_at < timedelta(seconds=120)

    fake_now = cycle_at + timedelta(seconds=125)
    release_job.set()
    await asyncio.wait_for(cycle, timeout=1)

    async with sessionmaker() as session:
        heartbeat = await session.get(
            IntegrationWorkerHeartbeat,
            "worker-long-job",
        )
        assert heartbeat.heartbeat_at == fake_now
        assert heartbeat.current_job is None
        assert heartbeat.last_completed_job == "notification_delivery"


async def test_scheduler_rejects_an_explicit_zero_heartbeat_interval(
    worker_database,
) -> None:
    from workers.integration_worker import (
        JobDefinition,
        JobRegistry,
        run_scheduler_cycle,
    )

    _engine, sessionmaker = worker_database
    registry = JobRegistry(
        (
            JobDefinition(
                "notification_delivery",
                60,
                True,
                lambda: asyncio.sleep(0),
            ),
        )
    )
    with pytest.raises(ValueError, match="heartbeat interval"):
        await run_scheduler_cycle(
            sessionmaker=sessionmaker,
            worker_id="worker-zero-heartbeat",
            registry=registry,
            cycle_at=datetime(2026, 8, 20, 15, 0, tzinfo=UTC),
            heartbeat_interval_seconds=0,
        )


async def test_scheduler_honors_each_jobs_independent_interval(
    worker_database,
) -> None:
    from workers.integration_worker import (
        JobDefinition,
        JobRegistry,
        run_scheduler_cycle,
    )

    _engine, sessionmaker = worker_database
    calls = {"fast": 0, "slow": 0}

    async def run_fast() -> None:
        calls["fast"] += 1

    async def run_slow() -> None:
        calls["slow"] += 1

    registry = JobRegistry(
        (
            JobDefinition("fast", 60, True, run_fast),
            JobDefinition("slow", 120, True, run_slow),
        )
    )
    started_at = datetime(2026, 8, 20, 13, 30, tzinfo=UTC)
    for offset in (0, 30, 60, 90, 120):
        await run_scheduler_cycle(
            sessionmaker=sessionmaker,
            worker_id="worker-intervals",
            registry=registry,
            cycle_at=started_at + timedelta(seconds=offset),
        )
    assert calls == {"fast": 3, "slow": 2}


async def test_scheduler_validation_failure_writes_no_boot_row(
    worker_database,
) -> None:
    from models.integration_health import IntegrationWorkerHeartbeat
    from workers.integration_worker import (
        JobDefinition,
        JobRegistry,
        run_scheduler_cycle,
    )

    _engine, sessionmaker = worker_database
    invalid_registry = JobRegistry(
        (
            JobDefinition(
                "secret_token_job",
                60,
                True,
                lambda: asyncio.sleep(0),
            ),
        )
    )
    with pytest.raises(ValueError, match="secret"):
        await run_scheduler_cycle(
            sessionmaker=sessionmaker,
            worker_id="worker-invalid",
            registry=invalid_registry,
            cycle_at=datetime(2026, 8, 20, 13, 5, tzinfo=UTC),
        )
    async with sessionmaker() as session:
        assert (
            await session.get(
                IntegrationWorkerHeartbeat,
                "worker-invalid",
            )
            is None
        )


async def test_ready_is_read_only_and_requires_current_head_fresh_scheduler_heartbeat_and_registry(
    worker_database,
) -> None:
    from services.integration_health_service import record_scheduler_boot
    from workers.health_app import WorkerReadinessProbe, create_health_app
    from workers.integration_worker import JobDefinition, JobRegistry

    engine, sessionmaker = worker_database
    registry = JobRegistry(
        (
            JobDefinition(
                "notification_delivery",
                60,
                True,
                lambda: asyncio.sleep(0),
            ),
        )
    )
    registry.initialize()
    checked_at = datetime.now(UTC)
    async with sessionmaker() as session:
        await record_scheduler_boot(
            session,
            worker_id="worker-ready",
            booted_at=checked_at,
        )
        await session.commit()

    statements: list[str] = []

    def capture_statement(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        statements.append(" ".join(statement.upper().split()))

    sa.event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        capture_statement,
    )
    try:
        probe = WorkerReadinessProbe(
            sessionmaker=sessionmaker,
            worker_id="worker-ready",
            expected_migration=REVISION,
            registry=registry,
            heartbeat_max_age=timedelta(minutes=2),
        )
        async with AsyncClient(
            transport=ASGITransport(app=create_health_app(probe)),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/ready")
    finally:
        sa.event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            capture_statement,
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "integration-worker",
        "database": "ok",
        "migration": "ok",
        "heartbeat": "ok",
        "job_registry": "ok",
    }
    assert statements
    assert all(
        statement.startswith("SELECT")
        for statement in statements
        if not statement.startswith("SHOW")
    )
    assert not any(
        token in statement
        for statement in statements
        for token in ("INSERT ", "UPDATE ", "DELETE ", "MERGE ")
    )


async def test_ready_failure_is_bounded_component_names_only(
    worker_database,
) -> None:
    from services.integration_health_service import record_scheduler_boot
    from workers.health_app import WorkerReadinessProbe, create_health_app
    from workers.integration_worker import JobDefinition, JobRegistry

    _engine, sessionmaker = worker_database
    stale = datetime.now(UTC) - timedelta(hours=1)
    async with sessionmaker() as session:
        await record_scheduler_boot(
            session,
            worker_id="worker-stale",
            booted_at=stale,
        )
        await session.commit()

    registry = JobRegistry(
        (
            JobDefinition(
                "notification_delivery",
                60,
                True,
                lambda: asyncio.sleep(0),
            ),
        )
    )
    probe = WorkerReadinessProbe(
        sessionmaker=sessionmaker,
        worker_id="worker-stale",
        expected_migration="wrong-secret-migration",
        registry=registry,
        heartbeat_max_age=timedelta(minutes=2),
    )
    async with AsyncClient(
        transport=ASGITransport(app=create_health_app(probe)),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "service": "integration-worker",
        "failing_components": [
            "heartbeat",
            "job_registry",
            "migration",
        ],
    }
    serialized = response.text
    for forbidden in (
        "wrong-secret-migration",
        "worker-stale",
        "oauth",
        "provider",
        "account",
    ):
        assert forbidden not in serialized


async def test_ready_requires_an_existing_scheduler_owned_heartbeat(
    worker_database,
) -> None:
    from workers.health_app import WorkerReadinessProbe, create_health_app
    from workers.integration_worker import JobDefinition, JobRegistry

    _engine, sessionmaker = worker_database
    registry = JobRegistry(
        (
            JobDefinition(
                "notification_delivery",
                60,
                True,
                lambda: asyncio.sleep(0),
            ),
        )
    )
    registry.initialize()
    probe = WorkerReadinessProbe(
        sessionmaker=sessionmaker,
        worker_id="worker-missing",
        expected_migration=REVISION,
        registry=registry,
        heartbeat_max_age=timedelta(minutes=2),
    )
    async with AsyncClient(
        transport=ASGITransport(app=create_health_app(probe)),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "service": "integration-worker",
        "failing_components": ["heartbeat"],
    }


async def test_stalled_sync_provider_does_not_delay_liveness_probe() -> None:
    from services.integration_health_service import (
        BoundedProviderExecutor,
        ProviderCallTimedOut,
    )
    from workers.health_app import create_health_app

    release = __import__("threading").Event()
    started = __import__("threading").Event()
    executor = BoundedProviderExecutor(max_workers=1)

    def stalled() -> None:
        started.set()
        release.wait(timeout=5)

    async def unavailable_ready():
        return ("database",)

    client = TestClient(create_health_app(unavailable_ready))
    try:
        provider = asyncio.create_task(
            executor.run(
                key="gmail:stalled",
                function=stalled,
                deadline_seconds=0.05,
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        started_at = time.monotonic()
        response = await asyncio.to_thread(client.get, "/health")
        elapsed = time.monotonic() - started_at
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "integration-worker",
        }
        assert elapsed < 0.5
        with pytest.raises(ProviderCallTimedOut):
            await provider
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()


@pytest.mark.parametrize(
    ("winner", "message"),
    (
        ("scheduler", "scheduler returned normally"),
        ("server", "server returned normally"),
    ),
)
async def test_first_completed_normal_return_cancels_and_awaits_peer(
    winner: str,
    message: str,
) -> None:
    from workers.integration_worker import supervise_worker_peers

    class Server:
        should_exit = False

    server = Server()
    cancelled = {"scheduler": False, "server": False}

    async def normal() -> None:
        await asyncio.sleep(0)

    async def blocked(name: str) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled[name] = True

    scheduler_peer = normal() if winner == "scheduler" else blocked("scheduler")
    server_peer = normal() if winner == "server" else blocked("server")
    before = set(asyncio.all_tasks())
    with pytest.raises(RuntimeError, match=message):
        await supervise_worker_peers(
            server=server,
            scheduler_peer=scheduler_peer,
            server_peer=server_peer,
        )
    await asyncio.sleep(0)
    assert server.should_exit is True
    loser = "server" if winner == "scheduler" else "scheduler"
    assert cancelled[loser] is True
    assert set(asyncio.all_tasks()) - before == set()


@pytest.mark.parametrize("winner", ("scheduler", "server"))
async def test_first_completed_error_is_reraised_after_peer_cleanup(
    winner: str,
) -> None:
    from workers.integration_worker import supervise_worker_peers

    class Server:
        should_exit = False

    server = Server()
    peer_finalized = asyncio.Event()

    async def exploding() -> None:
        await asyncio.sleep(0)
        raise ValueError(f"{winner} failed")

    async def blocked() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            peer_finalized.set()

    scheduler_peer = exploding() if winner == "scheduler" else blocked()
    server_peer = exploding() if winner == "server" else blocked()
    with pytest.raises(ValueError, match=f"{winner} failed"):
        await supervise_worker_peers(
            server=server,
            scheduler_peer=scheduler_peer,
            server_peer=server_peer,
        )
    assert server.should_exit is True
    assert peer_finalized.is_set()


@pytest.mark.parametrize("error_peer", ("scheduler", "server"))
async def test_first_completed_prefers_peer_error_when_both_peers_are_done(
    error_peer: str,
) -> None:
    from workers.integration_worker import supervise_worker_peers

    class Server:
        should_exit = False

    async def normal() -> None:
        return None

    async def exploding() -> None:
        raise ValueError(f"{error_peer} simultaneous failure")

    server = Server()
    scheduler_peer = exploding() if error_peer == "scheduler" else normal()
    server_peer = exploding() if error_peer == "server" else normal()
    with pytest.raises(ValueError, match=f"{error_peer} simultaneous failure"):
        await supervise_worker_peers(
            server=server,
            scheduler_peer=scheduler_peer,
            server_peer=server_peer,
        )
    assert server.should_exit is True


async def test_first_completed_uses_deterministic_scheduler_error_precedence_when_both_fail() -> (
    None
):
    from workers.integration_worker import supervise_worker_peers

    class Server:
        should_exit = False

    async def fail_scheduler() -> None:
        raise ValueError("scheduler simultaneous failure")

    async def fail_server() -> None:
        raise LookupError("server simultaneous failure")

    server = Server()
    with pytest.raises(ValueError, match="scheduler simultaneous failure"):
        await supervise_worker_peers(
            server=server,
            scheduler_peer=fail_scheduler(),
            server_peer=fail_server(),
        )
    assert server.should_exit is True
