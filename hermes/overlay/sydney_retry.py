"""Pure retry, continuation, prompt-budget, and replay guard primitives."""

from __future__ import annotations

import math
import re
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Literal

AUTOMATIC_CONTINUATION_MESSAGE = (
    "Your request is saved. Sydney will continue automatically when the provider "
    "is available."
)
RetryClass = Literal["retry", "continue_context", "terminal"]
RetryAction = Literal["retry_now", "waiting_retry", "continue_context", "terminal"]
PromptAction = Literal[
    "continue",
    "compress",
    "stop_turn_limit",
    "stop_loop",
]

_TEXT_DELAY = re.compile(
    r"(?i)\b(?:retry|try\s+again)\s+(?:in|after)\s+"
    r"(?P<amount>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>milliseconds?|msecs?|ms|seconds?|secs?|s|minutes?|mins?|m)\b"
)
_CONTEXT_PATTERNS = (
    "context window",
    "context length",
    "maximum context",
    "max context",
    "too many input tokens",
    "prompt is too long",
)
_RETRY_TEXT = (
    "resource_exhausted",
    "rate limit",
    "rate-limit",
    "too many requests",
    "temporarily unavailable",
    "service unavailable",
    "request timeout",
    "deadline exceeded",
    "connection reset",
    "connection timed out",
)


@dataclass(frozen=True, slots=True)
class RetryDecision:
    action: RetryAction
    delay: timedelta | None = None
    next_attempt_at: datetime | None = None
    classification: RetryClass = "terminal"
    message: str = AUTOMATIC_CONTINUATION_MESSAGE


def _duration_from_value(value: Any) -> timedelta | None:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value if value.total_seconds() >= 0 else None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return timedelta(seconds=max(0.0, float(value)))
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m)?\s*", value, re.IGNORECASE)
        if match:
            amount = float(match.group(1))
            unit = (match.group(2) or "s").lower()
            if unit == "ms":
                amount /= 1_000
            elif unit == "m":
                amount *= 60
            return timedelta(seconds=amount)
        return None
    if isinstance(value, Mapping):
        for key in ("retry_delay", "retryDelay", "delay"):
            if key in value:
                nested = _duration_from_value(value[key])
                if nested is not None:
                    return nested
        seconds = value.get("seconds", 0)
        nanos = value.get("nanos", value.get("nanoseconds", 0))
        try:
            total = float(seconds) + float(nanos) / 1_000_000_000
        except (TypeError, ValueError):
            return None
        if math.isfinite(total) and total >= 0:
            return timedelta(seconds=total)
        return None
    for attribute in ("retry_delay", "retryDelay", "delay"):
        if hasattr(value, attribute):
            parsed = _duration_from_value(getattr(value, attribute))
            if parsed is not None:
                return parsed
    if hasattr(value, "seconds") or hasattr(value, "nanos"):
        return _duration_from_value(
            {
                "seconds": getattr(value, "seconds", 0),
                "nanos": getattr(value, "nanos", 0),
            }
        )
    return None


def _headers(error: BaseException) -> dict[str, str]:
    source: Any = getattr(error, "headers", None)
    if source is None and getattr(error, "response", None) is not None:
        source = getattr(error.response, "headers", None)
    if not isinstance(source, Mapping):
        return {}
    return {str(key).lower(): str(value) for key, value in source.items()}


def _structured_delay(error: BaseException) -> timedelta | None:
    for attribute in ("retry_info", "retryInfo"):
        parsed = _duration_from_value(getattr(error, attribute, None))
        if parsed is not None:
            return parsed
    details = getattr(error, "details", None)
    if isinstance(details, (list, tuple)):
        for detail in details:
            parsed = _duration_from_value(detail)
            if parsed is not None:
                return parsed
    return None


def parse_retry_delay(error: BaseException, now: datetime) -> timedelta | None:
    """Parse provider-directed retry timing without inventing jitter."""
    structured = _structured_delay(error)
    if structured is not None:
        return structured

    headers = _headers(error)
    retry_after = headers.get("retry-after")
    if retry_after:
        numeric = _duration_from_value(retry_after)
        if numeric is not None:
            return numeric
        try:
            target = parsedate_to_datetime(retry_after)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return max(target - now, timedelta(0))
        except (TypeError, ValueError, OverflowError):
            pass

    absolute_reset = headers.get("x-ratelimit-reset") or headers.get("ratelimit-reset")
    if absolute_reset:
        try:
            target = datetime.fromtimestamp(float(absolute_reset), tz=timezone.utc)
            return max(target - now, timedelta(0))
        except (TypeError, ValueError, OverflowError):
            pass

    match = _TEXT_DELAY.search(str(error))
    if not match:
        return None
    amount = float(match.group("amount"))
    unit = match.group("unit").lower()
    if unit.startswith(("ms", "millisecond")):
        amount /= 1_000
    elif unit.startswith("m"):
        amount *= 60
    return timedelta(seconds=amount)


