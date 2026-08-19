from __future__ import annotations

import asyncio
import hashlib
import json
import os
import ssl
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import models  # noqa: F401 - register the complete metadata used by foreign keys
from database import Base
from models.command import CRMActivity, CRMContact, CRMTask
from models.crm_task_lifecycle import (
    CRMRecordLifecycleEvent,
    CRMTaskCreationRequest,
    CRMTaskSource,
)
from services.crm_task_service import (
    CRMTaskService,
    CreateTaskCommand,
    TaskActor,
    TaskCommandValidationError,
    TaskContactNotFound,
    TaskCreationStateError,
    TaskIdempotencyConflict,
    TaskSource,
    TaskSourceConflict,
    canonical_task_command_json,
)
from tests.test_crm_task_lifecycle_migration import _public_schema_user_objects


NOW = datetime(2026, 8, 18, 9, 15, tzinfo=timezone(timedelta(hours=-4)))
OWNERSHIP_TABLE = "_crm_task_service_test_ownership"


def _test_database_url() -> sa.engine.URL:
    raw_url = os.getenv("CRM_TASK_TEST_DATABASE_URL")
    expected_name = os.getenv("CRM_TASK_TEST_DATABASE_NAME")
    if not raw_url or not expected_name:
        if os.getenv("CI", "").casefold() == "true":
            pytest.fail("CI requires CRM_TASK_TEST_DATABASE_URL and CRM_TASK_TEST_DATABASE_NAME")
        pytest.skip("CRM task PostgreSQL test database is not provisioned")
    url = make_url(raw_url)
    assert expected_name.endswith("_test")
    assert url.database == expected_name
    assert url.drivername.startswith("postgresql")
    return url


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


@asynccontextmanager
async def owned_task_database():
    url = _test_database_url()
    expected_name = os.environ["CRM_TASK_TEST_DATABASE_NAME"]
    engine = create_async_engine(url, connect_args={"ssl": _ssl_context()})
    marker = uuid4().hex
    armed = False
    try:
        async with engine.begin() as connection:
            assert await connection.scalar(sa.text("SELECT current_database()")) == expected_name
            objects = await connection.run_sync(_public_schema_user_objects)
            assert objects == [], f"public schema is not empty: {objects}"
            await connection.execute(
                sa.text(f"CREATE TABLE public.{OWNERSHIP_TABLE} (marker text PRIMARY KEY)")
            )
            await connection.execute(
                sa.text(f"INSERT INTO public.{OWNERSHIP_TABLE} (marker) VALUES (:marker)"),
                {"marker": marker},
            )
            await connection.run_sync(Base.metadata.create_all)
        armed = True
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if armed:
            async with engine.begin() as connection:
                assert await connection.scalar(sa.text("SELECT current_database()")) == expected_name
                assert await connection.scalar(
                    sa.text(f"SELECT count(*) FROM public.{OWNERSHIP_TABLE} WHERE marker=:marker"),
                    {"marker": marker},
                ) == 1
                await connection.execute(sa.text("DROP SCHEMA public CASCADE"))
                await connection.execute(sa.text("CREATE SCHEMA public"))
        await engine.dispose()


@pytest_asyncio.fixture()
async def task_database():
    async with owned_task_database() as resources:
        yield resources


def command(**overrides: object) -> CreateTaskCommand:
    values: dict[str, object] = {
        "title": "Call Jane",
        "description": "Discuss listing",
        "priority": "normal",
        "due_at": NOW,
        "contact_id": None,
        "actor": TaskActor(type="admin", id="admin-1"),
        "source": TaskSource(type="command_ui", id="request-1", key="primary"),
        "idempotency_scope": "command_ui",
        "idempotency_key": "request-1",
        "client_timezone": "America/New_York",
    }
    values.update(overrides)
    return CreateTaskCommand(**values)  # type: ignore[arg-type]


