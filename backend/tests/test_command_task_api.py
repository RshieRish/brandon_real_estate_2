from __future__ import annotations

import asyncio
import ast
import inspect
import json
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI
from jose import jwt
from pydantic import ValidationError

import database
from config import settings
from database import get_db
from models.command import (
    CRMActivity,
    CRMAgreement,
    CRMContact,
    CRMListingRecord,
    CRMOpportunity,
    CRMTask,
    CRMTaskLink,
)
from models.crm_task_lifecycle import (
    CRMRecordLifecycleEvent,
    CRMTaskCreationRequest,
    CRMTaskSource,
)
from routers import command as command_router
from schemas.command import TaskUpdate
from services.command_tasks import archive_task_source_key
from tests.test_crm_task_service import owned_task_database


@pytest_asyncio.fixture()
async def task_api_database():
    async with owned_task_database() as resources:
        yield resources


@pytest.fixture()
def task_app(monkeypatch, task_api_database):
    _engine, factory = task_api_database
    monkeypatch.setattr(database, "AsyncSessionLocal", factory)
    app = FastAPI()
    app.include_router(command_router.router, prefix="/api/v1/command")
    return app


@pytest.fixture()
def task_lifecycle_app(monkeypatch, task_app):
    monkeypatch.setitem(settings.__dict__, "CRM_TASK_ARCHIVE_ENABLED", True)
    return task_app


def _token(subject: str = "17") -> str:
    return jwt.encode(
        {
            "sub": subject,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "token_type": "admin_session",
            "scope": "admin",
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def _headers(
    key: UUID | str | None = None, *, subject: str = "17"
) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_token(subject)}"}
    if key is not None:
        headers["X-Idempotency-Key"] = str(key)
    return headers


def _non_admin_headers(subject: str = "17") -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": subject,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "token_type": "user_session",
            "scope": "user",
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


async def _request(app: FastAPI, method: str, path: str, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        return await client.request(method, path, **kwargs)


async def _create_task(app: FastAPI, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "Call Jane",
        "description": "Discuss listing",
        "priority": "normal",
        "due_at": "2026-08-18T13:15:00Z",
    }
    payload.update(overrides)
    response = await _request(
        app,
        "POST",
        "/api/v1/command/tasks",
        json=payload,
        headers=_headers(uuid4()),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _create_contact(task_api_database) -> int:
    _engine, factory = task_api_database
    async with factory() as session, session.begin():
        contact = CRMContact(
            first_name="Avery",
            last_name="Lake",
            email=f"avery-{uuid4()}@example.test",
        )
        session.add(contact)
        await session.flush()
        return contact.id


def _lifecycle_payload(
    expected_version: int,
    *,
    request_id: UUID | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_id": str(request_id or uuid4()),
        "expected_version": expected_version,
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


@pytest.mark.asyncio
async def test_post_tasks_requires_admin_and_uuid_idempotency_header(task_app) -> None:
    path = "/api/v1/command/tasks"
    payload = {"title": "Call Jane"}
    assert (await _request(task_app, "POST", path, json=payload)).status_code == 401
    assert (
        await _request(task_app, "POST", path, json=payload, headers=_headers())
    ).status_code == 422
    assert (
        await _request(task_app, "POST", path, json=payload, headers=_headers("not-a-uuid"))
    ).status_code == 422


@pytest.mark.asyncio
async def test_post_tasks_exact_replay_returns_original_and_authenticated_actor(
    task_app, task_api_database
) -> None:
    key = uuid4()
    path = "/api/v1/command/tasks"
    payload = {
        "title": "Call Jane",
        "description": "Discuss listing",
        "priority": "high",
        "due_at": "2026-08-18T13:15:00Z",
    }
    first = await _request(task_app, "POST", path, json=payload, headers=_headers(key))
    second = await _request(task_app, "POST", path, json=payload, headers=_headers(key))
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()

    _engine, factory = task_api_database
    async with factory() as verifier:
        claim = (await verifier.scalars(sa.select(CRMTaskCreationRequest))).one()
        assert (claim.actor_type, claim.actor_id) == ("admin", "17")
        assert (claim.source_type, claim.source_id) == ("command_ui", str(key))
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTask)) == 1
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTaskSource)) == 1
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMRecordLifecycleEvent)) == 1


@pytest.mark.asyncio
async def test_post_tasks_changed_replay_returns_structured_409(task_app) -> None:
    key = uuid4()
    path = "/api/v1/command/tasks"
    first = await _request(task_app, "POST", path, json={"title": "First"}, headers=_headers(key))
    conflict = await _request(task_app, "POST", path, json={"title": "Changed"}, headers=_headers(key))
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json() == {
        "detail": {
            "code": "task_idempotency_mismatch",
            "message": "Idempotency key was already used with a different task request",
        }
    }


@pytest.mark.asyncio
async def test_real_get_db_finalizer_commits_success_and_rolls_back_late_failure(
    monkeypatch, task_app, task_api_database
) -> None:
    path = "/api/v1/command/tasks"
    success = await _request(
        task_app, "POST", path, json={"title": "Committed"}, headers=_headers(uuid4())
    )
    assert success.status_code == 200

    service = command_router.crm_task_service
    original_create = service.create

    async def create_then_fail(db, task_command):
        await original_create(db, task_command)
        raise RuntimeError("synthetic response failure")

    monkeypatch.setattr(service, "create", create_then_fail)
    failed = await _request(
        task_app, "POST", path, json={"title": "Rolled back"}, headers=_headers(uuid4())
    )
    assert failed.status_code == 500

    _engine, factory = task_api_database
    async with factory() as verifier:
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTask)) == 1
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTaskCreationRequest)) == 1
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTaskSource)) == 1
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMRecordLifecycleEvent)) == 1


