from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.gmail_task_postgres import async_test_url, migrated_test_database


REVISION = "82b5e3d7f0a1"
UTC = timezone.utc


@pytest.fixture(scope="module")
def runtime_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def notification_database(runtime_database):
    url, sync_engine = runtime_database
    with sync_engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM notification_jobs"))
    engine = create_async_engine(async_test_url(url), pool_pre_ping=True)
    try:
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _seed_due_jobs(sessionmaker, count: int) -> list[int]:
    from services.notification_service import enqueue_notification

    identifiers: list[int] = []
    async with sessionmaker() as session:
        for index in range(count):
            job = await enqueue_notification(
                session,
                event_type="integration_alert",
                payload={"sequence": index},
            )
            identifiers.append(job.id)
        await session.commit()
    return identifiers


async def test_two_sessions_claim_disjoint_due_rows_with_skip_locked(
    notification_database,
) -> None:
    from services.notification_service import claim_due_notification_jobs

    engine, sessionmaker = notification_database
    expected_ids = set(await _seed_due_jobs(sessionmaker, 4))
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
    first = sessionmaker()
    second = sessionmaker()
    now = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
    try:
        first_claim = await claim_due_notification_jobs(
            first,
            lease_owner="worker-a",
            limit=2,
            now=now,
            lease_duration=timedelta(minutes=2),
        )
        second_claim = await claim_due_notification_jobs(
            second,
            lease_owner="worker-b",
            limit=2,
            now=now,
            lease_duration=timedelta(minutes=2),
        )
        first_ids = {job.id for job in first_claim}
        second_ids = {job.id for job in second_claim}
        assert len(first_ids) == 2
        assert len(second_ids) == 2
        assert first_ids.isdisjoint(second_ids)
        assert first_ids | second_ids == expected_ids
        assert all(job.status == "sending" for job in first_claim + second_claim)
        assert all(
            job.lease_expires_at == now + timedelta(minutes=2)
            for job in first_claim + second_claim
        )
        await first.commit()
        await second.commit()
    finally:
        sa.event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            capture_statement,
        )
        await first.close()
        await second.close()

    assert any("FOR UPDATE SKIP LOCKED" in statement for statement in statements)


async def test_active_leases_are_excluded_and_expired_leases_are_recovered(
    notification_database,
) -> None:
    from services.notification_service import claim_due_notification_jobs

    _engine, sessionmaker = notification_database
    [job_id] = await _seed_due_jobs(sessionmaker, 1)
    now = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)

    async with sessionmaker() as first:
        [claimed] = await claim_due_notification_jobs(
            first,
            lease_owner="worker-a",
            limit=1,
            now=now,
            lease_duration=timedelta(minutes=5),
        )
        assert claimed.id == job_id
        await first.commit()

    async with sessionmaker() as second:
        assert await claim_due_notification_jobs(
            second,
            lease_owner="worker-b",
            limit=1,
            now=now + timedelta(minutes=1),
            lease_duration=timedelta(minutes=5),
        ) == []
        await second.rollback()

    async with sessionmaker() as third:
        [recovered] = await claim_due_notification_jobs(
            third,
            lease_owner="worker-b",
            limit=1,
            now=now + timedelta(minutes=6),
            lease_duration=timedelta(minutes=5),
        )
        assert recovered.id == job_id
        assert recovered.status == "sending"
        assert recovered.lease_owner == "worker-b"
        assert recovered.lease_expires_at == now + timedelta(minutes=11)
        await third.commit()


