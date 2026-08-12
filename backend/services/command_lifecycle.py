"""Validated lifecycle rules for internal agreement tracking."""

_ALLOWED = {
    "draft": {"in_review", "voided", "expired"},
    "in_review": {"ready", "voided", "expired"},
    "ready": {"shared", "voided", "expired"},
    "shared": {"viewed", "completed", "voided", "expired"},
    "viewed": {"completed", "voided", "expired"},
    "completed": set(),
    "voided": set(),
    "expired": set(),
}


def ensure_agreement_transition(current: str, requested: str) -> None:
    if requested not in _ALLOWED.get(current, set()):
        raise ValueError(f"Agreement transition from {current} to {requested} is not allowed")
