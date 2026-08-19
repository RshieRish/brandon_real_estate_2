"""Single transactional authority for creating mutable CRM tasks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMActivity, CRMContact, CRMTask
from models.crm_task_lifecycle import (
    CRMRecordLifecycleEvent,
    CRMTaskCreationRequest,
    CRMTaskSource,
)


ActorType = Literal["admin", "sydney", "system"]
SourceType = Literal[
    "command_ui", "archive_import", "gmail_message", "sydney_chat"
]
Priority = Literal["low", "normal", "high"]
WorkflowStatus = Literal["open", "in_progress", "completed", "cancelled"]

_ACTOR_TYPES = frozenset(("admin", "sydney", "system"))
_SOURCE_TYPES = frozenset(
    ("command_ui", "archive_import", "gmail_message", "sydney_chat")
)
_PRIORITIES = frozenset(("low", "normal", "high"))
_WORKFLOW_STATUSES = frozenset(("open", "in_progress", "completed", "cancelled"))
_LIFECYCLE_NAMESPACE = UUID("6ffce621-a586-5f4d-aacc-74984798dd5e")


class CRMTaskCreationError(Exception):
    code = "task_creation_error"


class TaskCommandValidationError(CRMTaskCreationError):
    code = "task_request_invalid"


class TaskContactNotFound(CRMTaskCreationError):
    code = "task_contact_not_found"


class TaskIdempotencyConflict(CRMTaskCreationError):
    code = "task_idempotency_mismatch"


class TaskCreationStateError(CRMTaskCreationError):
    code = "task_creation_state_invalid"


class TaskSourceConflict(CRMTaskCreationError):
    code = "task_source_conflict"


@dataclass(frozen=True, slots=True)
class TaskActor:
    type: ActorType
    id: str


@dataclass(frozen=True, slots=True)
class TaskSource:
    type: SourceType
    id: str
    key: str


@dataclass(frozen=True, slots=True)
class CreateTaskCommand:
    title: str
    description: str
    priority: Priority
    due_at: datetime | None
    contact_id: int | None
    actor: TaskActor
    source: TaskSource
    idempotency_scope: str
    idempotency_key: str
    client_timezone: str
    status: WorkflowStatus = "open"


@dataclass(frozen=True, slots=True)
class CreateTaskResult:
    task: CRMTask
    replayed: bool
    request_id: UUID
    request_hash: str


def _bounded_text(value: object, *, name: str, minimum: int, maximum: int) -> str:
    if type(value) is not str or not minimum <= len(value) <= maximum:
        raise TaskCommandValidationError(f"{name} is invalid")
    if minimum and not value.strip():
        raise TaskCommandValidationError(f"{name} is invalid")
    return value


def _utc_rfc3339(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise TaskCommandValidationError("due_at must include a UTC offset")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        ".000000+00:00", "Z"
    ).replace("+00:00", "Z")


def _validate(command: CreateTaskCommand) -> None:
    if not isinstance(command, CreateTaskCommand):
        raise TaskCommandValidationError("task command is invalid")
    _bounded_text(command.title, name="title", minimum=1, maximum=255)
    _bounded_text(command.description, name="description", minimum=0, maximum=65_536)
    if command.priority not in _PRIORITIES:
        raise TaskCommandValidationError("priority is invalid")
    if command.status not in _WORKFLOW_STATUSES:
        raise TaskCommandValidationError("status is invalid")
    _utc_rfc3339(command.due_at)
    if command.contact_id is not None and (
        type(command.contact_id) is not int or command.contact_id <= 0
    ):
        raise TaskCommandValidationError("contact_id is invalid")
    if not isinstance(command.actor, TaskActor) or command.actor.type not in _ACTOR_TYPES:
        raise TaskCommandValidationError("actor type is invalid")
    _bounded_text(command.actor.id, name="actor id", minimum=1, maximum=128)
    if not isinstance(command.source, TaskSource) or command.source.type not in _SOURCE_TYPES:
        raise TaskCommandValidationError("source type is invalid")
    _bounded_text(command.source.id, name="source id", minimum=1, maximum=255)
    _bounded_text(command.source.key, name="source key", minimum=1, maximum=128)
    _bounded_text(
        command.idempotency_scope,
        name="idempotency scope",
        minimum=1,
        maximum=64,
    )
    _bounded_text(
        command.idempotency_key,
        name="idempotency key",
        minimum=1,
        maximum=128,
    )
    timezone_name = _bounded_text(
        command.client_timezone,
        name="client timezone",
        minimum=1,
        maximum=64,
    )
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise TaskCommandValidationError("client timezone is invalid") from None


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_task_command_json(command: CreateTaskCommand) -> str:
    """Return the full, stable authority/source-aware idempotency payload."""
    _validate(command)
    return _canonical_json(
        {
            "actor": {"id": command.actor.id, "type": command.actor.type},
            "client_timezone": command.client_timezone,
            "contact_id": command.contact_id,
            "description": command.description,
            "due_at": _utc_rfc3339(command.due_at),
            "idempotency_key": command.idempotency_key,
            "idempotency_scope": command.idempotency_scope,
            "priority": command.priority,
            "source": {
                "id": command.source.id,
                "key": command.source.key,
                "type": command.source.type,
            },
            "status": command.status,
            "title": command.title,
        }
    )


def _request_id(command: CreateTaskCommand) -> UUID:
    return uuid5(
        _LIFECYCLE_NAMESPACE,
        f"{command.idempotency_scope}\x00{command.idempotency_key}",
    )


def _task_result_json(task: CRMTask) -> str:
    return _canonical_json(
        {
            "contact_id": task.contact_id,
            "description": task.description,
            "due_at": _utc_rfc3339(task.due_at),
            "id": task.id,
            "priority": task.priority,
            "status": task.status,
            "title": task.title,
            "version": task.version,
        }
    )


def _sanitized_activity_summary(title: str) -> str:
    visible = re.sub(r"\s+", " ", title).strip()
    return f"Created task: {visible}"[:500]


def _constraint_name(exc: IntegrityError) -> str | None:
    candidate: BaseException | None = exc.orig
    visited: set[int] = set()
    while candidate is not None and id(candidate) not in visited:
        visited.add(id(candidate))
        diagnostic = getattr(candidate, "diag", None)
        constraint = getattr(diagnostic, "constraint_name", None)
        if isinstance(constraint, str):
            return constraint
        constraint = getattr(candidate, "constraint_name", None)
        if isinstance(constraint, str):
            return constraint
        candidate = candidate.__cause__ or candidate.__context__
    match = re.search(r'unique constraint "([A-Za-z0-9_]+)"', str(exc.orig))
    return match.group(1) if match else None


class CRMTaskService:
    async def create(
        self, db: AsyncSession, command: CreateTaskCommand
    ) -> CreateTaskResult:
        payload_json = canonical_task_command_json(command)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        request_id = _request_id(command)
        due_at = (
            command.due_at.astimezone(UTC) if command.due_at is not None else None
        )

        claim_values = {
            "scope": command.idempotency_scope,
            "idempotency_key": command.idempotency_key,
            "payload_hash": payload_hash,
            "actor_type": command.actor.type,
            "actor_id": command.actor.id,
            "source_type": command.source.type,
            "source_id": command.source.id,
            "state": "applying",
            "metadata_json": _canonical_json(
                {"client_timezone": command.client_timezone}
            ),
        }
        dialect_name = db.get_bind().dialect.name
        if dialect_name == "postgresql":
            claim_insert = (
                pg_insert(CRMTaskCreationRequest)
                .values(**claim_values)
                .on_conflict_do_nothing(
                    constraint="uq_crm_task_creation_request_scope_key"
                )
                .returning(CRMTaskCreationRequest.id)
            )
        elif dialect_name == "sqlite":
            # The application runs PostgreSQL. This branch keeps the repository's
            # established SQLite route fixtures behaviorally representative.
            claim_insert = (
                sqlite_insert(CRMTaskCreationRequest)
                .values(**claim_values)
                .on_conflict_do_nothing(
                    index_elements=("scope", "idempotency_key")
                )
                .returning(CRMTaskCreationRequest.id)
            )
        else:
            raise TaskCreationStateError("Task database dialect is unsupported")

        try:
            async with db.begin_nested():
                if command.contact_id is not None and await db.get(
                    CRMContact, command.contact_id
                ) is None:
                    raise TaskContactNotFound("Task contact not found")

                claim_id = await db.scalar(claim_insert)
                if claim_id is None:
                    claim = await db.scalar(
                        select(CRMTaskCreationRequest)
                        .where(
                            CRMTaskCreationRequest.scope
                            == command.idempotency_scope,
                            CRMTaskCreationRequest.idempotency_key
                            == command.idempotency_key,
                        )
                        .with_for_update()
                    )
                    if claim is None:
                        raise TaskCreationStateError(
                            "Task creation request is unavailable"
                        )
                    if claim.payload_hash != payload_hash:
                        raise TaskIdempotencyConflict(
                            "Idempotency key was already used with a different task request"
                        )
                    if claim.state != "applied" or claim.task_id is None:
                        raise TaskCreationStateError(
                            "Task creation request is incomplete"
                        )
                    task = await db.get(CRMTask, claim.task_id)
                    if task is None or claim.result_version is None:
                        raise TaskCreationStateError(
                            "Task creation result is unavailable"
                        )
                    return CreateTaskResult(
                        task=task,
                        replayed=True,
                        request_id=request_id,
                        request_hash=payload_hash,
                    )

                claim = await db.get(CRMTaskCreationRequest, claim_id)
                if claim is None:
                    raise TaskCreationStateError("Task creation claim is unavailable")
                task = CRMTask(
                    title=command.title,
                    description=command.description,
                    priority=command.priority,
                    status=command.status,
                    due_at=due_at,
                    contact_id=command.contact_id,
                )
                db.add(task)
                await db.flush()
                db.add(
                    CRMTaskSource(
                        task_id=task.id,
                        source_type=command.source.type,
                        source_id=command.source.id,
                        source_key=command.source.key,
                    )
                )
                if task.contact_id is not None:
                    db.add(
                        CRMActivity(
                            contact_id=task.contact_id,
                            kind="task_created",
                            summary=_sanitized_activity_summary(task.title),
                            metadata_json=_canonical_json(
                                {
                                    "actor_id": command.actor.id,
                                    "actor_type": command.actor.type,
                                    "source_id": command.source.id,
                                    "source_type": command.source.type,
                                }
                            ),
                        )
                    )
                db.add(
                    CRMRecordLifecycleEvent(
                        entity_type="task",
                        entity_id=task.id,
                        action="create",
                        request_id=request_id,
                        request_hash=payload_hash,
                        actor_type=command.actor.type,
                        actor_id=command.actor.id,
                        source_type=command.source.type,
                        source_id=command.source.id,
                        result_json=_task_result_json(task),
                        metadata_json=_canonical_json(
                            {
                                "client_timezone": command.client_timezone,
                                "source_key": command.source.key,
                            }
                        ),
                    )
                )
                claim.state = "applied"
                claim.task_id = task.id
                claim.result_version = task.version
                await db.flush()
                return CreateTaskResult(
                    task=task,
                    replayed=False,
                    request_id=request_id,
                    request_hash=payload_hash,
                )
        except IntegrityError as exc:
            if _constraint_name(exc) == "uq_crm_task_source_identity":
                raise TaskSourceConflict(
                    "Task source identity is already linked"
                ) from None
            raise


crm_task_service = CRMTaskService()
