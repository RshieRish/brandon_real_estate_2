from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

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
        ("blocked_side_effect", "terminal_failure", True),
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


@pytest.mark.asyncio
async def test_running_lease_renews_only_for_its_current_owner() -> None:
    from schemas.sydney_context import ContextRunLeaseRenewRequest
    from services.sydney_context_service import renew_run_lease

    now = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)
    run = SimpleNamespace(
        id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        identity_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        platform_message_id="message-1",
        inbound_event_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        session_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        logical_conversation_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        state="running",
        attempt_count=1,
        lease_owner="hermes:attempt-1",
        lease_expires_at=now + timedelta(seconds=30),
        next_attempt_at=None,
        terminal_deadline_at=now + timedelta(hours=1),
        provider_category=None,
        error_code=None,
        parsed_retry_delay_seconds=None,
        final_response_event_id=None,
        updated_at=now,
    )
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(one=lambda: run)),
        flush=AsyncMock(),
    )

    result = await renew_run_lease(
        db,
        ContextRunLeaseRenewRequest(
            run_id=run.id,
            lease_owner="hermes:attempt-1",
        ),
        now=now,
        lease_seconds=120,
    )

    assert result.lease_expires_at == now + timedelta(seconds=120)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_run_lease_cannot_be_revived_by_its_old_owner() -> None:
    from schemas.sydney_context import ContextRunLeaseRenewRequest
    from services.sydney_context_service import ContextRunConflict, renew_run_lease

    now = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)
    run = SimpleNamespace(
        state="running",
        lease_owner="hermes:attempt-1",
        lease_expires_at=now,
    )
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(one=lambda: run)),
        flush=AsyncMock(),
    )

    with pytest.raises(ContextRunConflict, match="context_run_lease_expired"):
        await renew_run_lease(
            db,
            ContextRunLeaseRenewRequest(
                run_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                lease_owner="hermes:attempt-1",
            ),
            now=now,
            lease_seconds=120,
        )


@pytest.mark.asyncio
async def test_claim_finalizes_expired_runs_before_fifo_selection() -> None:
    from schemas.sydney_context import ContextRunClaimRequest
    from services.sydney_context_service import claim_runs

    db = SimpleNamespace(
        execute=AsyncMock(),
        scalars=AsyncMock(return_value=SimpleNamespace(all=list)),
        flush=AsyncMock(),
    )
    await claim_runs(
        db,
        ContextRunClaimRequest(lease_owner="atlas-fixture"),
        now=datetime(2026, 8, 25, 19, 0, tzinfo=UTC),
    )

    expiry_statement = db.execute.await_args.args[0]
    sql = str(expiry_statement)
    assert sql.startswith("UPDATE agent_run_jobs SET")
    assert "terminal_deadline_at <=" in sql
    assert "state IN" in sql
    assert "terminal_failure" in {
        getattr(value, "value", value) for value in expiry_statement._values.values()
    }


def _run_update_fixture(now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        identity_id=uuid4(),
        platform_message_id="message-update",
        inbound_event_id=uuid4(),
        session_id=uuid4(),
        logical_conversation_id=uuid4(),
        state="running",
        attempt_count=1,
        lease_owner="hermes:stable-process",
        lease_expires_at=now + timedelta(minutes=2),
        next_attempt_at=None,
        terminal_deadline_at=now + timedelta(hours=1),
        provider_category=None,
        error_code=None,
        parsed_retry_delay_seconds=None,
        final_response_event_id=None,
        updated_at=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (
        (
            {"lease_expires_at": timedelta(seconds=0)},
            "context_run_lease_expired",
        ),
        (
            {"terminal_deadline_at": timedelta(seconds=0)},
            "context_run_terminal_deadline_exceeded",
        ),
        (
            {
                "state": "queued",
                "lease_owner": None,
                "lease_expires_at": None,
            },
            "context_run_not_running",
        ),
    ),
)
async def test_run_state_update_requires_a_live_running_lease(
    mutation: dict[str, object],
    expected_error: str,
) -> None:
    from schemas.sydney_context import ContextRunUpdateRequest
    from services.sydney_context_service import ContextRunConflict, update_run_state

    now = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)
    run = _run_update_fixture(now)
    for name, value in mutation.items():
        if isinstance(value, timedelta):
            value = now + value
        setattr(run, name, value)
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(one=lambda: run)),
        flush=AsyncMock(),
    )
    request = ContextRunUpdateRequest(
        run_id=run.id,
        state="waiting_retry",
        lease_owner="hermes:stable-process",
        next_attempt_at=now + timedelta(minutes=5),
        provider_category="rate_limit",
        error_code="provider_429",
    )

    with pytest.raises(ContextRunConflict, match=f"^{expected_error}$"):
        await update_run_state(db, request, now=now)

    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_blocked_run_can_reach_terminal_resolution_without_a_lease() -> None:
    from schemas.sydney_context import ContextRunUpdateRequest
    from services.sydney_context_service import update_run_state

    now = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)
    run = _run_update_fixture(now)
    run.state = "blocked_side_effect"
    run.lease_owner = None
    run.lease_expires_at = None
    run.provider_category = "delivery_uncertain"
    run.error_code = "final_delivery_uncertain"
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(one=lambda: run)),
        flush=AsyncMock(),
    )

    summary = await update_run_state(
        db,
        ContextRunUpdateRequest(
            run_id=run.id,
            state="terminal_failure",
            provider_category="manual_resolution",
            error_code="final_delivery_not_sent",
        ),
        now=now + timedelta(hours=2),
    )

    assert summary.state == "terminal_failure"
    assert summary.provider_category == "manual_resolution"
    assert summary.error_code == "final_delivery_not_sent"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_exact_terminal_run_update_replay_is_idempotent_without_a_live_lease() -> (
    None
):
    from schemas.sydney_context import ContextRunUpdateRequest
    from services.sydney_context_service import update_run_state

    now = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)
    run = _run_update_fixture(now)
    final_event_id = uuid4()
    run.state = "succeeded"
    run.lease_owner = None
    run.lease_expires_at = None
    run.final_response_event_id = final_event_id
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(one=lambda: run)),
        scalar=AsyncMock(return_value=SimpleNamespace(id=final_event_id)),
        flush=AsyncMock(),
    )

    summary = await update_run_state(
        db,
        ContextRunUpdateRequest(
            run_id=run.id,
            state="succeeded",
            lease_owner="hermes:stable-process",
            final_response_event_id=final_event_id,
        ),
        now=now,
    )

    assert summary.state == "succeeded"
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_fractional_retry_update_replay_matches_postgres_numeric_precision() -> (
    None
):
    from decimal import Decimal

    from schemas.sydney_context import ContextRunUpdateRequest
    from services.sydney_context_service import update_run_state

    now = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)
    run = _run_update_fixture(now)
    run.state = "waiting_retry"
    run.lease_owner = None
    run.lease_expires_at = None
    run.next_attempt_at = now + timedelta(seconds=46.8)
    run.provider_category = "rate_limit"
    run.error_code = "provider_429"
    run.parsed_retry_delay_seconds = Decimal("46.800")
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(one=lambda: run)),
        flush=AsyncMock(),
    )

    summary = await update_run_state(
        db,
        ContextRunUpdateRequest(
            run_id=run.id,
            state="waiting_retry",
            lease_owner="hermes:stable-process",
            next_attempt_at=run.next_attempt_at,
            provider_category="rate_limit",
            error_code="provider_429",
            parsed_retry_delay_seconds=46.8,
        ),
        now=now,
    )

    assert summary.state == "waiting_retry"
    db.flush.assert_not_awaited()
