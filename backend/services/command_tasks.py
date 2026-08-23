"""Task-specific helpers for the internal Command workspace."""

import json
from uuid import UUID, uuid5


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


def archive_task_source_key(source_id: str, source_row_id: str) -> str:
    """Build a stable UUID solely from immutable archive identities."""
    if (
        type(source_id) is not str
        or not source_id.strip()
        or not 1 <= len(source_id) <= 255
    ):
        raise ValueError("archive source_id is invalid")
    if (
        type(source_row_id) is not str
        or not source_row_id.strip()
        or not 1 <= len(source_row_id) <= 128
    ):
        raise ValueError("archive source_row_id is invalid")
    canonical = json.dumps(
        {
            "source_id": source_id,
            "source_row_id": source_row_id,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return str(uuid5(_ARCHIVE_TASK_NAMESPACE, canonical))