def _status_code(error: BaseException) -> int | None:
    candidates = [
        getattr(error, "status_code", None),
        getattr(error, "status", None),
        getattr(error, "code", None),
    ]
    response = getattr(error, "response", None)
    if response is not None:
        candidates.extend(
            (getattr(response, "status_code", None), getattr(response, "status", None))
        )
    for candidate in candidates:
        if callable(candidate):
            continue
        if hasattr(candidate, "value"):
            candidate = candidate.value
        try:
            code = int(candidate)
        except (TypeError, ValueError):
            continue
        if 100 <= code <= 599:
            return code
    return None


def classify_retry(error: BaseException) -> RetryClass:
    """Classify provider failures without treating permanent 4xx errors as transient."""
    message = str(error).lower()
    if any(pattern in message for pattern in _CONTEXT_PATTERNS):
        return "continue_context"
    status = _status_code(error)
    if status in {408, 425, 429} or (status is not None and 500 <= status <= 599):
        return "retry"
    if status is not None and 400 <= status <= 499:
        return "terminal"
    if any(pattern in message for pattern in _RETRY_TEXT):
        return "retry"
    return "terminal"


def next_retry(
    attempt: int,
    provider_delay: timedelta | None,
    rng: Callable[[], float],
) -> timedelta:
    """Return exact provider timing or bounded exponential fallback jitter."""
    if provider_delay is not None:
        return max(provider_delay, timedelta(0))
    base_seconds = min(300.0, float(2 ** max(0, int(attempt))))
    sample = min(1.0, max(0.0, float(rng())))
    jitter_multiplier = 0.8 + (0.4 * sample)
    return timedelta(seconds=base_seconds * jitter_multiplier)


def plan_retry(
    error: BaseException,
    *,
    attempt: int,
    now: datetime,
    deadline: datetime,
    rng: Callable[[], float],
) -> RetryDecision:
    """Plan at most two short in-process retries; persist everything longer."""
    classification = classify_retry(error)
    if classification == "continue_context":
        return RetryDecision(action="continue_context", classification=classification)
    if classification == "terminal":
        return RetryDecision(action="terminal", classification=classification)
    delay = next_retry(attempt, parse_retry_delay(error, now), rng)
    next_attempt = now + delay
    if next_attempt > deadline:
        return RetryDecision(action="terminal", classification="terminal")
    action: RetryAction = (
        "retry_now"
        if attempt < 2 and delay <= timedelta(seconds=5)
        else "waiting_retry"
    )
    return RetryDecision(
        action=action,
        delay=delay,
        next_attempt_at=next_attempt,
        classification=classification,
    )


class RollingInputBudget:
    """A timestamped, lock-free rolling input-token budget for one agent loop."""

    def __init__(
        self, *, limit: int = 500_000, window: timedelta = timedelta(minutes=1)
    ) -> None:
        if limit < 1 or window <= timedelta(0):
            raise ValueError("rolling budget limits must be positive")
        self.limit = int(limit)
        self.window = window
        self._entries: deque[tuple[datetime, int]] = deque()
        self._total = 0

    def _prune(self, at: datetime) -> None:
        cutoff = at - self.window
        while self._entries and self._entries[0][0] <= cutoff:
            _, tokens = self._entries.popleft()
            self._total -= tokens

    def used(self, *, at: datetime) -> int:
        self._prune(at)
        return self._total

    def reserve(self, tokens: int, *, at: datetime) -> bool:
        if tokens < 0:
            raise ValueError("tokens must be nonnegative")
        self._prune(at)
        if self._total + tokens > self.limit:
            return False
        self._entries.append((at, int(tokens)))
        self._total += int(tokens)
        return True


@dataclass(frozen=True, slots=True)
class PromptBudgetGuard:
    compression_tokens: int = 96_000
    max_turns: int = 16
    exact_failure_limit: int = 5
    same_tool_failure_limit: int = 8
    no_progress_limit: int = 5

    def evaluate(
        self,
        *,
        input_tokens: int,
        turn_count: int,
        exact_failures: int = 0,
        same_tool_failures: int = 0,
        no_progress: int = 0,
    ) -> PromptAction:
        if turn_count >= self.max_turns:
            return "stop_turn_limit"
        if (
            exact_failures >= self.exact_failure_limit
            or same_tool_failures >= self.same_tool_failure_limit
            or no_progress >= self.no_progress_limit
        ):
            return "stop_loop"
        if input_tokens >= self.compression_tokens:
            return "compress"
        return "continue"


def tool_replay_decision(
    side_effect_class: str,
    state: str,
    has_result: bool,
) -> Literal["repeat_read", "restore_result", "retry_not_delivered", "block_uncertain"]:
    """Mirror the backend's fail-closed tool replay classifier."""
    if state == "succeeded" and has_result:
        return "restore_result"
    if side_effect_class == "read_only":
        return "repeat_read"
    if side_effect_class == "idempotent_write" and state == "not_delivered":
        return "retry_not_delivered"
    return "block_uncertain"