def test_canonical_hash_input_is_compact_sorted_complete_and_utc() -> None:
    rendered = canonical_task_command_json(command())
    assert rendered == json.dumps(
        {
            "actor": {"id": "admin-1", "type": "admin"},
            "client_timezone": "America/New_York",
            "contact_id": None,
            "description": "Discuss listing",
            "due_at": "2026-08-18T13:15:00Z",
            "idempotency_key": "request-1",
            "idempotency_scope": "command_ui",
            "priority": "normal",
            "source": {"id": "request-1", "key": "primary", "type": "command_ui"},
            "status": "open",
            "title": "Call Jane",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    assert '": ' not in rendered
    assert ', "' not in rendered


@pytest.mark.parametrize(
    "override",
    [
        {"title": ""},
        {"title": "x" * 256},
        {"description": 7},
        {"priority": "urgent"},
        {"priority": []},
        {"status": "archived"},
        {"status": []},
        {"due_at": object()},
        {"due_at": datetime(2026, 8, 18, 9, 15)},
        {
            "due_at": datetime.max.replace(
                tzinfo=timezone(timedelta(hours=-23, minutes=-59))
            )
        },
        {"contact_id": 0},
        {"actor": []},
        {"actor": TaskActor(type="robot", id="1")},
        {"actor": TaskActor(type=[], id="1")},
        {"actor": TaskActor(type="admin", id="")},
        {"source": []},
        {"source": TaskSource(type="webhook", id="1", key="primary")},
        {"source": TaskSource(type=[], id="1", key="primary")},
        {"source": TaskSource(type="command_ui", id="", key="primary")},
        {"source": TaskSource(type="command_ui", id="1", key="")},
        {"idempotency_scope": "x" * 65},
        {"idempotency_key": "x" * 129},
        {"client_timezone": "Eastern Standard Time"},
    ],
)
@pytest.mark.asyncio
async def test_command_validation_fails_before_database_use(override) -> None:
    with pytest.raises(TaskCommandValidationError):
        await CRMTaskService().create(None, command(**override))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_persists_claim_source_activity_lifecycle_and_exact_replay(task_database) -> None:
    _engine, factory = task_database
    async with factory() as session, session.begin():
        contact = CRMContact(first_name="Jane", last_name="Owner", email="jane@example.test")
        session.add(contact)
        await session.flush()
        task_command = command(contact_id=contact.id)
        first = await CRMTaskService().create(session, task_command)
        second = await CRMTaskService().create(session, task_command)

        assert first.replayed is False
        assert second.replayed is True
        assert second.task.id == first.task.id
        claim = (await session.scalars(sa.select(CRMTaskCreationRequest))).one()
        source = (await session.scalars(sa.select(CRMTaskSource))).one()
        activity = (await session.scalars(sa.select(CRMActivity))).one()
        lifecycle = (await session.scalars(sa.select(CRMRecordLifecycleEvent))).one()
        assert claim.payload_hash == hashlib.sha256(
            canonical_task_command_json(task_command).encode("utf-8")
        ).hexdigest()
        assert claim.state == "applied"
        assert claim.task_id == first.task.id
        assert claim.result_version == 1
        assert claim.metadata_json == '{"client_timezone":"America/New_York"}'
        assert (source.source_type, source.source_id, source.source_key) == (
            "command_ui", "request-1", "primary"
        )
        assert activity.contact_id == contact.id
        assert "\n" not in activity.summary
        assert lifecycle.action == "create"
        assert lifecycle.entity_type == "task"
        assert isinstance(lifecycle.request_id, UUID)
        assert lifecycle.request_id.version == 5
        assert lifecycle.request_hash == claim.payload_hash
        assert (lifecycle.actor_type, lifecycle.actor_id) == ("admin", "admin-1")
        assert (lifecycle.source_type, lifecycle.source_id) == ("command_ui", "request-1")
        assert json.loads(lifecycle.result_json) == {
            "contact_id": contact.id,
            "description": "Discuss listing",
            "due_at": "2026-08-18T13:15:00Z",
            "id": first.task.id,
            "priority": "normal",
            "status": "open",
            "title": "Call Jane",
            "version": 1,
        }
        assert lifecycle.result_json == json.dumps(
            json.loads(lifecycle.result_json), sort_keys=True, separators=(",", ":")
        )


@pytest.mark.asyncio
async def test_contactless_task_creates_no_contact_activity(task_database) -> None:
    _engine, factory = task_database
    async with factory() as session, session.begin():
        result = await CRMTaskService().create(session, command())
        assert result.task.contact_id is None
        assert await session.scalar(sa.select(sa.func.count()).select_from(CRMActivity)) == 0


@pytest.mark.asyncio
async def test_missing_contact_is_typed_and_writes_nothing(task_database) -> None:
    _engine, factory = task_database
    async with factory() as session, session.begin():
        with pytest.raises(TaskContactNotFound):
            await CRMTaskService().create(session, command(contact_id=987654))
        for table in (CRMTaskCreationRequest, CRMTask, CRMTaskSource, CRMRecordLifecycleEvent):
            assert await session.scalar(sa.select(sa.func.count()).select_from(table)) == 0


@pytest.mark.asyncio
async def test_key_reuse_with_changed_payload_is_typed_conflict(task_database) -> None:
    _engine, factory = task_database
    async with factory() as session, session.begin():
        await CRMTaskService().create(session, command())
        with pytest.raises(TaskIdempotencyConflict) as captured:
            await CRMTaskService().create(session, command(title="Call somebody else"))
        assert captured.value.code == "task_idempotency_mismatch"
        assert await session.scalar(sa.select(sa.func.count()).select_from(CRMTask)) == 1


@pytest.mark.asyncio
async def test_incomplete_replay_state_is_typed_error(task_database) -> None:
    _engine, factory = task_database
    async with factory() as session, session.begin():
        await CRMTaskService().create(session, command())
        claim = (await session.scalars(sa.select(CRMTaskCreationRequest))).one()
        claim.state = "applying"
        claim.task_id = None
        await session.flush()
        with pytest.raises(TaskCreationStateError) as captured:
            await CRMTaskService().create(session, command())
        assert captured.value.code == "task_creation_state_invalid"


@pytest.mark.asyncio
async def test_source_identity_conflict_rolls_back_new_claim_and_task(task_database) -> None:
    _engine, factory = task_database
    async with factory() as session, session.begin():
        await CRMTaskService().create(session, command())
        with pytest.raises(TaskSourceConflict):
            await CRMTaskService().create(
                session,
                command(idempotency_key="request-2", idempotency_scope="other-scope"),
            )
        assert await session.scalar(sa.select(sa.func.count()).select_from(CRMTask)) == 1
        assert await session.scalar(sa.select(sa.func.count()).select_from(CRMTaskCreationRequest)) == 1
        assert await session.scalar(sa.select(sa.func.count()).select_from(CRMTaskSource)) == 1
        assert await session.scalar(sa.select(sa.func.count()).select_from(CRMRecordLifecycleEvent)) == 1


@pytest.mark.parametrize(
    "rejected_type",
    [CRMTaskSource, CRMActivity, CRMRecordLifecycleEvent],
    ids=["source", "activity", "lifecycle"],
)
@pytest.mark.asyncio
async def test_each_late_persistence_failure_rolls_back_every_creation_row(
    monkeypatch, task_database, rejected_type
) -> None:
    _engine, factory = task_database
    async with factory() as session, session.begin():
        contact = CRMContact(
            first_name="Rollback", last_name="Owner", email="rollback@example.test"
        )
        session.add(contact)
        await session.flush()
        original_add = session.add

        def reject_persistence(instance, *args, **kwargs):
            if isinstance(instance, rejected_type):
                raise RuntimeError(f"synthetic {rejected_type.__tablename__} failure")
            return original_add(instance, *args, **kwargs)

        monkeypatch.setattr(session, "add", reject_persistence)
        with pytest.raises(RuntimeError, match="synthetic crm_"):
            await CRMTaskService().create(session, command(contact_id=contact.id))
        monkeypatch.setattr(session, "add", original_add)
        for table in (
            CRMTaskCreationRequest,
            CRMTask,
            CRMTaskSource,
            CRMActivity,
            CRMRecordLifecycleEvent,
        ):
            assert await session.scalar(sa.select(sa.func.count()).select_from(table)) == 0


@pytest.mark.asyncio
async def test_concurrent_callers_use_independent_committing_postgresql_sessions(task_database) -> None:
    _engine, factory = task_database
    barrier = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def worker():
        nonlocal ready
        async with factory() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    barrier.set()
            await barrier.wait()
            async with session.begin():
                result = await CRMTaskService().create(session, command())
            return result.task.id, result.replayed

    first, second = await asyncio.gather(worker(), worker())
    assert first[0] == second[0]
    assert sorted((first[1], second[1])) == [False, True]
    async with factory() as verifier:
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTask)) == 1
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTaskCreationRequest)) == 1
