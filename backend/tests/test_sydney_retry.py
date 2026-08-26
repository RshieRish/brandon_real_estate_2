from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[2] / "hermes" / "overlay"
sys.path.insert(0, str(OVERLAY))

from sydney_retry import (  # noqa: E402
    AUTOMATIC_CONTINUATION_MESSAGE,
    PromptBudgetGuard,
    RollingInputBudget,
    classify_retry,
    next_retry,
    parse_retry_delay,
    plan_retry,
    tool_replay_decision,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
        retry_info: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.headers = headers or {}
        self.retry_info = retry_info


class APIConnectionError(Exception):
    pass


def test_structured_retry_info_wins_over_headers_and_text() -> None:
    error = ProviderError(
        "retry in 2s",
        status_code=429,
        headers={"Retry-After": "3"},
        retry_info={"retry_delay": {"seconds": 47, "nanos": 500_000_000}},
    )
    assert parse_retry_delay(error, NOW) == timedelta(seconds=47.5)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "47"}, timedelta(seconds=47)),
        (
            {"Retry-After": format_datetime(NOW + timedelta(seconds=47), usegmt=True)},
            timedelta(seconds=47),
        ),
        (
            {"X-RateLimit-Reset": str(int((NOW + timedelta(seconds=52)).timestamp()))},
            timedelta(seconds=52),
        ),
    ],
)
def test_retry_headers_support_delta_date_and_absolute_reset(
    headers: dict[str, str], expected: timedelta
) -> None:
    assert parse_retry_delay(ProviderError("limited", headers=headers), NOW) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Quota exhausted, retry in 47s.", timedelta(seconds=47)),
        ("Please retry after 47 seconds", timedelta(seconds=47)),
        ("retry in 1250ms", timedelta(milliseconds=1250)),
        ("try again in 2 minutes", timedelta(minutes=2)),
        ("temporarily unavailable", None),
    ],
)
def test_text_retry_delay_parsing(message: str, expected: timedelta | None) -> None:
    assert parse_retry_delay(ProviderError(message), NOW) == expected


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ProviderError("rate limited", status_code=429), "retry"),
        (ProviderError("request timeout", status_code=408), "retry"),
        (ProviderError("provider unavailable", status_code=503), "retry"),
        (ProviderError("RESOURCE_EXHAUSTED"), "retry"),
        (ProviderError("context window exceeded", status_code=400), "continue_context"),
        (ProviderError("invalid API key", status_code=401), "terminal"),
        (ProviderError("invalid request", status_code=400), "terminal"),
    ],
)
def test_retry_classification(error: Exception, expected: str) -> None:
    assert classify_retry(error) == expected


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        TimeoutError("timed out"),
        ConnectionError("connection failed"),
        APIConnectionError("Connection error."),
    ],
)
def test_transport_exception_types_are_retryable_without_status_or_magic_text(
    error: Exception,
) -> None:
    assert classify_retry(error) == "retry"


def test_provider_delay_is_exact_and_fallback_jitter_is_bounded() -> None:
    assert next_retry(0, timedelta(seconds=47), lambda: 1.0) == timedelta(seconds=47)
    low = next_retry(3, None, lambda: 0.0).total_seconds()
    high = next_retry(3, None, lambda: 1.0).total_seconds()
    assert low == pytest.approx(6.4)
    assert high == pytest.approx(9.6)


def test_only_two_application_retries_are_immediate_and_long_waits_are_persisted() -> (
    None
):
    transient = ProviderError("temporarily unavailable", status_code=503)
    first = plan_retry(
        transient,
        attempt=0,
        now=NOW,
        deadline=NOW + timedelta(hours=24),
        rng=lambda: 0.5,
    )
    second = plan_retry(
        transient,
        attempt=1,
        now=NOW,
        deadline=NOW + timedelta(hours=24),
        rng=lambda: 0.5,
    )
    third = plan_retry(
        transient,
        attempt=2,
        now=NOW,
        deadline=NOW + timedelta(hours=24),
        rng=lambda: 0.5,
    )
    delayed = plan_retry(
        ProviderError("retry in 47s", status_code=429),
        attempt=0,
        now=NOW,
        deadline=NOW + timedelta(hours=24),
        rng=lambda: 0.5,
    )

    assert [first.action, second.action, third.action, delayed.action] == [
        "retry_now",
        "retry_now",
        "waiting_retry",
        "waiting_retry",
    ]
    assert delayed.delay == timedelta(seconds=47)
    assert delayed.next_attempt_at == NOW + timedelta(seconds=47)


def test_retry_never_crosses_24_hour_terminal_deadline() -> None:
    decision = plan_retry(
        ProviderError("retry in 47s", status_code=429),
        attempt=0,
        now=NOW,
        deadline=NOW + timedelta(seconds=30),
        rng=lambda: 0.5,
    )
    assert decision.action == "terminal"
    assert decision.next_attempt_at is None


def test_rolling_input_budget_enforces_500k_tokens_per_minute() -> None:
    budget = RollingInputBudget(limit=500_000, window=timedelta(minutes=1))
    assert budget.reserve(300_000, at=NOW) is True
    assert budget.reserve(200_000, at=NOW + timedelta(seconds=10)) is True
    assert budget.reserve(1, at=NOW + timedelta(seconds=20)) is False
    assert budget.used(at=NOW + timedelta(seconds=20)) == 500_000
    assert budget.reserve(250_000, at=NOW + timedelta(seconds=61)) is True
    assert budget.used(at=NOW + timedelta(seconds=61)) == 450_000


def test_prompt_guard_applies_compression_turn_and_loop_limits() -> None:
    guard = PromptBudgetGuard(
        compression_tokens=96_000,
        max_turns=16,
        exact_failure_limit=5,
        same_tool_failure_limit=8,
        no_progress_limit=5,
    )
    assert guard.evaluate(input_tokens=95_999, turn_count=15) == "continue"
    assert guard.evaluate(input_tokens=96_000, turn_count=15) == "compress"
    assert guard.evaluate(input_tokens=1, turn_count=16) == "stop_turn_limit"
    assert guard.evaluate(input_tokens=1, turn_count=1, exact_failures=5) == "stop_loop"
    assert (
        guard.evaluate(input_tokens=1, turn_count=1, same_tool_failures=8)
        == "stop_loop"
    )
    assert guard.evaluate(input_tokens=1, turn_count=1, no_progress=5) == "stop_loop"


@pytest.mark.parametrize(
    ("side_effect_class", "state", "has_result", "expected"),
    [
        ("read_only", "started", False, "repeat_read"),
        ("read_only", "failed", False, "repeat_read"),
        ("idempotent_write", "not_delivered", False, "retry_not_delivered"),
        ("idempotent_write", "delivery_uncertain", False, "block_uncertain"),
        ("non_idempotent_write", "not_delivered", False, "block_uncertain"),
        ("non_idempotent_write", "succeeded", True, "restore_result"),
    ],
)
def test_retry_side_effect_decisions_match_backend_contract(
    side_effect_class: str,
    state: str,
    has_result: bool,
    expected: str,
) -> None:
    assert tool_replay_decision(side_effect_class, state, has_result) == expected


def test_transient_copy_promises_automatic_continuation_without_session_commands() -> (
    None
):
    lowered = AUTOMATIC_CONTINUATION_MESSAGE.lower()
    assert "saved" in lowered
    assert "continue automatically" in lowered
    assert "/new" not in lowered
    assert "/reset" not in lowered
    assert "/compact" not in lowered