async def test_claim_order_is_deterministic_and_limit_is_bounded(
    notification_database,
) -> None:
    from services.notification_service import claim_due_notification_jobs

    _engine, sessionmaker = notification_database
    identifiers = await _seed_due_jobs(sessionmaker, 3)
    now = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)
    async with sessionmaker() as session:
        claims = await claim_due_notification_jobs(
            session,
            lease_owner="worker-order",
            limit=2,
            now=now,
            lease_duration=timedelta(minutes=1),
        )
        assert [job.id for job in claims] == identifiers[:2]
        await session.commit()

    async with sessionmaker() as session:
        with pytest.raises(ValueError, match="limit"):
            await claim_due_notification_jobs(
                session,
                lease_owner="worker-order",
                limit=0,
                now=now,
                lease_duration=timedelta(minutes=1),
            )
        with pytest.raises(ValueError, match="limit"):
            await claim_due_notification_jobs(
                session,
                lease_owner="worker-order",
                limit=101,
                now=now,
                lease_duration=timedelta(minutes=1),
            )
        with pytest.raises(ValueError, match="lease_owner"):
            await claim_due_notification_jobs(
                session,
                lease_owner="",
                limit=1,
                now=now,
                lease_duration=timedelta(minutes=1),
            )
        with pytest.raises(ValueError, match="lease_owner"):
            await claim_due_notification_jobs(
                session,
                lease_owner="x" * 129,
                limit=1,
                now=now,
                lease_duration=timedelta(minutes=1),
            )
        with pytest.raises(ValueError, match="lease_duration"):
            await claim_due_notification_jobs(
                session,
                lease_owner="worker-order",
                limit=1,
                now=now,
                lease_duration=timedelta(0),
            )


async def test_claims_exclude_future_due_delivered_and_active_lease_rows(
    notification_database,
) -> None:
    from services.notification_service import claim_due_notification_jobs

    _engine, sessionmaker = notification_database
    now = datetime(2026, 8, 20, 16, 30, tzinfo=UTC)
    async with sessionmaker() as session:
        session.add_all(
            [
                __import__(
                    "models.notification_job",
                    fromlist=["NotificationJob"],
                ).NotificationJob(
                    event_type="future-pending",
                    status="pending",
                    recipient="admin@example.test",
                    subject="Future",
                    payload_json="{}",
                    next_attempt_at=now + timedelta(minutes=1),
                ),
                __import__(
                    "models.notification_job",
                    fromlist=["NotificationJob"],
                ).NotificationJob(
                    event_type="delivered",
                    status="delivered",
                    recipient="admin@example.test",
                    subject="Delivered",
                    payload_json="{}",
                    delivered_at=now,
                ),
                __import__(
                    "models.notification_job",
                    fromlist=["NotificationJob"],
                ).NotificationJob(
                    event_type="active-lease",
                    status="sending",
                    recipient="admin@example.test",
                    subject="Sending",
                    payload_json="{}",
                    lease_owner="worker-active",
                    lease_expires_at=now + timedelta(minutes=1),
                ),
            ]
        )
        await session.commit()

    async with sessionmaker() as session:
        assert await claim_due_notification_jobs(
            session,
            lease_owner="worker-new",
            limit=10,
            now=now,
            lease_duration=timedelta(minutes=1),
        ) == []


async def test_enqueue_requires_paired_bounded_provider_dedupe_identity(
    notification_database,
) -> None:
    from services.notification_service import enqueue_notification

    _engine, sessionmaker = notification_database
    async with sessionmaker() as session:
        for provider_key, dedupe_key in (
            ("gmail_task_intake", None),
            (None, "dedupe"),
        ):
            with pytest.raises(ValueError, match="both"):
                await enqueue_notification(
                    session,
                    event_type="integration_alert",
                    payload={},
                    provider_key=provider_key,
                    dedupe_key=dedupe_key,
                )
        with pytest.raises(ValueError, match="provider_key"):
            await enqueue_notification(
                session,
                event_type="integration_alert",
                payload={},
                provider_key="x" * 101,
                dedupe_key="bounded",
            )
        with pytest.raises(ValueError, match="dedupe_key"):
            await enqueue_notification(
                session,
                event_type="integration_alert",
                payload={},
                provider_key="gmail_task_intake",
                dedupe_key="x" * 256,
            )