@pytest.mark.asyncio
async def test_archive_import_keeps_same_title_rows_and_replays_by_stable_identity(
    task_app, task_api_database
) -> None:
    payload = {
        "source_id": "fixture-export-2026-08-18",
        "tasks": [
            {
                "source_row_id": "task-row-1",
                "title": "Same title",
                "description": "First source row",
            },
            {
                "source_row_id": "task-row-2",
                "title": "Same title",
                "description": "Second source row",
                "status": "completed",
            },
        ]
    }
    first = await _request(
        task_app, "POST", "/api/v1/command/archive/import", json=payload, headers=_headers()
    )
    second = await _request(
        task_app, "POST", "/api/v1/command/archive/import", json=payload, headers=_headers()
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["created"]["tasks"] == 2
    assert second.json()["created"]["tasks"] == 0
    assert second.json()["skipped_duplicates"]["tasks"] == 2

    _engine, factory = task_api_database
    async with factory() as verifier:
        tasks = (await verifier.scalars(sa.select(CRMTask).order_by(CRMTask.id))).all()
        sources = (await verifier.scalars(sa.select(CRMTaskSource).order_by(CRMTaskSource.id))).all()
        assert [task.title for task in tasks] == ["Same title", "Same title"]
        assert {task.description: task.status for task in tasks} == {
            "First source row": "open",
            "Second source row": "completed",
        }
        assert len({source.source_key for source in sources}) == 2
        assert all(UUID(source.source_key).version == 5 for source in sources)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"tasks": [{"source_row_id": "task-1", "title": "Missing source"}]},
        {"source_id": "source-1", "tasks": [{"title": "Missing row identity"}]},
        {
            "source_id": "   ",
            "tasks": [{"source_row_id": "task-1", "title": "Blank source"}],
        },
        {
            "source_id": "source-1",
            "tasks": [{"source_row_id": "\t", "title": "Blank row identity"}],
        },
        {
            "source_id": "x" * 256,
            "tasks": [{"source_row_id": "task-1", "title": "Long source"}],
        },
        {
            "source_id": "source-1",
            "tasks": [{"source_row_id": "x" * 129, "title": "Long row"}],
        },
    ],
)
async def test_archive_task_identity_is_required_and_bounded(task_app, payload) -> None:
    response = await _request(
        task_app,
        "POST",
        "/api/v1/command/archive/import",
        json=payload,
        headers=_headers(),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_archive_retry_survives_row_reordering(task_app, task_api_database) -> None:
    first_payload = {
        "source_id": "stable-export",
        "tasks": [
            {"source_row_id": "row-a", "title": "First"},
            {"source_row_id": "row-b", "title": "Second"},
        ],
    }
    reordered = {
        "source_id": "stable-export",
        "tasks": list(reversed(first_payload["tasks"])),
    }
    first = await _request(
        task_app, "POST", "/api/v1/command/archive/import", json=first_payload, headers=_headers()
    )
    replay = await _request(
        task_app, "POST", "/api/v1/command/archive/import", json=reordered, headers=_headers()
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["created"]["tasks"] == 2
    assert replay.json()["created"]["tasks"] == 0
    assert replay.json()["skipped_duplicates"]["tasks"] == 2
    _engine, factory = task_api_database
    async with factory() as verifier:
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTask)) == 2


@pytest.mark.asyncio
async def test_concurrent_reversed_archive_requests_lock_tasks_in_stable_order(
    monkeypatch, task_app, task_api_database
) -> None:
    source_id = "concurrent-reversed-export"
    rows = [
        {"source_row_id": "row-a", "title": "First"},
        {"source_row_id": "row-b", "title": "Second"},
    ]
    ordered_rows = sorted(
        rows,
        key=lambda row: archive_task_source_key(source_id, row["source_row_id"]),
    )
    payloads = (
        {"source_id": source_id, "tasks": ordered_rows},
        {"source_id": source_id, "tasks": list(reversed(ordered_rows))},
    )

    original_create = command_router.crm_task_service.create
    first_call_ready = asyncio.Event()
    first_call_finished = asyncio.Event()
    first_keys_by_session: dict[int, str] = {}
    finished_first_calls = 0
    gate_lock = asyncio.Lock()

    async def create_with_concurrency_gate(db, task_command):
        nonlocal finished_first_calls
        session_key = id(db)
        async with gate_lock:
            is_first_call = session_key not in first_keys_by_session
            if is_first_call:
                first_keys_by_session[session_key] = task_command.source.key
                if len(first_keys_by_session) == 2:
                    first_call_ready.set()
        if is_first_call:
            await asyncio.wait_for(first_call_ready.wait(), timeout=3)

        result = await original_create(db, task_command)

        # The old caller-order implementation reaches this branch with two
        # different first locks. Hold both until acquired so its second calls
        # deterministically exercise PostgreSQL's reversed-lock deadlock.
        if is_first_call and len(set(first_keys_by_session.values())) == 2:
            async with gate_lock:
                finished_first_calls += 1
                if finished_first_calls == 2:
                    first_call_finished.set()
            await asyncio.wait_for(first_call_finished.wait(), timeout=3)
        return result

    monkeypatch.setattr(
        command_router.crm_task_service, "create", create_with_concurrency_gate
    )
    responses = await asyncio.wait_for(
        asyncio.gather(
            *(
                _request(
                    task_app,
                    "POST",
                    "/api/v1/command/archive/import",
                    json=payload,
                    headers=_headers(),
                )
                for payload in payloads
            )
        ),
        timeout=8,
    )

    assert len(first_keys_by_session) == 2
    assert len(set(first_keys_by_session.values())) == 1
    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["created"]["tasks"] for response in responses) == [0, 2]
    assert sorted(
        response.json()["skipped_duplicates"]["tasks"] for response in responses
    ) == [0, 2]
    _engine, factory = task_api_database
    async with factory() as verifier:
        for model in (
            CRMTask,
            CRMTaskSource,
            CRMTaskCreationRequest,
            CRMRecordLifecycleEvent,
        ):
            assert await verifier.scalar(
                sa.select(sa.func.count()).select_from(model)
            ) == 2


@pytest.mark.asyncio
async def test_archive_edited_row_with_same_identity_is_structured_409(task_app, task_api_database) -> None:
    original = {
        "source_id": "edited-export",
        "tasks": [{"source_row_id": "row-1", "title": "Original title"}],
    }
    edited = {
        "source_id": "edited-export",
        "tasks": [{"source_row_id": "row-1", "title": "Edited title"}],
    }
    assert (
        await _request(
            task_app, "POST", "/api/v1/command/archive/import", json=original, headers=_headers()
        )
    ).status_code == 200
    conflict = await _request(
        task_app, "POST", "/api/v1/command/archive/import", json=edited, headers=_headers()
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "task_idempotency_mismatch"
    _engine, factory = task_api_database
    async with factory() as verifier:
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTask)) == 1


@pytest.mark.asyncio
async def test_identical_archive_rows_from_distinct_sources_create_distinct_tasks(
    task_app, task_api_database
) -> None:
    task = {"source_row_id": "row-1", "title": "Identical task"}
    for source_id in ("export-a", "export-b"):
        response = await _request(
            task_app,
            "POST",
            "/api/v1/command/archive/import",
            json={"source_id": source_id, "tasks": [task]},
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json()["created"]["tasks"] == 1
    _engine, factory = task_api_database
    async with factory() as verifier:
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTask)) == 2


@pytest.mark.asyncio
async def test_archive_retry_by_another_admin_is_actor_bound_structured_409(
    task_app, task_api_database
) -> None:
    payload = {
        "source_id": "actor-bound-export",
        "tasks": [{"source_row_id": "row-1", "title": "Actor-bound task"}],
    }
    first = await _request(
        task_app,
        "POST",
        "/api/v1/command/archive/import",
        json=payload,
        headers=_headers(subject="17"),
    )
    conflict = await _request(
        task_app,
        "POST",
        "/api/v1/command/archive/import",
        json=payload,
        headers=_headers(subject="18"),
    )
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "task_idempotency_mismatch"
    _engine, factory = task_api_database
    async with factory() as verifier:
        assert await verifier.scalar(sa.select(sa.func.count()).select_from(CRMTask)) == 1


