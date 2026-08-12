"""Task-specific audit helpers for the internal Command workspace."""


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
