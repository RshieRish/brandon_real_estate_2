"""Small Hermes integration seams for Sydney's pinned source patch."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from plugins.memory.sydney.sydney_retry import RollingInputBudget
except ImportError:
    try:
        from .sydney_retry import RollingInputBudget
    except ImportError:
        from sydney_retry import RollingInputBudget


class SydneyBudgetExceeded(RuntimeError):
    status_code = 429
    headers = {"Retry-After": "60"}


def get_sydney_provider(agent: Any) -> Any | None:
    manager = getattr(agent, "_memory_manager", None)
    if manager is None:
        return None
    try:
        return manager.get_provider("sydney")
    except (AttributeError, RuntimeError):
        return None


def record_inbound_before_model(
    agent: Any,
    *,
    platform_message_id: str,
    content: str,
) -> None:
    provider = get_sydney_provider(agent)
    if provider is None:
        return
    provider.record_inbound(platform_message_id, content)
    provider.drain_once()


def reserve_input_budget(agent: Any, tokens: int) -> None:
    provider = get_sydney_provider(agent)
    if provider is None:
        return
    budget = getattr(agent, "_sydney_input_budget", None)
    if budget is None:
        budget = RollingInputBudget(limit=500_000)
        agent._sydney_input_budget = budget
    now = datetime.now(timezone.utc)
    blocked_until = getattr(agent, "_sydney_budget_blocked_until", None)
    if isinstance(blocked_until, datetime) and blocked_until > now:
        raise SydneyBudgetExceeded("retry in 60s: rolling input budget exhausted")
    reservation = max(0, int(tokens))
    if not budget.reserve(reservation, at=now):
        raise SydneyBudgetExceeded("retry in 60s: rolling input budget exhausted")
    agent._sydney_current_reserved_input_tokens = reservation


def reconcile_input_usage(agent: Any, actual_tokens: int) -> None:
    """Account for any provider-reported input beyond the preflight estimate."""
    provider = get_sydney_provider(agent)
    if provider is None:
        return
    actual = max(0, int(actual_tokens))
    reserved = max(0, int(getattr(agent, "_sydney_current_reserved_input_tokens", 0)))
    agent._sydney_last_actual_input_tokens = actual
    difference = max(0, actual - reserved)
    if difference <= 0:
        return
    budget = getattr(agent, "_sydney_input_budget", None)
    now = datetime.now(timezone.utc)
    if budget is None or not budget.reserve(difference, at=now):
        agent._sydney_budget_blocked_until = now + timedelta(minutes=1)


def defer_retry_if_needed(agent: Any, error: BaseException, attempt: int) -> str | None:
    provider = get_sydney_provider(agent)
    if provider is None:
        return None
    return provider.defer_retry(error, attempt=max(0, int(attempt)))


def record_run_outcome(agent: Any, result: dict[str, Any]) -> None:
    provider = get_sydney_provider(agent)
    if provider is None:
        return
    response = result.get("final_response")
    if result.get("completed") is not False and isinstance(response, str) and response:
        provider.complete_active_run(response)


def _side_effect_class(tool_name: str) -> str:
    lowered = tool_name.lower()
    read_markers = (
        "read",
        "search",
        "list",
        "status",
        "preview",
        "history",
        "get",
        "inspect",
    )
    if any(marker in lowered for marker in read_markers):
        return "read_only"
    if lowered in {"todo", "memory"}:
        return "idempotent_write"
    return "non_idempotent_write"


def tool_before(agent: Any, tool_call_id: str, tool_name: str, arguments: dict[str, Any]) -> str | None:
    provider = get_sydney_provider(agent)
    if provider is None:
        return None
    if not provider.active_run_id:
        provider.drain_once()
    run_id = provider.active_run_id
    if not run_id or not provider.active_lease_owner:
        return "Sydney could not establish the durable run ledger; execution was blocked."
    source_key = f"tool:{run_id}:{tool_call_id}:before"
    provider.record_tool_before(
        run_id=run_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        side_effect_class=_side_effect_class(tool_name),
    )
    provider.drain_once()
    receipt = provider.tool_replay_receipt(source_key) or {}
    decision = receipt.get("replay_decision")
    if decision in {"execute", "repeat_read", "retry_not_delivered"}:
        return None
    if decision == "restore_result":
        return "Sydney blocked duplicate execution because the prior tool result already exists."
    if decision == "block_uncertain":
        return "Sydney blocked duplicate execution because delivery is uncertain."
    return "Sydney could not acknowledge the tool ledger; execution was blocked."


def tool_after(
    agent: Any,
    tool_call_id: str,
    tool_name: str,
    result: Any,
    *,
    failed: bool,
) -> None:
    provider = get_sydney_provider(agent)
    if provider is None or not provider.active_run_id:
        return
    side_effect = _side_effect_class(tool_name)
    if failed:
        state = "failed" if side_effect == "read_only" else "delivery_uncertain"
    else:
        state = "succeeded"
    if isinstance(result, str):
        content = result
    else:
        try:
            content = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            content = str(result)
    provider.record_tool_after(
        run_id=provider.active_run_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        state=state,
        result_content=content if state == "succeeded" else None,
    )
    provider.drain_once()
