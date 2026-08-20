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

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMActivity, CRMContact, CRMTask, CRMTaskLink
from models.crm_task_lifecycle import (
    CRMRecordLifecycleEvent,
    CRMTaskCreationRequest,
    CRMTaskSource,
)
from schemas.command import POSTGRES_INTEGER_MAX
from services.command_task_links import task_link_display_name, task_link_model
from services.command_tasks import task_activity_summary


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


class TaskNotFound(CRMTaskCreationError):
    code = "task_not_found"


class TaskLinkedRecordNotFound(CRMTaskCreationError):
    code = "task_linked_record_not_found"


class TaskStateConflict(CRMTaskCreationError):
    code = "task_state_conflict"

    def __init__(self, message: str, *, current_task: dict[str, object]):
        super().__init__(message)
        self.current_task = current_task
        self.current_version = int(current_task["version"])


class TaskVersionConflict(TaskStateConflict):
    code = "task_version_conflict"


class TaskArchived(TaskStateConflict):
    code = "task_archived"


class TaskRequestMismatch(TaskStateConflict):
    code = "task_request_mismatch"


class TaskLifecycleStateError(TaskStateConflict):
    code = "task_lifecycle_state_invalid"


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


@dataclass(frozen=True, slots=True)
class TaskMutationResult:
    task: CRMTask


@dataclass(frozen=True, slots=True)
class TaskLinkResult:
    link: CRMTaskLink
    display_name: str
    task_version: int


@dataclass(frozen=True, slots=True)
class TaskLifecycleResult:
    task: dict[str, object]
    replayed: bool
    changed: bool


def _bounded_text(value: object, *, name: str, minimum: int, maximum: int) -> str:
    if type(value) is not str or not minimum <= len(value) <= maximum:
        raise TaskCommandValidationError(f"{name} is invalid")
    if minimum and not value.strip():
        raise TaskCommandValidationError(f"{name} is invalid")
    return value