async def test_deterministic_provider_dedupe_converges_under_a_real_race(
    notification_database,
) -> None:
    from services.notification_service import enqueue_notification

    _engine, sessionmaker = notification_database
    barrier = asyncio.Barrier(2)

    async def enqueue_from_independent_session(sequence: int) -> int:
        async with sessionmaker() as session:
            await barrier.wait()
            job = await enqueue_notification(
                session,
                event_type="integration_alert",
                payload={"sequence": sequence},
                provider_key="gmail_task_intake",
                dedupe_key="integration-health:gmail_task_intake:epoch:3:opened",
            )
            await session.commit()
            return job.id

    first_id, second_id = await asyncio.gather(
        enqueue_from_independent_session(1),
        enqueue_from_independent_session(2),
    )
    assert first_id == second_id

    async with sessionmaker() as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT id, provider_key, dedupe_key FROM notification_jobs "
                    "WHERE provider_key = 'gmail_task_intake'"
                )
            )
        ).all()
        assert rows == [
            (
                first_id,
                "gmail_task_intake",
                "integration-health:gmail_task_intake:epoch:3:opened",
            )
        ]


async def test_claim_completion_requires_matching_lease_owner(
    notification_database,
) -> None:
    from services.notification_service import (
        claim_due_notification_jobs,
        complete_notification_claim,
    )

    _engine, sessionmaker = notification_database
    [job_id] = await _seed_due_jobs(sessionmaker, 1)
    now = datetime(2026, 8, 20, 17, 0, tzinfo=UTC)
    async with sessionmaker() as session:
        [job] = await claim_due_notification_jobs(
            session,
            lease_owner="worker-owner",
            limit=1,
            now=now,
            lease_duration=timedelta(minutes=2),
        )
        await session.commit()

    async with sessionmaker() as session:
        assert not await complete_notification_claim(
            session,
            job_id=job_id,
            lease_owner="worker-other",
            delivered_at=now + timedelta(seconds=5),
        )
        await session.commit()

    async with sessionmaker() as session:
        assert await complete_notification_claim(
            session,
            job_id=job_id,
            lease_owner="worker-owner",
            delivered_at=now + timedelta(seconds=5),
        )
        await session.commit()
        persisted = await session.get(type(job), job_id)
        assert persisted.status == "delivered"
        assert persisted.lease_owner is None
        assert persisted.lease_expires_at is None


async def test_actual_processing_entrypoint_claims_before_one_provider_send(
    notification_database,
) -> None:
    from services.notification_service import process_due_notification_jobs

    _engine, sessionmaker = notification_database
    [job_id] = await _seed_due_jobs(sessionmaker, 1)
    now = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)
    sends: list[int] = []

    async def deliver(job) -> None:
        async with sessionmaker() as observer:
            visible = await observer.get(type(job), job.id)
            assert visible.status == "sending"
            assert visible.lease_owner in {
                "worker-process-a",
                "worker-process-b",
            }
            assert visible.lease_expires_at == now + timedelta(minutes=2)
        sends.append(job.id)
        await asyncio.sleep(0.05)

    async def process(owner: str) -> int:
        async with sessionmaker() as session:
            return await process_due_notification_jobs(
                session,
                lease_owner=owner,
                limit=1,
                now=now,
                lease_duration=timedelta(minutes=2),
                deliver=deliver,
            )

    processed = await asyncio.gather(
        process("worker-process-a"),
        process("worker-process-b"),
    )
    assert sorted(processed) == [0, 1]
    assert sends == [job_id]
    async with sessionmaker() as session:
        persisted = await session.get(
            __import__(
                "models.notification_job",
                fromlist=["NotificationJob"],
            ).NotificationJob,
            job_id,
        )
        assert persisted.status == "delivered"
        assert persisted.lease_owner is None
        assert persisted.lease_expires_at is None


async def test_actual_processing_entrypoint_recovers_an_expired_lease(
    notification_database,
) -> None:
    from models.notification_job import NotificationJob
    from services.notification_service import process_due_notification_jobs

    _engine, sessionmaker = notification_database
    now = datetime(2026, 8, 20, 19, 0, tzinfo=UTC)
    async with sessionmaker() as session:
        stale = NotificationJob(
            event_type="stale",
            status="sending",
            recipient="admin@example.test",
            subject="Stale",
            payload_json="{}",
            lease_owner="dead-worker",
            lease_expires_at=now - timedelta(seconds=1),
        )
        session.add(stale)
        await session.commit()
        stale_id = stale.id

    sends: list[int] = []

    async def deliver(job) -> None:
        sends.append(job.id)

    async with sessionmaker() as session:
        processed = await process_due_notification_jobs(
            session,
            lease_owner="recovery-worker",
            limit=1,
            now=now,
            lease_duration=timedelta(minutes=2),
            deliver=deliver,
        )
    assert processed == 1
    assert sends == [stale_id]