def test_command_router_does_not_replace_get_db_dependency() -> None:
    route = next(
        route
        for route in command_router.router.routes
        if getattr(route, "path", None) == "/tasks" and getattr(route, "methods", None) == {"POST"}
    )
    assert any(dependency.call is get_db for dependency in route.dependant.dependencies)


def test_task_archive_feature_flag_defaults_off_and_is_documented() -> None:
    assert (
        settings.__class__.model_fields["CRM_TASK_ARCHIVE_ENABLED"].default
        is False
    )
    env_example = (Path(__file__).parents[1] / ".env.example").read_text(
        encoding="utf-8"
    )
    assignments = [
        line
        for line in env_example.splitlines()
        if line.startswith("CRM_TASK_ARCHIVE_ENABLED=")
    ]
    assert assignments == ["CRM_TASK_ARCHIVE_ENABLED=false"]


@pytest.mark.asyncio
async def test_archive_restore_require_admin_and_enabled_flag(
    monkeypatch, task_app, task_api_database
) -> None:
    task = await _create_task(task_app)
    payload = _lifecycle_payload(1)
    archive_path = f"/api/v1/command/tasks/{task['id']}/archive"
    restore_path = f"/api/v1/command/tasks/{task['id']}/restore"

    monkeypatch.setitem(settings.__dict__, "CRM_TASK_ARCHIVE_ENABLED", False)
    for path in (archive_path, restore_path):
        assert (
            await _request(task_app, "POST", path, json=payload)
        ).status_code == 401
        assert (
            await _request(
                task_app,
                "POST",
                path,
                json=payload,
                headers=_non_admin_headers(),
            )
        ).status_code == 403
    disabled_archive = await _request(
        task_app,
        "POST",
        archive_path,
        json=payload,
        headers=_headers(),
    )
    disabled_restore = await _request(
        task_app,
        "POST",
        restore_path,
        json=payload,
        headers=_headers(),
    )
    assert disabled_archive.status_code == disabled_restore.status_code == 503

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None
        assert stored.version == 1
        assert stored.archived_at is None
        assert await verifier.scalar(
            sa.select(sa.func.count())
            .select_from(CRMRecordLifecycleEvent)
            .where(CRMRecordLifecycleEvent.action.in_(("archive", "restore")))
        ) == 0


@pytest.mark.asyncio
async def test_patch_and_link_remain_available_when_archive_flag_is_disabled(
    monkeypatch, task_app, task_api_database
) -> None:
    monkeypatch.setitem(settings.__dict__, "CRM_TASK_ARCHIVE_ENABLED", False)
    contact_id = await _create_contact(task_api_database)
    task = await _create_task(task_app)
    task_path = f"/api/v1/command/tasks/{task['id']}"

    patched = await _request(
        task_app,
        "PATCH",
        task_path,
        json={"expected_version": 1, "priority": "high"},
        headers=_headers(),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["version"] == 2

    linked = await _request(
        task_app,
        "POST",
        f"{task_path}/links",
        json={
            "entity_type": "contact",
            "entity_id": contact_id,
            "expected_version": 2,
        },
        headers=_headers(),
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["task_version"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"expected_version": 1},
        {"request_id": str(uuid4())},
        {"request_id": "not-a-uuid", "expected_version": 1},
        {"request_id": str(uuid4()), "expected_version": 0},
        {"request_id": str(uuid4()), "expected_version": True},
        {
            "request_id": str(uuid4()),
            "expected_version": 1,
            "reason": "x" * 501,
        },
        {
            "request_id": str(uuid4()),
            "expected_version": 1,
            "unexpected": True,
        },
    ],
)
async def test_archive_restore_request_body_is_strict(
    task_lifecycle_app, payload
) -> None:
    task = await _create_task(task_lifecycle_app)
    for action in ("archive", "restore"):
        response = await _request(
            task_lifecycle_app,
            "POST",
            f"/api/v1/command/tasks/{task['id']}/{action}",
            json=payload,
            headers=_headers(),
        )
        assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_task_responses_expose_archive_fields_and_version(task_app) -> None:
    task = await _create_task(task_app)
    assert task["archived_at"] is None
    assert task["archive_reason"] is None
    assert task["version"] == 1


