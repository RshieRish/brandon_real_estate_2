"""Task-specific helpers for the internal Command workspace."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid5


ARCHIVE_TASK_SOURCE_ID = "command_archive_bundle"
_ARCHIVE_TASK_NAMESPACE = UUID("322ab65e-3f4f-5935-94ed-5565b0ac00b2")


_LABELS = {
    "title": "title",
    "description": "details",
    "priority": "priority",
    "due_at": "due date",
    "status": "status",
}


def task_activity_summary(changes: dict[str, object]) -> str:
    """Make a concise immutable activity summary from persisted task fields."""
    labels = [_LABELS[field] for field in _LABELS if field in changes]
    if not labels:
        return "Updated task"
    if len(labels) == 1:
        return f"Updated task {labels[0]}"
    if len(labels) == 2:
        return f"Updated task {labels[0]} and {labels[1]}"
    return f"Updated task {', '.join(labels[:-1])}, and {labels[-1]}"


def archive_task_source_key(row: object, ordinal: int) -> str:
    """Build a stable UUID from the archive source, complete row, and ordinal."""
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("archive task ordinal is invalid")
    model_dump = getattr(row, "model_dump", None)
    if not callable(model_dump):
        raise TypeError("archive task row is invalid")
    payload = model_dump()
    due_at = payload.get("due_at")
    if isinstance(due_at, datetime):
        if due_at.tzinfo is None or due_at.utcoffset() is None:
            raise ValueError("archive task due_at must include a UTC offset")
        payload["due_at"] = due_at.astimezone(UTC).isoformat().replace(
            "+00:00", "Z"
        )
    canonical = json.dumps(
        {
            "ordinal": ordinal,
            "row": payload,
            "source_id": ARCHIVE_TASK_SOURCE_ID,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return str(uuid5(_ARCHIVE_TASK_NAMESPACE, canonical))