def _utc_rfc3339(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = _utc_datetime(value)
    assert normalized is not None
    return normalized.isoformat(timespec="microseconds").replace(
        ".000000+00:00", "Z"
    ).replace("+00:00", "Z")


def _utc_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TaskCommandValidationError("due_at must be a datetime")
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            raise TaskCommandValidationError("due_at must include a UTC offset")
        return value.astimezone(UTC)
    except TaskCommandValidationError:
        raise
    except Exception:
        raise TaskCommandValidationError("due_at cannot be converted to UTC") from None


def _supported_text(value: object, supported: frozenset[str], *, name: str) -> str:
    if type(value) is not str or value not in supported:
        raise TaskCommandValidationError(f"{name} is invalid")
    return value


def _positive_integer(value: object, *, name: str) -> int:
    if (
        type(value) is not int
        or value <= 0
        or value > POSTGRES_INTEGER_MAX
    ):
        raise TaskCommandValidationError(f"{name} is invalid")
    return value


def _validate_actor(actor: object) -> TaskActor:
    if not isinstance(actor, TaskActor):
        raise TaskCommandValidationError("actor type is invalid")
    _supported_text(actor.type, _ACTOR_TYPES, name="actor type")
    _bounded_text(actor.id, name="actor id", minimum=1, maximum=128)
    return actor


def _validate_source(source: object) -> TaskSource:
    if not isinstance(source, TaskSource):
        raise TaskCommandValidationError("source type is invalid")
    _supported_text(source.type, _SOURCE_TYPES, name="source type")
    _bounded_text(source.id, name="source id", minimum=1, maximum=255)
    _bounded_text(source.key, name="source key", minimum=1, maximum=128)
    return source


def _validate(command: CreateTaskCommand) -> None:
    if not isinstance(command, CreateTaskCommand):
        raise TaskCommandValidationError("task command is invalid")
    _bounded_text(command.title, name="title", minimum=1, maximum=255)
    _bounded_text(command.description, name="description", minimum=0, maximum=65_536)
    _supported_text(command.priority, _PRIORITIES, name="priority")
    _supported_text(command.status, _WORKFLOW_STATUSES, name="status")
    _utc_rfc3339(command.due_at)
    if command.contact_id is not None:
        _positive_integer(command.contact_id, name="contact_id")
    _validate_actor(command.actor)
    _validate_source(command.source)
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


def task_snapshot(task: CRMTask) -> dict[str, object]:
    """Return the stable public task representation used in conflict/replay data."""

    return {
        "archive_reason": task.archive_reason,
        "archived_at": _utc_rfc3339(task.archived_at),
        "contact_id": task.contact_id,
        "description": task.description,
        "due_at": _utc_rfc3339(task.due_at),
        "id": task.id,
        "priority": task.priority,
        "status": task.status,
        "title": task.title,
        "version": task.version,
    }


def _task_lifecycle_payload(
    *,
    action: Literal["archive", "restore"],
    task_id: int,
    request_id: UUID,
    expected_version: int,
    reason: str | None,
    actor: TaskActor,
    source: TaskSource,
) -> dict[str, object]:
    return {
        "action": action,
        "actor": {"id": actor.id, "type": actor.type},
        "expected_version": expected_version,
        "reason": reason,
        "request_id": str(request_id),
        "source": {
            "id": source.id,
            "key": source.key,
            "type": source.type,
        },
        "task_id": task_id,
    }


def canonical_task_lifecycle_json(
    *,
    action: Literal["archive", "restore"],
    task_id: int,
    request_id: UUID,
    expected_version: int,
    reason: str | None,
    actor: TaskActor,
    source: TaskSource,
) -> str:
    if action not in ("archive", "restore"):
        raise TaskCommandValidationError("task lifecycle action is invalid")
    _positive_integer(task_id, name="task_id")
    if not isinstance(request_id, UUID):
        raise TaskCommandValidationError("request_id is invalid")
    _positive_integer(expected_version, name="expected_version")
    if reason is not None:
        _bounded_text(reason, name="reason", minimum=0, maximum=500)
    _validate_actor(actor)
    _validate_source(source)
    return _canonical_json(
        _task_lifecycle_payload(
            action=action,
            task_id=task_id,
            request_id=request_id,
            expected_version=expected_version,
            reason=reason,
            actor=actor,
            source=source,
        )
    )


def _lifecycle_result_json(task: CRMTask, *, changed: bool) -> str:
    return _canonical_json({**task_snapshot(task), "changed": changed})


def _stored_lifecycle_result(
    event: CRMRecordLifecycleEvent,
    *,
    current_task: CRMTask,
) -> dict[str, object]:
    try:
        payload = json.loads(event.result_json)
    except (TypeError, ValueError):
        raise TaskLifecycleStateError(
            "Task lifecycle result is invalid",
            current_task=task_snapshot(current_task),
        ) from None
    if type(payload) is not dict or type(payload.get("changed")) is not bool:
        raise TaskLifecycleStateError(
            "Task lifecycle result is invalid",
            current_task=task_snapshot(current_task),
        )
    required_fields = {
        "archive_reason",
        "archived_at",
        "contact_id",
        "description",
        "due_at",
        "id",
        "priority",
        "status",
        "title",
        "version",
    }
    if not required_fields.issubset(payload):
        raise TaskLifecycleStateError(
            "Task lifecycle result is invalid",
            current_task=task_snapshot(current_task),
        )
    return payload


def _validated_update_changes(changes: object) -> dict[str, object]:
    if type(changes) is not dict or not changes:
        raise TaskCommandValidationError("task changes are invalid")
    supported = {
        "contact_id",
        "description",
        "due_at",
        "priority",
        "status",
        "title",
    }
    if not set(changes).issubset(supported):
        raise TaskCommandValidationError("task changes are invalid")

    validated = dict(changes)
    if "status" in validated:
        _supported_text(validated["status"], _WORKFLOW_STATUSES, name="status")
    if "title" in validated:
        _bounded_text(validated["title"], name="title", minimum=1, maximum=255)
    if "description" in validated:
        _bounded_text(
            validated["description"],
            name="description",
            minimum=0,
            maximum=65_536,
        )
    if "priority" in validated:
        _supported_text(validated["priority"], _PRIORITIES, name="priority")
    if "due_at" in validated:
        validated["due_at"] = _utc_datetime(validated["due_at"])
    if "contact_id" in validated and validated["contact_id"] is not None:
        _positive_integer(validated["contact_id"], name="contact_id")
    return validated


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
    async def update(
        self,
        db: AsyncSession,
        *,
        task_id: int,
        expected_version: int,
        changes: dict[str, object],
        actor: TaskActor,
    ) -> TaskMutationResult:
        _positive_integer(task_id, name="task_id")
        _positive_integer(expected_version, name="expected_version")
        _validate_actor(actor)
        validated_changes = _validated_update_changes(changes)

        async with db.begin_nested():
            contact_id = validated_changes.get("contact_id")
            cas = update(CRMTask).where(
                CRMTask.id == task_id,
                CRMTask.version == expected_version,
                CRMTask.version < POSTGRES_INTEGER_MAX,
                CRMTask.archived_at.is_(None),
            )
            if contact_id is not None:
                cas = cas.where(
                    select(CRMContact.id)
                    .where(CRMContact.id == contact_id)
                    .exists()
                )

            task = await db.scalar(
                cas
                .values(
                    **validated_changes,
                    version=CRMTask.version + 1,
                )
                .returning(CRMTask)
                .execution_options(populate_existing=True)
            )
            if task is None:
                current_task = await db.scalar(
                    select(CRMTask)
                    .where(CRMTask.id == task_id)
                    .execution_options(populate_existing=True)
                )
                if current_task is None:
                    raise TaskNotFound("Task not found")
                snapshot = task_snapshot(current_task)
                if current_task.archived_at is not None:
                    raise TaskArchived(
                        "Task is archived",
                        current_task=snapshot,
                    )
                if current_task.version != expected_version:
                    raise TaskVersionConflict(
                        "Task version is stale",
                        current_task=snapshot,
                    )
                if current_task.version >= POSTGRES_INTEGER_MAX:
                    raise TaskVersionConflict(
                        "Task version cannot be incremented",
                        current_task=snapshot,
                    )
                if contact_id is not None:
                    raise TaskContactNotFound("Task contact not found")
                raise TaskVersionConflict(
                    "Task version changed during the update",
                    current_task=snapshot,
                )

            db.add(
                CRMActivity(
                    contact_id=task.contact_id,
                    kind="task_updated",
                    summary=task_activity_summary(validated_changes),
                    metadata_json=_canonical_json(
                        {
                            "actor_id": actor.id,
                            "actor_type": actor.type,
                        }
                    ),
                )
            )
            await db.flush()
            return TaskMutationResult(task=task)

    async def add_link(
        self,
        db: AsyncSession,
        *,
        task_id: int,
        entity_type: str,
        entity_id: int,
        expected_version: int,
        actor: TaskActor,
    ) -> TaskLinkResult:
        _positive_integer(task_id, name="task_id")
        _bounded_text(
            entity_type,
            name="entity_type",
            minimum=1,
            maximum=50,
        )
        _positive_integer(entity_id, name="entity_id")
        _positive_integer(expected_version, name="expected_version")
        _validate_actor(actor)

        async with db.begin_nested():
            task = await db.scalar(
                select(CRMTask)
                .where(CRMTask.id == task_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if task is None:
                raise TaskNotFound("Task not found")
            snapshot = task_snapshot(task)
            if task.archived_at is not None:
                raise TaskArchived(
                    "Task is archived",
                    current_task=snapshot,
                )
            if task.version != expected_version:
                raise TaskVersionConflict(
                    "Task version is stale",
                    current_task=snapshot,
                )

            existing = await db.scalar(
                select(CRMTaskLink).where(
                    CRMTaskLink.task_id == task_id,
                    CRMTaskLink.entity_type == entity_type,
                    CRMTaskLink.entity_id == entity_id,
                )
            )
            if existing is not None:
                entity_model = task_link_model(entity_type)
                record = (
                    await db.get(entity_model, entity_id)
                    if entity_model is not None
                    else None
                )
                return TaskLinkResult(
                    link=existing,
                    display_name=(
                        task_link_display_name(entity_type, record)
                        if record is not None
                        else "Removed internal record"
                    ),
                    task_version=task.version,
                )

            entity_model = task_link_model(entity_type)
            if entity_model is None:
                raise TaskCommandValidationError(
                    "Task-link entity type is unsupported"
                )
            record = await db.get(entity_model, entity_id)
            if record is None:
                raise TaskLinkedRecordNotFound(
                    "Linked internal record not found"
                )
            display_name = task_link_display_name(entity_type, record)
            if task.version >= POSTGRES_INTEGER_MAX:
                raise TaskVersionConflict(
                    "Task version cannot be incremented",
                    current_task=snapshot,
                )
            link = CRMTaskLink(
                task_id=task_id,
                entity_type=entity_type,
                entity_id=entity_id,
            )
            db.add(link)
            task.version += 1
            db.add(
                CRMActivity(
                    contact_id=task.contact_id,
                    kind="task_linked",
                    summary=f"Linked task to {entity_type}",
                    metadata_json=_canonical_json(
                        {
                            "actor_id": actor.id,
                            "actor_type": actor.type,
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                        }
                    ),
                )
            )
            await db.flush()
            return TaskLinkResult(
                link=link,
                display_name=display_name,
                task_version=task.version,
            )

    async def archive(
        self,
        db: AsyncSession,
        *,
        task_id: int,
        request_id: UUID,
        expected_version: int,
        reason: str | None,
        actor: TaskActor,
        source: TaskSource,
    ) -> TaskLifecycleResult:
        return await self._change_lifecycle(
            db,
            action="archive",
            task_id=task_id,
            request_id=request_id,
            expected_version=expected_version,
            reason=reason,
            actor=actor,
            source=source,
        )

    async def restore(
        self,
        db: AsyncSession,
        *,
        task_id: int,
        request_id: UUID,
        expected_version: int,
        reason: str | None,
        actor: TaskActor,
        source: TaskSource,
    ) -> TaskLifecycleResult:
        return await self._change_lifecycle(
            db,
            action="restore",
            task_id=task_id,
            request_id=request_id,
            expected_version=expected_version,
            reason=reason,
            actor=actor,
            source=source,
        )

    async def _change_lifecycle(
        self,
        db: AsyncSession,
        *,
        action: Literal["archive", "restore"],
        task_id: int,
        request_id: UUID,
        expected_version: int,
        reason: str | None,
        actor: TaskActor,
        source: TaskSource,
    ) -> TaskLifecycleResult:
        canonical_request = canonical_task_lifecycle_json(
            action=action,
            task_id=task_id,
            request_id=request_id,
            expected_version=expected_version,
            reason=reason,
            actor=actor,
            source=source,
        )
        request_hash = hashlib.sha256(
            canonical_request.encode("utf-8")
        ).hexdigest()

        async with db.begin_nested():
            task = await db.scalar(
                select(CRMTask)
                .where(CRMTask.id == task_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if task is None:
                raise TaskNotFound("Task not found")

            event = await db.scalar(
                select(CRMRecordLifecycleEvent)
                .where(
                    CRMRecordLifecycleEvent.entity_type == "task",
                    CRMRecordLifecycleEvent.entity_id == task_id,
                    CRMRecordLifecycleEvent.action == action,
                    CRMRecordLifecycleEvent.request_id == request_id,
                )
                .with_for_update()
            )
            if event is not None:
                if event.request_hash != request_hash:
                    raise TaskRequestMismatch(
                        "Task lifecycle request does not match its prior use",
                        current_task=task_snapshot(task),
                    )
                stored = _stored_lifecycle_result(
                    event,
                    current_task=task,
                )
                changed = bool(stored.pop("changed"))
                return TaskLifecycleResult(
                    task=stored,
                    replayed=True,
                    changed=changed,
                )

            if task.version != expected_version:
                raise TaskVersionConflict(
                    "Task version is stale",
                    current_task=task_snapshot(task),
                )

            changed = (
                task.archived_at is None
                if action == "archive"
                else task.archived_at is not None
            )
            if changed and task.version >= POSTGRES_INTEGER_MAX:
                raise TaskVersionConflict(
                    "Task version cannot be incremented",
                    current_task=task_snapshot(task),
                )
            if changed and action == "archive":
                task.archived_at = datetime.now(UTC)
                task.archived_by_type = actor.type
                task.archived_by_id = actor.id
                task.archive_reason = reason
                task.version += 1
            elif changed:
                task.archived_at = None
                task.archived_by_type = None
                task.archived_by_id = None
                task.archive_reason = None
                task.version += 1

            result_json = _lifecycle_result_json(task, changed=changed)
            db.add(
                CRMRecordLifecycleEvent(
                    entity_type="task",
                    entity_id=task.id,
                    action=action,
                    request_id=request_id,
                    request_hash=request_hash,
                    actor_type=actor.type,
                    actor_id=actor.id,
                    source_type=source.type,
                    source_id=source.id,
                    result_json=result_json,
                    metadata_json=_canonical_json(
                        {
                            "changed": changed,
                            "reason": reason,
                            "source_key": source.key,
                        }
                    ),
                )
            )
            await db.flush()
            snapshot = json.loads(result_json)
            snapshot.pop("changed")
            return TaskLifecycleResult(
                task=snapshot,
                replayed=False,
                changed=changed,
            )

    async def create(
        self, db: AsyncSession, command: CreateTaskCommand
    ) -> CreateTaskResult:
        payload_json = canonical_task_command_json(command)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        request_id = _request_id(command)
        due_at = _utc_datetime(command.due_at)

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