def test_task_update_schema_rejects_whitespace_only_title() -> None:
    with pytest.raises(ValidationError):
        TaskUpdate(expected_version=1, title="   ")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expected_version": 1},
        {"expected_version": 1, "unexpected": True},
        {"expected_version": 1, "title": None},
        {"expected_version": 1, "description": None},
        {"expected_version": 1, "priority": None},
        {"expected_version": 1, "status": None},
        {"expected_version": 0, "title": "Invalid version"},
        {"expected_version": True, "title": "Invalid version"},
        {"expected_version": 1, "title": 7},
        {"expected_version": 1, "priority": "urgent"},
        {"expected_version": 1, "status": "archived"},
        {"expected_version": 1, "contact_id": True},
        {"expected_version": 1, "due_at": 1_724_073_300},
        {"expected_version": 1, "due_at": "1724073300"},
        {"expected_version": 1, "due_at": "1724073300.5"},
        {"expected_version": 1, "due_at": "2026-08-18T13:15:00"},
    ],
)
async def test_patch_task_requires_strict_nonempty_versioned_changes(
    task_lifecycle_app, payload
) -> None:
    task = await _create_task(task_lifecycle_app)
    response = await _request(
        task_lifecycle_app,
        "PATCH",
        f"/api/v1/command/tasks/{task['id']}",
        json=payload,
        headers=_headers(),
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_patch_task_is_cas_preserves_explicit_clears_and_increments_repeats(
    task_lifecycle_app, task_api_database
) -> None:
    contact_id = await _create_contact(task_api_database)
    task = await _create_task(
        task_lifecycle_app,
        title="Same title",
        contact_id=contact_id,
        due_at="2026-08-20T17:30:00Z",
    )
    path = f"/api/v1/command/tasks/{task['id']}"

    repeated = await _request(
        task_lifecycle_app,
        "PATCH",
        path,
        json={"expected_version": 1, "title": "Same title"},
        headers=_headers(),
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["version"] == 2

    normalized = await _request(
        task_lifecycle_app,
        "PATCH",
        path,
        json={
            "expected_version": 2,
            "due_at": "2026-08-21T09:30:00-04:00",
        },
        headers=_headers(),
    )
    assert normalized.status_code == 200, normalized.text
    assert normalized.json()["version"] == 3
    assert normalized.json()["due_at"] == "2026-08-21T13:30:00Z"

    cleared = await _request(
        task_lifecycle_app,
        "PATCH",
        path,
        json={"expected_version": 3, "due_at": None, "contact_id": None},
        headers=_headers(),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["version"] == 4
    assert cleared.json()["due_at"] is None
    assert cleared.json()["contact_id"] is None

    missing_contact = await _request(
        task_lifecycle_app,
        "PATCH",
        path,
        json={"expected_version": 4, "contact_id": 999_999},
        headers=_headers(),
    )
    assert missing_contact.status_code == 404

    stale = await _request(
        task_lifecycle_app,
        "PATCH",
        path,
        json={"expected_version": 3, "priority": "high"},
        headers=_headers(),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "task_version_conflict",
        "current_version": 4,
        "current_task": cleared.json(),
    }

    missing = await _request(
        task_lifecycle_app,
        "PATCH",
        "/api/v1/command/tasks/999999",
        json={"expected_version": 1, "priority": "high"},
        headers=_headers(),
    )
    assert missing.status_code == 404

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None
        assert stored.version == 4
        assert stored.title == "Same title"
        assert stored.contact_id is None
        assert stored.due_at is None
        assert await verifier.scalar(
            sa.select(sa.func.count())
            .select_from(CRMActivity)
            .where(CRMActivity.kind == "task_updated")
        ) == 3


@pytest.mark.asyncio
async def test_patch_task_state_precedes_missing_replacement_contact(
    task_lifecycle_app, task_api_database
) -> None:
    task = await _create_task(task_lifecycle_app, title="State precedence")
    path = f"/api/v1/command/tasks/{task['id']}"

    updated = await _request(
        task_lifecycle_app,
        "PATCH",
        path,
        json={"expected_version": 1, "priority": "high"},
        headers=_headers(),
    )
    assert updated.status_code == 200, updated.text

    stale = await _request(
        task_lifecycle_app,
        "PATCH",
        path,
        json={"expected_version": 1, "contact_id": 999_999},
        headers=_headers(),
    )

    archived = await _request(
        task_lifecycle_app,
        "POST",
        f"{path}/archive",
        json=_lifecycle_payload(2),
        headers=_headers(),
    )
    assert archived.status_code == 200, archived.text

    archived_patch = await _request(
        task_lifecycle_app,
        "PATCH",
        path,
        json={"expected_version": 3, "contact_id": 999_999},
        headers=_headers(),
    )
    missing_task = await _request(
        task_lifecycle_app,
        "PATCH",
        "/api/v1/command/tasks/999999",
        json={"expected_version": 1, "contact_id": 999_999},
        headers=_headers(),
    )

    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "task_version_conflict",
        "current_version": 2,
        "current_task": updated.json(),
    }
    assert archived_patch.status_code == 409
    assert archived_patch.json()["detail"] == {
        "code": "task_archived",
        "current_version": 3,
        "current_task": archived.json(),
    }
    assert missing_task.status_code == 404
    assert missing_task.json() == {"detail": "Task not found"}

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None
        assert stored.version == 3
        assert stored.contact_id is None


@pytest.mark.asyncio
async def test_patch_activity_failure_rolls_back_cas_increment(
    task_lifecycle_app, task_api_database
) -> None:
    task = await _create_task(task_lifecycle_app, title="Original")
    _engine, factory = task_api_database
    async with factory() as setup, setup.begin():
        await setup.execute(
            sa.text(
                """
                CREATE FUNCTION reject_task_update_activity() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.kind = 'task_updated' THEN
                        RAISE EXCEPTION 'synthetic task activity failure';
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            )
        )
        await setup.execute(
            sa.text(
                """
                CREATE TRIGGER reject_task_update_activity
                BEFORE INSERT ON crm_activities
                FOR EACH ROW EXECUTE FUNCTION reject_task_update_activity()
                """
            )
        )

    response = await _request(
        task_lifecycle_app,
        "PATCH",
        f"/api/v1/command/tasks/{task['id']}",
        json={"expected_version": 1, "title": "Must roll back"},
        headers=_headers(),
    )
    assert response.status_code == 500

    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None
        assert (stored.title, stored.version) == ("Original", 1)
        assert await verifier.scalar(
            sa.select(sa.func.count())
            .select_from(CRMActivity)
            .where(CRMActivity.kind == "task_updated")
        ) == 0


@pytest.mark.asyncio
async def test_concurrent_patch_compare_and_swap_allows_exactly_one_winner(
    monkeypatch, task_lifecycle_app, task_api_database
) -> None:
    task = await _create_task(task_lifecycle_app, title="Contended")
    path = f"/api/v1/command/tasks/{task['id']}"
    original_update = command_router.crm_task_service.update
    both_ready = asyncio.Event()
    gate_lock = asyncio.Lock()
    ready = 0

    async def update_with_gate(*args, **kwargs):
        nonlocal ready
        async with gate_lock:
            ready += 1
            if ready == 2:
                both_ready.set()
        await asyncio.wait_for(both_ready.wait(), timeout=3)
        return await original_update(*args, **kwargs)

    monkeypatch.setattr(
        command_router.crm_task_service,
        "update",
        update_with_gate,
    )
    responses = await asyncio.wait_for(
        asyncio.gather(
            _request(
                task_lifecycle_app,
                "PATCH",
                path,
                json={"expected_version": 1, "title": "First contender"},
                headers=_headers(),
            ),
            _request(
                task_lifecycle_app,
                "PATCH",
                path,
                json={"expected_version": 1, "priority": "high"},
                headers=_headers(),
            ),
        ),
        timeout=8,
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response for response in responses if response.status_code == 200)
    loser = next(response for response in responses if response.status_code == 409)
    assert winner.json()["version"] == 2
    assert loser.json()["detail"] == {
        "code": "task_version_conflict",
        "current_version": 2,
        "current_task": winner.json(),
    }

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None and stored.version == 2
        assert await verifier.scalar(
            sa.select(sa.func.count())
            .select_from(CRMActivity)
            .where(CRMActivity.kind == "task_updated")
        ) == 1


@pytest.mark.asyncio
async def test_task_link_is_versioned_stale_before_duplicate_and_archived_guarded(
    task_lifecycle_app, task_api_database
) -> None:
    contact_id = await _create_contact(task_api_database)
    task = await _create_task(task_lifecycle_app)
    path = f"/api/v1/command/tasks/{task['id']}/links"

    missing_version = await _request(
        task_lifecycle_app,
        "POST",
        path,
        json={"entity_type": "contact", "entity_id": contact_id},
        headers=_headers(),
    )
    assert missing_version.status_code == 422
    extra = await _request(
        task_lifecycle_app,
        "POST",
        path,
        json={
            "entity_type": "contact",
            "entity_id": contact_id,
            "expected_version": 1,
            "unexpected": True,
        },
        headers=_headers(),
    )
    assert extra.status_code == 422

    created = await _request(
        task_lifecycle_app,
        "POST",
        path,
        json={
            "entity_type": "contact",
            "entity_id": contact_id,
            "expected_version": 1,
        },
        headers=_headers(),
    )
    assert created.status_code == 200, created.text
    assert created.json()["task_version"] == 2

    stale_duplicate = await _request(
        task_lifecycle_app,
        "POST",
        path,
        json={
            "entity_type": "contact",
            "entity_id": contact_id,
            "expected_version": 1,
        },
        headers=_headers(),
    )
    assert stale_duplicate.status_code == 409
    task_at_version_two = {**task, "version": 2}
    assert stale_duplicate.json()["detail"] == {
        "code": "task_version_conflict",
        "current_version": 2,
        "current_task": task_at_version_two,
    }

    duplicate = await _request(
        task_lifecycle_app,
        "POST",
        path,
        json={
            "entity_type": "contact",
            "entity_id": contact_id,
            "expected_version": 2,
        },
        headers=_headers(),
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json() == created.json()

    unsupported = await _request(
        task_lifecycle_app,
        "POST",
        path,
        json={
            "entity_type": "unsupported",
            "entity_id": contact_id,
            "expected_version": 2,
        },
        headers=_headers(),
    )
    assert unsupported.status_code == 422
    missing_record = await _request(
        task_lifecycle_app,
        "POST",
        path,
        json={
            "entity_type": "contact",
            "entity_id": 999_999,
            "expected_version": 2,
        },
        headers=_headers(),
    )
    assert missing_record.status_code == 404

    archived = await _request(
        task_lifecycle_app,
        "POST",
        f"/api/v1/command/tasks/{task['id']}/archive",
        json=_lifecycle_payload(2),
        headers=_headers(),
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["version"] == 3

    archived_duplicate = await _request(
        task_lifecycle_app,
        "POST",
        path,
        json={
            "entity_type": "contact",
            "entity_id": contact_id,
            "expected_version": 3,
        },
        headers=_headers(),
    )
    assert archived_duplicate.status_code == 409
    assert archived_duplicate.json()["detail"] == {
        "code": "task_archived",
        "current_version": 3,
        "current_task": archived.json(),
    }

    listed = await _request(
        task_lifecycle_app,
        "GET",
        path,
        headers=_headers(),
    )
    assert listed.status_code == 200
    assert listed.json() == [{**created.json(), "task_version": 3}]

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None and stored.version == 3
        assert await verifier.scalar(
            sa.select(sa.func.count()).select_from(CRMTaskLink)
        ) == 1


@pytest.mark.asyncio
async def test_task_link_duplicate_replays_after_polymorphic_target_is_removed(
    task_lifecycle_app, task_api_database
) -> None:
    contact_id = await _create_contact(task_api_database)
    task = await _create_task(task_lifecycle_app)
    path = f"/api/v1/command/tasks/{task['id']}/links"
    payload = {
        "entity_type": "contact",
        "entity_id": contact_id,
        "expected_version": 1,
    }

    created = await _request(
        task_lifecycle_app,
        "POST",
        path,
        json=payload,
        headers=_headers(),
    )
    assert created.status_code == 200, created.text
    assert created.json()["task_version"] == 2

    _engine, factory = task_api_database
    async with factory() as remover, remover.begin():
        contact = await remover.get(CRMContact, contact_id)
        assert contact is not None
        await remover.delete(contact)

    duplicate = await _request(
        task_lifecycle_app,
        "POST",
        path,
        json={**payload, "expected_version": 2},
        headers=_headers(),
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json() == {
        **created.json(),
        "display_name": "Removed internal record",
        "task_version": 2,
    }

    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None and stored.version == 2
        assert await verifier.scalar(
            sa.select(sa.func.count()).select_from(CRMTaskLink)
        ) == 1
        assert await verifier.scalar(
            sa.select(sa.func.count())
            .select_from(CRMActivity)
            .where(CRMActivity.kind == "task_linked")
        ) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"entity_type": "", "entity_id": 1, "expected_version": 1},
        {"entity_type": 7, "entity_id": 1, "expected_version": 1},
        {"entity_type": "x" * 51, "entity_id": 1, "expected_version": 1},
        {"entity_type": "contact", "entity_id": 0, "expected_version": 1},
        {"entity_type": "contact", "entity_id": True, "expected_version": 1},
        {"entity_type": "contact", "entity_id": "1", "expected_version": 1},
        {"entity_type": "contact", "entity_id": 1, "expected_version": 0},
        {"entity_type": "contact", "entity_id": 1, "expected_version": True},
        {"entity_type": "contact", "entity_id": 1, "expected_version": "1"},
    ],
)
async def test_task_link_request_bounds_and_types_are_strict(
    task_lifecycle_app, payload
) -> None:
    task = await _create_task(task_lifecycle_app)
    response = await _request(
        task_lifecycle_app,
        "POST",
        f"/api/v1/command/tasks/{task['id']}/links",
        json=payload,
        headers=_headers(),
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_task_link_supports_every_registered_internal_entity_type(
    task_lifecycle_app, task_api_database
) -> None:
    _engine, factory = task_api_database
    async with factory() as setup, setup.begin():
        contact = CRMContact(
            first_name="Supported",
            last_name="Contact",
            email=f"supported-{uuid4()}@example.test",
        )
        agreement = CRMAgreement(title="Supported Agreement")
        listing = CRMListingRecord(address="101 Supported Way")
        opportunity = CRMOpportunity(name="Supported Opportunity")
        setup.add_all((contact, agreement, listing, opportunity))
        await setup.flush()
        targets = (
            ("contact", contact.id, "Supported Contact"),
            ("agreement", agreement.id, "Supported Agreement"),
            ("listing", listing.id, "101 Supported Way"),
            ("opportunity", opportunity.id, "Supported Opportunity"),
        )

    task = await _create_task(task_lifecycle_app)
    path = f"/api/v1/command/tasks/{task['id']}/links"
    for expected_version, (entity_type, entity_id, display_name) in enumerate(
        targets,
        start=1,
    ):
        response = await _request(
            task_lifecycle_app,
            "POST",
            path,
            json={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "expected_version": expected_version,
            },
            headers=_headers(),
        )
        assert response.status_code == 200, response.text
        assert response.json()["display_name"] == display_name
        assert response.json()["task_version"] == expected_version + 1


@pytest.mark.asyncio
async def test_concurrent_distinct_links_lock_parent_version_before_insert(
    monkeypatch, task_lifecycle_app, task_api_database
) -> None:
    first_contact_id = await _create_contact(task_api_database)
    second_contact_id = await _create_contact(task_api_database)
    task = await _create_task(task_lifecycle_app)
    path = f"/api/v1/command/tasks/{task['id']}/links"
    original_add_link = command_router.crm_task_service.add_link
    both_ready = asyncio.Event()
    gate_lock = asyncio.Lock()
    ready = 0

    async def add_link_with_gate(*args, **kwargs):
        nonlocal ready
        async with gate_lock:
            ready += 1
            if ready == 2:
                both_ready.set()
        await asyncio.wait_for(both_ready.wait(), timeout=3)
        return await original_add_link(*args, **kwargs)

    monkeypatch.setattr(
        command_router.crm_task_service,
        "add_link",
        add_link_with_gate,
    )
    responses = await asyncio.wait_for(
        asyncio.gather(
            *(
                _request(
                    task_lifecycle_app,
                    "POST",
                    path,
                    json={
                        "entity_type": "contact",
                        "entity_id": contact_id,
                        "expected_version": 1,
                    },
                    headers=_headers(),
                )
                for contact_id in (first_contact_id, second_contact_id)
            )
        ),
        timeout=8,
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response for response in responses if response.status_code == 200)
    loser = next(response for response in responses if response.status_code == 409)
    assert winner.json()["task_version"] == 2
    current_task = {**task, "version": 2}
    assert loser.json()["detail"] == {
        "code": "task_version_conflict",
        "current_version": 2,
        "current_task": current_task,
    }

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None and stored.version == 2
        assert await verifier.scalar(
            sa.select(sa.func.count()).select_from(CRMTaskLink)
        ) == 1


@pytest.mark.asyncio
async def test_task_link_insert_failure_rolls_back_parent_version(
    task_lifecycle_app, task_api_database
) -> None:
    contact_id = await _create_contact(task_api_database)
    task = await _create_task(task_lifecycle_app)
    _engine, factory = task_api_database
    async with factory() as setup, setup.begin():
        await setup.execute(
            sa.text(
                """
                CREATE FUNCTION reject_task_link() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'synthetic task link failure';
                END;
                $$
                """
            )
        )
        await setup.execute(
            sa.text(
                """
                CREATE TRIGGER reject_task_link
                BEFORE INSERT ON crm_task_links
                FOR EACH ROW EXECUTE FUNCTION reject_task_link()
                """
            )
        )

    response = await _request(
        task_lifecycle_app,
        "POST",
        f"/api/v1/command/tasks/{task['id']}/links",
        json={
            "entity_type": "contact",
            "entity_id": contact_id,
            "expected_version": 1,
        },
        headers=_headers(),
    )
    assert response.status_code == 500

    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None and stored.version == 1
        assert await verifier.scalar(
            sa.select(sa.func.count()).select_from(CRMTaskLink)
        ) == 0


@pytest.mark.asyncio
async def test_archive_restore_replay_conflicts_and_preserve_workflow_and_links(
    task_lifecycle_app, task_api_database
) -> None:
    contact_id = await _create_contact(task_api_database)
    task = await _create_task(task_lifecycle_app)
    task_path = f"/api/v1/command/tasks/{task['id']}"

    updated = await _request(
        task_lifecycle_app,
        "PATCH",
        task_path,
        json={"expected_version": 1, "status": "in_progress"},
        headers=_headers(),
    )
    assert updated.status_code == 200, updated.text
    linked = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/links",
        json={
            "entity_type": "contact",
            "entity_id": contact_id,
            "expected_version": 2,
        },
        headers=_headers(),
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["task_version"] == 3

    request_id = uuid4()
    archive_payload = _lifecycle_payload(
        3,
        request_id=request_id,
        reason="No longer needed",
    )
    archive_path = f"{task_path}/archive"
    first = await _request(
        task_lifecycle_app,
        "POST",
        archive_path,
        json=archive_payload,
        headers=_headers(subject="17"),
    )
    replay = await _request(
        task_lifecycle_app,
        "POST",
        archive_path,
        json=archive_payload,
        headers=_headers(subject="17"),
    )
    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["archived_at"] is not None
    assert first.json()["archive_reason"] == "No longer needed"
    assert first.json()["status"] == "in_progress"
    assert first.json()["version"] == 4

    changed_replay = await _request(
        task_lifecycle_app,
        "POST",
        archive_path,
        json={**archive_payload, "reason": "Changed"},
        headers=_headers(subject="17"),
    )
    assert changed_replay.status_code == 409
    assert changed_replay.json()["detail"] == {
        "code": "task_request_mismatch",
        "current_version": 4,
        "current_task": first.json(),
    }

    other_actor = await _request(
        task_lifecycle_app,
        "POST",
        archive_path,
        json=archive_payload,
        headers=_headers(subject="18"),
    )
    assert other_actor.status_code == 409
    assert other_actor.json()["detail"] == {
        "code": "task_request_mismatch",
        "current_version": 4,
        "current_task": first.json(),
    }

    stale = await _request(
        task_lifecycle_app,
        "POST",
        archive_path,
        json=_lifecycle_payload(3),
        headers=_headers(),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "task_version_conflict",
        "current_version": 4,
        "current_task": first.json(),
    }

    archived_patch = await _request(
        task_lifecycle_app,
        "PATCH",
        task_path,
        json={"expected_version": 4, "priority": "high"},
        headers=_headers(),
    )
    assert archived_patch.status_code == 409
    assert archived_patch.json()["detail"]["code"] == "task_archived"

    restored = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/restore",
        json=_lifecycle_payload(4, reason="Needed again"),
        headers=_headers(),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived_at"] is None
    assert restored.json()["archive_reason"] is None
    assert restored.json()["status"] == "in_progress"
    assert restored.json()["version"] == 5

    stale_restore_noop = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/restore",
        json=_lifecycle_payload(4, reason="Already restored"),
        headers=_headers(),
    )
    assert stale_restore_noop.status_code == 409
    assert stale_restore_noop.json()["detail"] == {
        "code": "task_version_conflict",
        "current_version": 5,
        "current_task": restored.json(),
    }

    replay_after_restore = await _request(
        task_lifecycle_app,
        "POST",
        archive_path,
        json=archive_payload,
        headers=_headers(subject="17"),
    )
    assert replay_after_restore.status_code == 200
    assert replay_after_restore.json() == first.json()

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None
        assert stored.archived_at is None
        assert stored.status == "in_progress"
        assert stored.version == 5
        assert await verifier.scalar(
            sa.select(sa.func.count())
            .select_from(CRMTaskLink)
            .where(CRMTaskLink.task_id == task["id"])
        ) == 1


@pytest.mark.asyncio
async def test_lifecycle_request_identity_is_scoped_by_task_and_action(
    task_lifecycle_app, task_api_database
) -> None:
    first_task = await _create_task(task_lifecycle_app, title="First scope")
    second_task = await _create_task(task_lifecycle_app, title="Second scope")
    shared_request_id = uuid4()

    first_archive = await _request(
        task_lifecycle_app,
        "POST",
        f"/api/v1/command/tasks/{first_task['id']}/archive",
        json=_lifecycle_payload(1, request_id=shared_request_id),
        headers=_headers(),
    )
    second_archive = await _request(
        task_lifecycle_app,
        "POST",
        f"/api/v1/command/tasks/{second_task['id']}/archive",
        json=_lifecycle_payload(1, request_id=shared_request_id),
        headers=_headers(),
    )
    first_restore = await _request(
        task_lifecycle_app,
        "POST",
        f"/api/v1/command/tasks/{first_task['id']}/restore",
        json=_lifecycle_payload(2, request_id=shared_request_id),
        headers=_headers(),
    )

    assert first_archive.status_code == 200, first_archive.text
    assert second_archive.status_code == 200, second_archive.text
    assert first_restore.status_code == 200, first_restore.text
    assert first_archive.json()["version"] == 2
    assert second_archive.json()["version"] == 2
    assert first_restore.json()["version"] == 3

    _engine, factory = task_api_database
    async with factory() as verifier:
        events = (
            await verifier.scalars(
                sa.select(CRMRecordLifecycleEvent)
                .where(CRMRecordLifecycleEvent.request_id == shared_request_id)
                .order_by(
                    CRMRecordLifecycleEvent.entity_id,
                    CRMRecordLifecycleEvent.action,
                )
            )
        ).all()
        assert {
            (event.entity_id, event.action) for event in events
        } == {
            (first_task["id"], "archive"),
            (first_task["id"], "restore"),
            (second_task["id"], "archive"),
        }


@pytest.mark.asyncio
async def test_restore_exact_replay_and_request_mismatch_are_symmetric(
    task_lifecycle_app
) -> None:
    task = await _create_task(task_lifecycle_app)
    task_path = f"/api/v1/command/tasks/{task['id']}"
    archived = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/archive",
        json=_lifecycle_payload(1),
        headers=_headers(),
    )
    assert archived.status_code == 200, archived.text

    request_id = uuid4()
    payload = _lifecycle_payload(
        2,
        request_id=request_id,
        reason="Return to active work",
    )
    first = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/restore",
        json=payload,
        headers=_headers(subject="17"),
    )
    replay = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/restore",
        json=payload,
        headers=_headers(subject="17"),
    )
    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["version"] == 3
    assert first.json()["archived_at"] is None

    changed_payload = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/restore",
        json={**payload, "reason": "Different reason"},
        headers=_headers(subject="17"),
    )
    changed_actor = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/restore",
        json=payload,
        headers=_headers(subject="18"),
    )
    for mismatch in (changed_payload, changed_actor):
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"] == {
            "code": "task_request_mismatch",
            "current_version": 3,
            "current_task": first.json(),
        }


@pytest.mark.asyncio
async def test_same_state_lifecycle_requests_persist_durable_historical_noops(
    task_lifecycle_app, task_api_database
) -> None:
    task = await _create_task(task_lifecycle_app)
    task_path = f"/api/v1/command/tasks/{task['id']}"

    restore_request_id = uuid4()
    restore_noop_payload = _lifecycle_payload(
        1,
        request_id=restore_request_id,
        reason="Already active",
    )
    restore_noop = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/restore",
        json=restore_noop_payload,
        headers=_headers(),
    )
    assert restore_noop.status_code == 200, restore_noop.text
    assert restore_noop.json()["version"] == 1
    assert restore_noop.json()["archived_at"] is None

    archived = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/archive",
        json=_lifecycle_payload(1),
        headers=_headers(),
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["version"] == 2

    restore_noop_after_archive = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/restore",
        json=restore_noop_payload,
        headers=_headers(),
    )
    assert restore_noop_after_archive.status_code == 200
    assert restore_noop_after_archive.json() == restore_noop.json()

    archive_noop_request_id = uuid4()
    archive_noop_payload = _lifecycle_payload(
        2,
        request_id=archive_noop_request_id,
        reason="Still archived",
    )
    archive_noop = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/archive",
        json=archive_noop_payload,
        headers=_headers(),
    )
    assert archive_noop.status_code == 200
    assert archive_noop.json()["version"] == 2
    assert archive_noop.json()["archive_reason"] == archived.json()["archive_reason"]

    restored = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/restore",
        json=_lifecycle_payload(2),
        headers=_headers(),
    )
    assert restored.status_code == 200
    assert restored.json()["version"] == 3
    assert restored.json()["archived_at"] is None

    archive_noop_after_restore = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/archive",
        json=archive_noop_payload,
        headers=_headers(),
    )
    assert archive_noop_after_restore.status_code == 200
    assert archive_noop_after_restore.json() == archive_noop.json()

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None
        assert stored.version == 3
        assert stored.archived_at is None
        restore_event = await verifier.scalar(
            sa.select(CRMRecordLifecycleEvent).where(
                CRMRecordLifecycleEvent.entity_type == "task",
                CRMRecordLifecycleEvent.entity_id == task["id"],
                CRMRecordLifecycleEvent.action == "restore",
                CRMRecordLifecycleEvent.request_id == restore_request_id,
            )
        )
        archive_event = await verifier.scalar(
            sa.select(CRMRecordLifecycleEvent).where(
                CRMRecordLifecycleEvent.entity_type == "task",
                CRMRecordLifecycleEvent.entity_id == task["id"],
                CRMRecordLifecycleEvent.action == "archive",
                CRMRecordLifecycleEvent.request_id == archive_noop_request_id,
            )
        )
        assert restore_event is not None and archive_event is not None
        assert json.loads(restore_event.result_json)["changed"] is False
        assert json.loads(archive_event.result_json)["changed"] is False


@pytest.mark.asyncio
async def test_concurrent_identical_archive_request_is_one_transition_and_one_replay(
    monkeypatch, task_lifecycle_app, task_api_database
) -> None:
    task = await _create_task(task_lifecycle_app)
    payload = _lifecycle_payload(1)
    path = f"/api/v1/command/tasks/{task['id']}/archive"
    original_archive = command_router.crm_task_service.archive
    both_ready = asyncio.Event()
    gate_lock = asyncio.Lock()
    ready = 0

    async def archive_with_gate(*args, **kwargs):
        nonlocal ready
        async with gate_lock:
            ready += 1
            if ready == 2:
                both_ready.set()
        await asyncio.wait_for(both_ready.wait(), timeout=3)
        return await original_archive(*args, **kwargs)

    monkeypatch.setattr(
        command_router.crm_task_service,
        "archive",
        archive_with_gate,
    )
    responses = await asyncio.wait_for(
        asyncio.gather(
            *(
                _request(
                    task_lifecycle_app,
                    "POST",
                    path,
                    json=payload,
                    headers=_headers(),
                )
                for _ in range(2)
            )
        ),
        timeout=8,
    )
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["version"] == 2

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None and stored.version == 2
        assert await verifier.scalar(
            sa.select(sa.func.count())
            .select_from(CRMRecordLifecycleEvent)
            .where(
                CRMRecordLifecycleEvent.entity_type == "task",
                CRMRecordLifecycleEvent.entity_id == task["id"],
                CRMRecordLifecycleEvent.action == "archive",
            )
        ) == 1


@pytest.mark.asyncio
async def test_concurrent_identical_restore_request_is_one_transition_and_one_replay(
    monkeypatch, task_lifecycle_app, task_api_database
) -> None:
    task = await _create_task(task_lifecycle_app)
    task_path = f"/api/v1/command/tasks/{task['id']}"
    archived = await _request(
        task_lifecycle_app,
        "POST",
        f"{task_path}/archive",
        json=_lifecycle_payload(1),
        headers=_headers(),
    )
    assert archived.status_code == 200, archived.text

    payload = _lifecycle_payload(2)
    path = f"{task_path}/restore"
    original_restore = command_router.crm_task_service.restore
    both_ready = asyncio.Event()
    gate_lock = asyncio.Lock()
    ready = 0

    async def restore_with_gate(*args, **kwargs):
        nonlocal ready
        async with gate_lock:
            ready += 1
            if ready == 2:
                both_ready.set()
        await asyncio.wait_for(both_ready.wait(), timeout=3)
        return await original_restore(*args, **kwargs)

    monkeypatch.setattr(
        command_router.crm_task_service,
        "restore",
        restore_with_gate,
    )
    responses = await asyncio.wait_for(
        asyncio.gather(
            *(
                _request(
                    task_lifecycle_app,
                    "POST",
                    path,
                    json=payload,
                    headers=_headers(),
                )
                for _ in range(2)
            )
        ),
        timeout=8,
    )
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["version"] == 3

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None
        assert stored.archived_at is None
        assert stored.version == 3
        assert await verifier.scalar(
            sa.select(sa.func.count())
            .select_from(CRMRecordLifecycleEvent)
            .where(
                CRMRecordLifecycleEvent.entity_type == "task",
                CRMRecordLifecycleEvent.entity_id == task["id"],
                CRMRecordLifecycleEvent.action == "restore",
            )
        ) == 1


@pytest.mark.asyncio
async def test_task_visibility_composes_archive_status_and_due_filters(
    task_lifecycle_app, task_api_database
) -> None:
    due_values = [
        datetime(2026, 8, day, 12, tzinfo=UTC)
        for day in range(1, 6)
    ]
    _engine, factory = task_api_database
    async with factory() as setup, setup.begin():
        rows = [
            CRMTask(title="Active open", status="open", due_at=due_values[0]),
            CRMTask(
                title="Active in progress",
                status="in_progress",
                due_at=due_values[1],
            ),
            CRMTask(
                title="Nonarchived completed",
                status="completed",
                due_at=due_values[2],
            ),
            CRMTask(
                title="Archived open",
                status="open",
                due_at=due_values[3],
                archived_at=datetime(2026, 8, 18, 12, tzinfo=UTC),
                archived_by_type="admin",
                archived_by_id="17",
                archive_reason="Archived fixture",
            ),
            CRMTask(
                title="Archived completed",
                status="completed",
                due_at=due_values[4],
                archived_at=datetime(2026, 8, 18, 12, tzinfo=UTC),
                archived_by_type="admin",
                archived_by_id="17",
                archive_reason="Archived fixture",
            ),
        ]
        setup.add_all(rows)
        await setup.flush()

    async def titles(query: str = "") -> list[str]:
        response = await _request(
            task_lifecycle_app,
            "GET",
            f"/api/v1/command/tasks{query}",
            headers=_headers(),
        )
        assert response.status_code == 200, response.text
        return [row["title"] for row in response.json()]

    assert await titles() == ["Active open", "Active in progress"]
    assert await titles("?visibility=active&status=completed") == [
        "Nonarchived completed"
    ]
    assert await titles("?visibility=archived") == [
        "Archived open",
        "Archived completed",
    ]
    assert await titles("?visibility=archived&status=completed") == [
        "Archived completed"
    ]
    assert await titles("?visibility=all&status=completed") == [
        "Nonarchived completed",
        "Archived completed",
    ]
    assert await titles(
        "?visibility=all&due_before=2026-08-04T12:00:00Z"
    ) == [
        "Active open",
        "Active in progress",
        "Nonarchived completed",
        "Archived open",
    ]
    assert await titles(
        "?visibility=all&due_after=2026-08-03T12:00:00Z"
    ) == [
        "Nonarchived completed",
        "Archived open",
        "Archived completed",
    ]
    assert await titles(
        "?visibility=archived&status=completed"
        "&due_after=2026-08-04T12:00:00Z"
    ) == ["Archived completed"]
    invalid = await _request(
        task_lifecycle_app,
        "GET",
        "/api/v1/command/tasks?visibility=unknown",
        headers=_headers(),
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_archive_outer_request_failure_rolls_back_task_and_event(
    monkeypatch, task_lifecycle_app, task_api_database
) -> None:
    task = await _create_task(task_lifecycle_app)
    original_archive = command_router.crm_task_service.archive

    async def archive_then_fail(*args, **kwargs):
        await original_archive(*args, **kwargs)
        raise RuntimeError("synthetic response failure")

    monkeypatch.setattr(command_router.crm_task_service, "archive", archive_then_fail)
    response = await _request(
        task_lifecycle_app,
        "POST",
        f"/api/v1/command/tasks/{task['id']}/archive",
        json=_lifecycle_payload(1),
        headers=_headers(),
    )
    assert response.status_code == 500

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None
        assert stored.archived_at is None
        assert stored.version == 1
        assert await verifier.scalar(
            sa.select(sa.func.count())
            .select_from(CRMRecordLifecycleEvent)
            .where(
                CRMRecordLifecycleEvent.entity_type == "task",
                CRMRecordLifecycleEvent.entity_id == task["id"],
                CRMRecordLifecycleEvent.action == "archive",
            )
        ) == 0


@pytest.mark.asyncio
async def test_restore_outer_request_failure_rolls_back_task_and_event(
    monkeypatch, task_lifecycle_app, task_api_database
) -> None:
    task = await _create_task(task_lifecycle_app)
    archived = await _request(
        task_lifecycle_app,
        "POST",
        f"/api/v1/command/tasks/{task['id']}/archive",
        json=_lifecycle_payload(1),
        headers=_headers(),
    )
    assert archived.status_code == 200, archived.text
    original_restore = command_router.crm_task_service.restore

    async def restore_then_fail(*args, **kwargs):
        await original_restore(*args, **kwargs)
        raise RuntimeError("synthetic response failure")

    monkeypatch.setattr(
        command_router.crm_task_service,
        "restore",
        restore_then_fail,
    )
    response = await _request(
        task_lifecycle_app,
        "POST",
        f"/api/v1/command/tasks/{task['id']}/restore",
        json=_lifecycle_payload(2),
        headers=_headers(),
    )
    assert response.status_code == 500

    _engine, factory = task_api_database
    async with factory() as verifier:
        stored = await verifier.get(CRMTask, task["id"])
        assert stored is not None
        assert stored.archived_at is not None
        assert stored.version == 2
        assert await verifier.scalar(
            sa.select(sa.func.count())
            .select_from(CRMRecordLifecycleEvent)
            .where(
                CRMRecordLifecycleEvent.entity_type == "task",
                CRMRecordLifecycleEvent.entity_id == task["id"],
                CRMRecordLifecycleEvent.action == "restore",
            )
        ) == 0


@pytest.mark.parametrize("method_name", ["update", "add_link", "archive", "restore"])
def test_task_mutation_service_never_owns_outer_commit_or_rollback(
    method_name: str,
) -> None:
    source = textwrap.dedent(
        inspect.getsource(getattr(command_router.crm_task_service, method_name))
    )
    tree = ast.parse(source)
    transaction_calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"commit", "rollback"}
    ]
    assert transaction_calls == []
