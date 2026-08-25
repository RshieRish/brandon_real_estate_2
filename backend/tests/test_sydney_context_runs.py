from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("side_effect_class", "state", "has_result", "expected"),
    [
        ("read_only", "started", False, "repeat_read"),
        ("read_only", "failed", False, "repeat_read"),
        ("read_only", "not_delivered", False, "repeat_read"),
        ("read_only", "succeeded", True, "restore_result"),
        ("idempotent_write", "succeeded", True, "restore_result"),
        ("idempotent_write", "not_delivered", False, "retry_not_delivered"),
        ("idempotent_write", "delivery_uncertain", False, "block_uncertain"),
        ("idempotent_write", "started", False, "block_uncertain"),
        ("non_idempotent_write", "succeeded", True, "restore_result"),
        ("non_idempotent_write", "not_delivered", False, "block_uncertain"),
        ("non_idempotent_write", "delivery_uncertain", False, "block_uncertain"),
        ("non_idempotent_write", "failed", False, "block_uncertain"),
    ],
)
def test_tool_replay_decision_never_reexecutes_completed_or_uncertain_writes(
    side_effect_class: str,
    state: str,
    has_result: bool,
    expected: str,
) -> None:
    from services.sydney_context_service import tool_replay_decision

    assert (
        tool_replay_decision(
            side_effect_class=side_effect_class,
            state=state,
            has_result=has_result,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        ("queued", "running", True),
        ("queued", "waiting_retry", True),
        ("running", "waiting_retry", True),
        ("running", "succeeded", True),
        ("running", "blocked_side_effect", True),
        ("waiting_retry", "running", True),
        ("succeeded", "running", False),
        ("terminal_failure", "queued", False),
        ("blocked_side_effect", "succeeded", False),
        ("queued", "succeeded", False),
    ],
)
def test_run_state_transition_contract(
    current: str, target: str, allowed: bool
) -> None:
    from services.sydney_context_service import is_run_transition_allowed

    assert is_run_transition_allowed(current, target) is allowed
