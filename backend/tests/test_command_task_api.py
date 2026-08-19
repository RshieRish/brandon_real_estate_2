from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI
from jose import jwt

import database
from config import settings
from database import get_db
from models.command import CRMActivity, CRMTask
from models.crm_task_lifecycle import (
    CRMRecordLifecycleEvent,
    CRMTaskCreationRequest,
    CRMTaskSource,
)
from routers import command as command_router
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


def _headers(key: UUID | str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_token()}"}
    if key is not None:
        headers["X-Idempotency-Key"] = str(key)
    return headers


async def _request(app: FastAPI, method: str, path: str, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        return await client.request(method, path, **kwargs)


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
async def test_archive_import_keeps_same_title_rows_and_replays_by_stable_ordinal(
    task_app, task_api_database
) -> None:
    payload = {
        "tasks": [
            {"title": "Same title", "description": "First source row"},
            {
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
        assert [task.status for task in tasks] == ["open", "completed"]
        assert len({source.source_key for source in sources}) == 2
        assert all(UUID(source.source_key).version == 5 for source in sources)


def test_command_router_does_not_replace_get_db_dependency() -> None:
    route = next(
        route
        for route in command_router.router.routes
        if getattr(route, "path", None) == "/tasks" and getattr(route, "methods", None) == {"POST"}
    )
    assert any(dependency.call is get_db for dependency in route.dependant.dependencies)
