"""Canonical CRM task workflow and archive projections."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from sqlalchemy import and_
from sqlalchemy.sql.elements import ColumnElement

from models.command import CRMTask

TaskWorkflowStatus = Literal["open", "in_progress", "completed", "cancelled"]
TaskGroup = Literal["active", "completed", "cancelled", "archived"]

ACTIVE_TASK_STATUSES: tuple[TaskWorkflowStatus, ...] = ("open", "in_progress")
TASK_WORKFLOW_STATUSES: tuple[TaskWorkflowStatus, ...] = (
    *ACTIVE_TASK_STATUSES,
    "completed",
    "cancelled",
)


class TaskProjectionError(ValueError):
    """Stored or requested task state cannot be projected safely."""


def _workflow_status(status: str) -> TaskWorkflowStatus:
    if status not in TASK_WORKFLOW_STATUSES:
        raise TaskProjectionError("task status is invalid")
    return cast(TaskWorkflowStatus, status)


def task_group(*, status: str, archived_at: datetime | None) -> TaskGroup:
    """Group a task with archive visibility taking precedence over workflow."""
    if archived_at is not None:
        return "archived"
    workflow_status = _workflow_status(status)
    if workflow_status in ACTIVE_TASK_STATUSES:
        return "active"
    return workflow_status


def nonarchived_task_clause() -> ColumnElement[bool]:
    """Select mutable tasks without imposing a workflow group."""
    return CRMTask.archived_at.is_(None)


def active_task_clause() -> ColumnElement[bool]:
    """Select the only workflow states that are currently actionable."""
    return and_(
        nonarchived_task_clause(),
        CRMTask.status.in_(ACTIVE_TASK_STATUSES),
    )


def archived_task_clause() -> ColumnElement[bool]:
    """Select archived mutable task rows regardless of preserved workflow."""
    return CRMTask.archived_at.is_not(None)


def workflow_status_task_clause(status: str) -> ColumnElement[bool]:
    """Select one known nonarchived workflow status."""
    workflow_status = _workflow_status(status)
    return and_(
        nonarchived_task_clause(),
        CRMTask.status == workflow_status,
    )


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "TASK_WORKFLOW_STATUSES",
    "TaskGroup",
    "TaskProjectionError",
    "TaskWorkflowStatus",
    "active_task_clause",
    "archived_task_clause",
    "nonarchived_task_clause",
    "task_group",
    "workflow_status_task_clause",
]