async def test_two_workers_do_not_preclaim_or_duplicate_later_rows_while_first_delivery_stalls(
    notification_database,
) -> None:
    from models.notification_job import NotificationJob
    from services.notification_service import process_due_notification_jobs

    _engine, sessionmaker = notification_database
    first_id, second_id = await _seed_due_jobs(sessionmaker, 2)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    sends: list[tuple[str, int]] = []

    async def deliver_a(job: NotificationJob) -> None:
        sends.append(("worker-a", job.id))
        if job.id == first_id:
            first_started.set()
            await release_first.wait()

    async def deliver_b(job: NotificationJob) -> None:
        sends.append(("worker-b", job.id))

    async def process(owner: str, deliver) -> int:
        async with sessionmaker() as session:
            return await process_due_notification_jobs(
                session,
                lease_owner=owner,
                limit=2,
                lease_duration=timedelta(seconds=10),
                delivery_timeout=timedelta(seconds=5),
                deliver=deliver,
            )

    first_worker = asyncio.create_task(process("worker-a", deliver_a))
    first_processed: int | None = None
    second_processed: int | None = None
    try:
        await asyncio.wait_for(first_started.wait(), timeout=2)
        async with sessionmaker() as observer:
            first = await observer.get(NotificationJob, first_id)
            second = await observer.get(NotificationJob, second_id)
            assert first.status == "sending"
            assert first.lease_owner == "worker-a"
            assert second.status == "pending"
            assert second.lease_owner is None
            assert second.lease_expires_at is None

        second_processed = await asyncio.wait_for(
            process("worker-b", deliver_b),
            timeout=2,
        )
    finally:
        release_first.set()
        first_processed = await asyncio.wait_for(first_worker, timeout=2)

    assert (first_processed, second_processed) == (1, 1)
    assert sorted(sends) == sorted(
        [("worker-a", first_id), ("worker-b", second_id)]
    )


async def test_delivery_timeout_is_positive_strictly_below_lease_and_releases_claim(
    notification_database,
) -> None:
    from models.notification_job import NotificationJob
    from services.notification_service import (
        DEFAULT_NOTIFICATION_DELIVERY_TIMEOUT,
        DEFAULT_NOTIFICATION_LEASE_DURATION,
        process_due_notification_jobs,
    )

    assert timedelta(0) < DEFAULT_NOTIFICATION_DELIVERY_TIMEOUT
    assert (
        DEFAULT_NOTIFICATION_DELIVERY_TIMEOUT
        < DEFAULT_NOTIFICATION_LEASE_DURATION
    )
    _engine, sessionmaker = notification_database

    async with sessionmaker() as session:
        for invalid_timeout in (timedelta(0), timedelta(seconds=1)):
            with pytest.raises(ValueError, match="delivery_timeout"):
                await process_due_notification_jobs(
                    session,
                    limit=1,
                    lease_duration=timedelta(seconds=1),
                    delivery_timeout=invalid_timeout,
                )

    [job_id] = await _seed_due_jobs(sessionmaker, 1)

    async def stalled_delivery(_job: NotificationJob) -> None:
        await asyncio.Event().wait()

    async with sessionmaker() as session:
        processed = await asyncio.wait_for(
            process_due_notification_jobs(
                session,
                lease_owner="timeout-worker",
                limit=1,
                lease_duration=timedelta(seconds=1),
                delivery_timeout=timedelta(milliseconds=50),
                deliver=stalled_delivery,
            ),
            timeout=0.5,
        )
    assert processed == 1
    async with sessionmaker() as session:
        job = await session.get(NotificationJob, job_id)
        assert job.status == "failed"
        assert job.last_error == "notification_delivery_failed"
        assert job.lease_owner is None
        assert job.lease_expires_at is None
