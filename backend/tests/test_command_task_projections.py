"""One task projection contract across Command read surfaces."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base, get_db
from middleware.auth import require_admin
from models.command import CRMContact, CRMTask
from routers import command as command_router
from services.crm_task_projection import (
    TaskProjectionError,
    active_task_clause,
    task_group,
    workflow_status_task_clause,
)

NOW = datetime(2026, 8, 18, 14, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "archived", "group"),
    [
        ("open", False, "active"),
        ("in_progress", False, "active"),
        ("completed", False, "completed"),
        ("cancelled", False, "cancelled"),
        ("open", True, "archived"),
        ("completed", True, "archived"),
    ],
)
def test_task_group_contract(status: str, archived: bool, group: str) -> None:
    assert task_group(status=status, archived_at=NOW if archived else None) == group


def test_task_group_rejects_unknown_nonarchived_workflow_status_stably() -> None:
    with pytest.raises(TaskProjectionError, match=r"^task status is invalid$"):
        task_group(status="private-invalid-status", archived_at=None)

    # Archive visibility wins even if historical workflow data is no longer known.
    assert task_group(status="private-invalid-status", archived_at=NOW) == "archived"


def _postgresql_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_shared_sql_clauses_encode_archive_and_workflow_dimensions() -> None:
    active_sql = _postgresql_sql(select(CRMTask.id).where(active_task_clause()))
    assert "crm_tasks.archived_at IS NULL" in active_sql
    assert "crm_tasks.status IN ('open', 'in_progress')" in active_sql

    completed_sql = _postgresql_sql(
        select(CRMTask.id).where(workflow_status_task_clause("completed"))
    )
    assert "crm_tasks.archived_at IS NULL" in completed_sql
    assert "crm_tasks.status = 'completed'" in completed_sql

    with pytest.raises(TaskProjectionError, match=r"^task status is invalid$"):
        workflow_status_task_clause("private-invalid-status")


def test_task_list_rejects_unknown_workflow_status_at_the_http_boundary() -> None:
    app = FastAPI()
    app.include_router(command_router.router)

    async def fake_admin():
        return object()

    async def fake_db():
        yield object()

    app.dependency_overrides[require_admin] = fake_admin
    app.dependency_overrides[get_db] = fake_db
    response = TestClient(app, raise_server_exceptions=False).get(
        "/tasks", params={"status": "private-invalid-status"}
    )

    assert response.status_code == 422


@pytest_asyncio.fixture()
async def projection_db(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'command-task-projections.sqlite'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_projection_matrix(db: AsyncSession) -> dict[str, CRMTask]:
    contact = CRMContact(first_name="Projection", last_name="Matrix", stage="lead")
    db.add(contact)
    await db.flush()
    rows = {
        "open": CRMTask(
            contact_id=contact.id,
            title="Open task",
            status="open",
            due_at=NOW - timedelta(days=1),
        ),
        "in_progress": CRMTask(
            contact_id=contact.id,
            title="In-progress task",
            status="in_progress",
            due_at=NOW,
        ),
        "completed": CRMTask(
            contact_id=contact.id,
            title="Completed task",
            status="completed",
            due_at=NOW,
        ),
        "cancelled": CRMTask(
            contact_id=contact.id,
            title="Cancelled task",
            status="cancelled",
            due_at=NOW,
        ),
        "archived_open": CRMTask(
            contact_id=contact.id,
            title="Archived open task",
            status="open",
            due_at=NOW - timedelta(days=2),
            archived_at=NOW,
        ),
        "archived_completed": CRMTask(
            contact_id=contact.id,
            title="Archived completed task",
            status="completed",
            due_at=NOW,
            archived_at=NOW,
        ),
    }
    db.add_all(rows.values())
    await db.flush()
    return rows


@pytest.mark.asyncio
async def test_command_reads_share_the_active_task_projection(
    projection_db: AsyncSession,
) -> None:
    rows = await _seed_projection_matrix(projection_db)
    active_ids = {rows["open"].id, rows["in_progress"].id}

    overview = await command_router.overview(db=projection_db)
    assert overview.open_tasks == 2

    briefing = await command_router.ai_briefing(db=projection_db)
    assert briefing == {
        "summary": "2 open tasks across 1 contacts and 0 opportunities.",
        "source": "internal-crm",
        "requires_review": True,
    }

    report = await command_router.reports_summary(db=projection_db)
    assert report["open_tasks"] == 2

    details = await command_router.report_details("open_tasks", db=projection_db)
    assert {row["id"] for row in details["rows"]} == active_ids

    default_tasks = await command_router.tasks(db=projection_db)
    assert {row.id for row in default_tasks} == active_ids

    due_before = await command_router.tasks(
        due_before=NOW - timedelta(hours=12),
        db=projection_db,
    )
    assert [row.id for row in due_before] == [rows["open"].id]

    due_after = await command_router.tasks(
        due_after=NOW - timedelta(hours=12),
        db=projection_db,
    )
    assert [row.id for row in due_after] == [rows["in_progress"].id]

    in_progress = await command_router.tasks(status="in_progress", db=projection_db)
    assert [row.id for row in in_progress] == [rows["in_progress"].id]

    completed = await command_router.tasks(status="completed", db=projection_db)
    assert [row.id for row in completed] == [rows["completed"].id]

    cancelled = await command_router.tasks(status="cancelled", db=projection_db)
    assert [row.id for row in cancelled] == [rows["cancelled"].id]
