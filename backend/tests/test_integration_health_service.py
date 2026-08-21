from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.gmail_task_postgres import (
    async_test_url,
    migrated_test_database,
)


REVISION = "82b5e3d7f0a1"
UTC = timezone.utc


@pytest.fixture(scope="module")
def runtime_database():
    with migrated_test_database(REVISION) as database:
        yield database


@pytest.fixture
async def runtime_sessionmaker(runtime_database):
    url, _sync_engine = runtime_database
    engine = create_async_engine(async_test_url(url), pool_pre_ping=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_health_transitions_are_versioned_sanitized_and_recoverable(
    runtime_sessionmaker,
) -> None:
    from services.integration_health_service import (
        record_integration_failure,
        record_integration_success,
    )

    first_check = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    async with runtime_sessionmaker() as session:
        first = await record_integration_failure(
            session,
            provider="gmail_task_intake",
            state="degraded",
            checked_at=first_check,
            error_category="oauth_revoked",
            raw_error=(
                "Bearer private-token user@example.test "
                "https://provider.test/path?access_token=private"
            ),
        )
        await session.commit()
        assert first.provider == "gmail_task_intake"
        assert first.state == "degraded"
        assert first.transition_epoch == 1
        assert first.consecutive_failures == 1
        assert first.last_error_category == "oauth_revoked"
        assert first.last_error_message == "Authentication must be renewed."
        assert "private" not in first.last_error_message
        assert "example.test" not in first.last_error_message

    async with runtime_sessionmaker() as session:
        repeated = await record_integration_failure(
            session,
            provider="gmail_task_intake",
            state="degraded",
            checked_at=first_check + timedelta(minutes=1),
            error_category="oauth_revoked",
            raw_error="different secret material",
        )
        await session.commit()
        assert repeated.transition_epoch == 1
        assert repeated.consecutive_failures == 2

    recovered_at = first_check + timedelta(minutes=2)
    async with runtime_sessionmaker() as session:
        recovered = await record_integration_success(
            session,
            provider="gmail_task_intake",
            checked_at=recovered_at,
        )
        await session.commit()
        assert recovered.state == "healthy"
        assert recovered.transition_epoch == 2
        assert recovered.consecutive_failures == 0
        assert recovered.last_succeeded_at == recovered_at
        assert recovered.recovered_at == recovered_at
        assert recovered.last_error_category is None
        assert recovered.last_error_message is None


def test_health_notification_dedupe_keys_are_deterministic_and_bounded() -> None:
    from services.integration_health_service import integration_alert_dedupe_key

    assert integration_alert_dedupe_key(
        provider="gmail_task_intake",
        transition_epoch=7,
        event="opened",
    ) == "integration-health:gmail_task_intake:epoch:7:opened"
    assert integration_alert_dedupe_key(
        provider="gmail_task_intake",
        transition_epoch=7,
        event="opened",
    ) == integration_alert_dedupe_key(
        provider="gmail_task_intake",
        transition_epoch=7,
        event="opened",
    )
    assert integration_alert_dedupe_key(
        provider="gmail_task_intake",
        transition_epoch=7,
        event="recovered",
    ) != integration_alert_dedupe_key(
        provider="gmail_task_intake",
        transition_epoch=7,
        event="opened",
    )
    with pytest.raises(ValueError, match="provider"):
        integration_alert_dedupe_key(
            provider="x" * 65,
            transition_epoch=1,
            event="opened",
        )
    with pytest.raises(ValueError, match="positive"):
        integration_alert_dedupe_key(
            provider="gmail_task_intake",
            transition_epoch=0,
            event="opened",
        )


def _manual_signed_key(material: bytes) -> int:
    import hashlib

    unsigned = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    return unsigned - 2**64 if unsigned >= 2**63 else unsigned


def test_advisory_v1_vectors_domain_and_framing_are_exact() -> None:
    from services.integration_advisory_locks import (
        account_advisory_key,
        thread_advisory_key,
    )

    account_id = UUID("00000000-0000-0000-0000-000000000001")
    thread = b"thread-123"
    account_material = (
        b"sws:gmail-task-intake:advisory:v1:account\x00"
        + account_id.bytes
    )
    thread_material = (
        b"sws:gmail-task-intake:advisory:v1:thread\x00"
        + account_id.bytes
        + len(thread).to_bytes(2, "big")
        + thread
    )
    assert account_advisory_key(account_id) == 848794804012879307
    assert thread_advisory_key(account_id, "thread-123") == (
        -7678506188538908948
    )
    assert account_advisory_key(account_id) == _manual_signed_key(
        account_material
    )
    assert thread_advisory_key(account_id, "thread-123") == (
        _manual_signed_key(thread_material)
    )
    assert account_advisory_key(account_id) != thread_advisory_key(
        account_id,
        "",
    )
    assert thread_advisory_key(account_id, "a") != thread_advisory_key(
        account_id,
        "\x00a",
    )
    with pytest.raises(ValueError, match="ASCII"):
        thread_advisory_key(account_id, "thréad")
    with pytest.raises(ValueError, match="65535"):
        thread_advisory_key(account_id, "x" * 65536)


@pytest.mark.parametrize("seed", ("0", "1", "random"))
def test_advisory_keys_do_not_depend_on_python_hash_seed(seed: str) -> None:
    code = """
from uuid import UUID
from services.integration_advisory_locks import account_advisory_key, thread_advisory_key
account = UUID('00000000-0000-0000-0000-000000000001')
print(account_advisory_key(account))
print(thread_advisory_key(account, 'thread-123'))
"""
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = seed
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == [
        "848794804012879307",
        "-7678506188538908948",
    ]


async def test_session_and_transaction_advisory_helpers_use_postgresql_primitives(
    runtime_sessionmaker,
) -> None:
    from services.integration_advisory_locks import (
        release_session_advisory_lock,
        try_session_advisory_lock,
        transaction_advisory_lock,
    )

    account_id = UUID("00000000-0000-0000-0000-000000000001")
    first = runtime_sessionmaker()
    second = runtime_sessionmaker()
    try:
        first_connection = await first.connection()
        second_connection = await second.connection()
        assert await try_session_advisory_lock(first_connection, account_id)
        assert not await try_session_advisory_lock(second_connection, account_id)
        assert await release_session_advisory_lock(first_connection, account_id)
        assert await try_session_advisory_lock(second_connection, account_id)
        assert await release_session_advisory_lock(second_connection, account_id)

        await transaction_advisory_lock(
            first_connection,
            account_id,
            "thread-123",
        )
        await first.commit()
    finally:
        await first.close()
        await second.close()


async def test_synchronous_provider_deadline_keeps_event_loop_responsive() -> None:
    from services.integration_health_service import (
        BoundedProviderExecutor,
        ProviderCallTimedOut,
        ProviderJobStillRunning,
    )

    executor = BoundedProviderExecutor(max_workers=1)
    release = __import__("threading").Event()
    started = __import__("threading").Event()

    def stalled_provider() -> str:
        started.set()
        release.wait(timeout=5)
        return "late"

    try:
        provider_call = asyncio.create_task(
            executor.run(
                key="gmail:account-1",
                function=stalled_provider,
                deadline_seconds=0.05,
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        ticks = 0

        async def event_loop_probe() -> None:
            nonlocal ticks
            for _ in range(5):
                await asyncio.sleep(0)
                ticks += 1

        await event_loop_probe()
        with pytest.raises(ProviderCallTimedOut, match="provider_timeout"):
            await provider_call
        assert ticks == 5
        with pytest.raises(ProviderJobStillRunning, match="already_running"):
            await executor.run(
                key="gmail:account-1",
                function=lambda: "must-not-run",
                deadline_seconds=0.05,
            )
    finally:
        release.set()
        await executor.wait_for_tracked_calls()
        executor.shutdown()
