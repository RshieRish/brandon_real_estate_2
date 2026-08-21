from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "82b5e3d7f0a1"
UTC = timezone.utc


@pytest.fixture(scope="module")
def runtime_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def worker_database(runtime_database):
    url, sync_engine = runtime_database
    with sync_engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM integration_worker_heartbeats"))
    engine = create_async_engine(async_test_url(url), pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessionmaker
    finally:
        await engine.dispose()


def test_worker_feature_flags_default_off_and_web_app_starts_no_integration_loop() -> None:
    from config import Settings

    settings = Settings(JWT_SECRET="test-secret")
    assert settings.GMAIL_TASK_INTAKE_ENABLED is False
    assert settings.SYDNEY_TASK_QUESTIONS_ENABLED is False
    assert settings.INSTAGRAM_INTEGRATION_ENABLED is False

    main_source = (Path(__file__).parents[1] / "main.py").read_text(
        encoding="utf-8"
    )
    assert "workers.integration_worker" not in main_source
    assert "GMAIL_TASK_INTAKE_ENABLED" not in main_source
    assert "SYDNEY_TASK_QUESTIONS_ENABLED" not in main_source
    assert "INSTAGRAM_INTEGRATION_ENABLED" not in main_source


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
        JobRegistry(
            (
                JobDefinition("gmail_token", 60, True, no_op),
            )
        ).initialize()
    with pytest.raises(ValueError, match="interval"):
        JobRegistry(
            (
                JobDefinition("invalid_interval", 0, True, no_op),
            )
        ).initialize()


def test_health_is_exact_liveness_and_touches_no_dependency() -> None:
    from workers.health_app import create_health_app

    calls = 0

    async def exploding_readiness():
        nonlocal calls
        calls += 1
        raise RuntimeError(
            "database oauth registry provider secret@example.test"
        )

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
        assert await session.get(
            IntegrationWorkerHeartbeat,
            "worker-invalid",
        ) is None


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
    (("scheduler", "scheduler returned normally"), ("server", "server returned normally")),
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


async def test_first_completed_uses_deterministic_scheduler_error_precedence_when_both_fail() -> None:
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
