"""Small Hermes integration seams for Sydney's pinned source patch."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar
from uuid import uuid4

try:
    from plugins.memory.sydney.sydney_retry import RollingInputBudget
except ImportError:
    try:
        from .sydney_retry import RollingInputBudget
    except ImportError:
        from sydney_retry import RollingInputBudget


class SydneyBudgetExceeded(RuntimeError):
    status_code = 429
    headers: ClassVar[dict[str, str]] = {"Retry-After": "60"}


@dataclass(frozen=True)
class SydneyToolBeforeDecision:
    """A fail-closed block or an already-persisted successful tool result."""

    block_message: str | None = None
    restored_result: str | None = None


@dataclass(frozen=True)
class _PendingDelivery:
    provider: Any
    result: dict[str, Any]
    degraded: bool = False
    delivery_kind: str = "final"


@dataclass(frozen=True)
class _ActiveExecution:
    provider: Any
    run_id: str


_PENDING_DELIVERIES: dict[tuple[str, str, str], _PendingDelivery] = {}
_PENDING_DELIVERIES_LOCK = threading.Lock()
_ACTIVE_EXECUTIONS: dict[tuple[str, str, str], _ActiveExecution] = {}
_ACTIVE_EXECUTIONS_LOCK = threading.Lock()


def _normalized_delivery_key(value: Any) -> tuple[str, str, str] | None:
    if (
        isinstance(value, (tuple, list))
        and len(value) == 3
        and all(isinstance(item, str) and item for item in value)
    ):
        return (value[0], value[1], value[2])
    return None


def _delivery_key_for_event(event: Any) -> tuple[str, str, str] | None:
    overridden_key = _normalized_delivery_key(
        getattr(event, "_sydney_delivery_key", None)
    )
    if overridden_key is not None:
        return overridden_key
    source = getattr(event, "source", None)
    platform = getattr(source, "platform", "")
    platform_name = str(getattr(platform, "value", platform) or "")
    chat_id = str(getattr(source, "chat_id", "") or "")
    message_id = str(
        getattr(event, "message_id", "") or getattr(source, "message_id", "") or ""
    )
    return _normalized_delivery_key((platform_name, chat_id, message_id))


def _release_active_execution_by_key(key: tuple[str, str, str]) -> None:
    with _ACTIVE_EXECUTIONS_LOCK:
        active = _ACTIVE_EXECUTIONS.pop(key, None)
    if active is not None:
        active.provider.end_active_execution(active.run_id)


def _begin_active_execution(provider: Any, key: tuple[str, str, str]) -> bool:
    run_id = provider.begin_active_execution(key[2])
    if not run_id:
        return False
    with _ACTIVE_EXECUTIONS_LOCK:
        previous = _ACTIVE_EXECUTIONS.get(key)
        _ACTIVE_EXECUTIONS[key] = _ActiveExecution(provider=provider, run_id=run_id)
    if previous is not None and (
        previous.provider is not provider or previous.run_id != run_id
    ):
        previous.provider.end_active_execution(previous.run_id)
    return True


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
    internal: bool = False,
) -> bool:
    previous_key = getattr(agent, "_sydney_delivery_key", None)
    agent._sydney_delivery_key = None
    agent._sydney_degraded_delivery_key = None
    agent._sydney_terminal_replay_state = None
    agent._sydney_control_replay_state = None
    provider = get_sydney_provider(agent)
    if provider is None:
        return True
    if not provider.is_available():
        return True
    if not getattr(provider, "retry_enabled", False):
        if not internal:
            provider.record_inbound(platform_message_id, content)
            provider.drain_once()
        return True
    delivery_key = (
        str(getattr(provider, "_platform", "")),
        str(getattr(provider, "_external_chat_id", "")),
        str(platform_message_id),
    )
    prior_finalization_pending = False
    if previous_key and previous_key != delivery_key:
        normalized_previous_key = _normalized_delivery_key(previous_key)
        if normalized_previous_key is not None:
            _release_active_execution_by_key(normalized_previous_key)
        prior_finalization_pending = provider.has_pending_run_finalization(previous_key)
        if prior_finalization_pending:
            provider.drain_once()
            prior_finalization_pending = provider.has_pending_run_finalization(
                previous_key
            )
        if not prior_finalization_pending:
            provider.supersede_active_run()
    agent._sydney_delivery_key = delivery_key
    if internal:
        provider.activate_claimed_inbound(platform_message_id)
        provider.drain_once()
        terminal_state = provider.inbound_terminal_state(platform_message_id)
        if terminal_state is not None:
            agent._sydney_terminal_replay_state = terminal_state
            return False
        if provider.owns_run_lease(platform_message_id):
            return _begin_active_execution(provider, delivery_key)
        return False
    control_replay = provider.resolve_staged_control_delivery(delivery_key)
    if control_replay is not None:
        agent._sydney_control_replay_state = control_replay
        return False
    final_replay = provider.resolve_staged_final_delivery(delivery_key)
    if final_replay is not None:
        agent._sydney_control_replay_state = final_replay
        return False
    provider.record_inbound(platform_message_id, content)
    provider.drain_once()
    terminal_state = provider.inbound_terminal_state(platform_message_id)
    if terminal_state is not None:
        agent._sydney_terminal_replay_state = terminal_state
        return False
    if prior_finalization_pending and provider.has_pending_run_finalization(
        previous_key
    ):
        return False
    if provider.owns_run_lease(platform_message_id):
        return _begin_active_execution(provider, delivery_key)
    if bool(getattr(provider, "last_drain_backend_unavailable", False)) and bool(
        provider.inbound_is_pending(platform_message_id)
    ):
        agent._sydney_degraded_delivery_key = delivery_key
        return True
    return False


def deferred_inbound_response(agent: Any) -> str:
    try:
        from plugins.memory.sydney.sydney_retry import (
            AUTOMATIC_CONTINUATION_MESSAGE,
            AUTOMATIC_TERMINAL_REPLAY_MESSAGE,
        )
    except ImportError:
        try:
            from .sydney_retry import (
                AUTOMATIC_CONTINUATION_MESSAGE,
                AUTOMATIC_TERMINAL_REPLAY_MESSAGE,
            )
        except ImportError:
            from sydney_retry import (
                AUTOMATIC_CONTINUATION_MESSAGE,
                AUTOMATIC_TERMINAL_REPLAY_MESSAGE,
            )
    if getattr(agent, "_sydney_control_replay_state", None):
        return ""
    if getattr(agent, "_sydney_terminal_replay_state", None):
        return AUTOMATIC_TERMINAL_REPLAY_MESSAGE
    return AUTOMATIC_CONTINUATION_MESSAGE


def reserve_input_budget(agent: Any, tokens: int) -> None:
    provider = get_sydney_provider(agent)
    if provider is None or not getattr(provider, "retry_enabled", False):
        return
    budget = getattr(agent, "_sydney_input_budget", None)
    if budget is None:
        try:
            configured_limit = int(
                os.environ.get("SYDNEY_CONTEXT_INTERACTIVE_TPM_BUDGET", "500000")
            )
        except (TypeError, ValueError):
            configured_limit = 500_000
        budget = RollingInputBudget(limit=max(1, min(configured_limit, 10_000_000)))
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
    if provider is None or not getattr(provider, "retry_enabled", False):
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
    if provider is None or not getattr(provider, "retry_enabled", False):
        return None
    return provider.defer_retry(error, attempt=max(0, int(attempt)))


def defer_compression_exhaustion(agent: Any) -> str | None:
    """Move a compression-exhausted run onto the automatic continuation lane."""
    provider = get_sydney_provider(agent)
    if provider is None or not getattr(provider, "retry_enabled", False):
        return None
    return provider.defer_compression_exhaustion()


def stage_run_outcome(agent: Any, result: dict[str, Any]) -> bool:
    """Hold a successful model result until the platform confirms delivery."""
    provider = get_sydney_provider(agent)
    if provider is None or not getattr(provider, "retry_enabled", False):
        return False
    if getattr(agent, "_sydney_terminal_replay_state", None):
        return False
    if getattr(agent, "_sydney_control_replay_state", None):
        result["final_response"] = ""
        result["already_sent"] = True
        return False
    response = result.get("final_response")
    key = getattr(agent, "_sydney_delivery_key", None)
    if (
        not isinstance(response, str)
        or not response
        or not isinstance(key, tuple)
        or len(key) != 3
        or not all(isinstance(value, str) and value for value in key)
    ):
        if result.get("failed") or (
            result.get("completed") is False and not result.get("deferred")
        ):
            provider.fail_active_run(error_code="model_terminal_failure")
        return False
    delivery_kind = "final"
    if result.get("deferred"):
        delivery_kind = "deferred"
    elif result.get("failed") or result.get("completed") is False:
        delivery_kind = "terminal_error"
    if delivery_kind != "final":
        try:
            staged_status = provider.stage_control_delivery(
                key,
                response,
                delivery_kind=delivery_kind,
                error_code="model_terminal_failure",
            )
        except Exception:  # noqa: BLE001 - optional plugin boundary must fail closed.
            staged_status = "unavailable"
        if staged_status != "staged":
            if staged_status in {"pending", "delivered"}:
                result["already_sent"] = True
            else:
                provider.fail_active_run(
                    error_code="control_delivery_ledger_unavailable"
                )
                result["completed"] = False
                result["failed"] = True
            result["final_response"] = ""
            return False
        with _PENDING_DELIVERIES_LOCK:
            _PENDING_DELIVERIES[key] = _PendingDelivery(
                provider=provider,
                result=result,
                delivery_kind=delivery_kind,
            )
        return True
    degraded = getattr(agent, "_sydney_degraded_delivery_key", None) == key
    if degraded:
        provider.drain_once()
        if provider.owns_run_lease(key[2]):
            agent._sydney_degraded_delivery_key = None
            degraded = False
    try:
        staged = (
            provider.stage_degraded_delivery(key, response)
            if degraded
            else provider.stage_final_delivery(key, response)
        )
    except Exception:  # noqa: BLE001 - optional plugin boundary must fail closed.
        staged = False
    if not staged:
        provider.fail_active_run(error_code="final_delivery_ledger_unavailable")
        result["final_response"] = ""
        result["completed"] = False
        result["failed"] = True
        return False
    with _PENDING_DELIVERIES_LOCK:
        _PENDING_DELIVERIES[key] = _PendingDelivery(
            provider=provider,
            result=result,
            degraded=degraded,
            delivery_kind="final",
        )
    return True


def record_delivery_by_key(delivery_key: Any, *, delivered: bool) -> None:
    """Commit one staged run only after its final response landed."""
    if (
        not isinstance(delivery_key, tuple)
        or len(delivery_key) != 3
        or not all(isinstance(value, str) and value for value in delivery_key)
    ):
        return
    key = delivery_key
    with _PENDING_DELIVERIES_LOCK:
        pending = _PENDING_DELIVERIES.pop(key, None)
    if pending is None:
        return
    if delivered or bool(pending.result.get("already_sent")):
        response = pending.result.get("final_response")
        if isinstance(response, str) and response:
            if pending.delivery_kind in {"deferred", "terminal_error"}:
                pending.provider.confirm_control_delivery(
                    key,
                    response,
                    delivery_kind=pending.delivery_kind,
                )
            elif pending.degraded:
                pending.provider.confirm_degraded_delivery(key, response)
            else:
                pending.provider.complete_active_run(response, delivery_key=key)
    # A failed adapter call cannot prove Telegram rejected the send. Keep the
    # durable staged marker so restart recovery blocks a potentially duplicate
    # final response until a human or authoritative receipt resolves it.


def record_delivery_outcome(event: Any, *, delivered: bool) -> None:
    """Resolve the event's staged run at the platform delivery boundary."""
    key = _delivery_key_for_event(event)
    if key is not None:
        record_delivery_by_key(key, delivered=delivered)


def release_active_execution_for_event(event: Any) -> None:
    """Stop renewals when the adapter's message handler has exited."""
    key = _delivery_key_for_event(event)
    if key is not None:
        _release_active_execution_by_key(key)


def _side_effect_class(tool_name: str) -> str:
    lowered = tool_name.lower()
    if lowered in {"todo", "memory"}:
        return "idempotent_write"
    tokens = set(re.findall(r"[a-z0-9]+", lowered))
    mutation_markers = {
        "add",
        "append",
        "archive",
        "approve",
        "clear",
        "create",
        "delete",
        "dismiss",
        "draft",
        "edit",
        "execute",
        "forget",
        "import",
        "insert",
        "invite",
        "move",
        "pause",
        "publish",
        "remove",
        "reset",
        "restore",
        "resume",
        "run",
        "send",
        "set",
        "start",
        "stop",
        "subscribe",
        "update",
        "upsert",
        "write",
    }
    if tokens.intersection(mutation_markers):
        return "non_idempotent_write"
    read_only_tools = {"leads_recent", "bookings_recent"}
    read_markers = {
        "get",
        "history",
        "inspect",
        "list",
        "preview",
        "read",
        "search",
        "status",
    }
    if lowered in read_only_tools or tokens.intersection(read_markers):
        return "read_only"
    return "non_idempotent_write"


def _caller_idempotency_key(
    tool_name: str,
    arguments: dict[str, Any],
    side_effect_class: str,
) -> str | None:
    if side_effect_class == "read_only":
        return None
    for key in ("request_id", "idempotency_key", "idempotencyKey"):
        value = arguments.get(key)
        if isinstance(value, str) and value:
            digest = hashlib.sha256(
                f"sydney-tool-intent-v1\0{tool_name}\0{key}\0{value}".encode()
            ).hexdigest()
            return f"{key}_sha256:{digest}"
    canonical = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(
        f"sydney-tool-intent-v1\0{tool_name}\0{canonical}".encode()
    ).hexdigest()
    return f"arguments_sha256:{digest}"


def tool_before(
    agent: Any,
    tool_call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> SydneyToolBeforeDecision | None:
    provider = get_sydney_provider(agent)
    if provider is None or not getattr(provider, "retry_enabled", False):
        return None
    degraded_key = getattr(agent, "_sydney_degraded_delivery_key", None)
    if isinstance(degraded_key, tuple) and len(degraded_key) == 3:
        provider.drain_once()
        if provider.owns_run_lease(str(degraded_key[2])):
            agent._sydney_degraded_delivery_key = None
        else:
            if _side_effect_class(tool_name) == "read_only":
                return None
            return SydneyToolBeforeDecision(
                block_message=(
                    "Sydney saved this request locally, but the durable backend is "
                    "unavailable; mutating tools are blocked until it recovers."
                )
            )
    if not provider.has_active_run_lease():
        provider.drain_once()
    run_id = provider.active_run_id
    if not run_id or not provider.has_active_run_lease():
        return SydneyToolBeforeDecision(
            block_message=(
                "Sydney could not establish the durable run ledger; execution was blocked."
            )
        )
    source_key = f"tool:{run_id}:{tool_call_id}:before"
    side_effect_class = _side_effect_class(tool_name)
    existing_receipt = provider.tool_replay_receipt(source_key)
    provider.record_tool_before(
        run_id=run_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        side_effect_class=side_effect_class,
        caller_idempotency_key=_caller_idempotency_key(
            tool_name,
            arguments,
            side_effect_class,
        ),
    )
    provider.drain_once()
    receipt = (
        provider.refresh_tool_replay(source_key)
        if existing_receipt is not None
        else provider.tool_replay_receipt(source_key)
    ) or {}
    receipt = receipt.get("tool", receipt)
    decision = receipt.get("replay_decision")
    canonical_tool_call_id = receipt.get("canonical_tool_call_id")
    if (
        decision in {"execute", "repeat_read", "retry_not_delivered"}
        and isinstance(canonical_tool_call_id, str)
        and canonical_tool_call_id
        and canonical_tool_call_id != tool_call_id
    ):
        aliases = getattr(agent, "_sydney_tool_call_aliases", None)
        if not isinstance(aliases, dict):
            aliases = {}
            agent._sydney_tool_call_aliases = aliases
        aliases[tool_call_id] = canonical_tool_call_id
    if decision in {"execute", "repeat_read", "retry_not_delivered"}:
        attempts = getattr(agent, "_sydney_tool_attempt_keys", None)
        if not isinstance(attempts, dict):
            attempts = {}
            agent._sydney_tool_attempt_keys = attempts
        attempts[tool_call_id] = uuid4().hex
        return None
    if decision == "restore_result":
        result_content = receipt.get("result_content")
        if isinstance(result_content, str):
            return SydneyToolBeforeDecision(restored_result=result_content)
        return SydneyToolBeforeDecision(
            block_message=(
                "Sydney found a prior tool result but could not restore its content; "
                "execution was blocked."
            )
        )
    if decision == "block_uncertain":
        return SydneyToolBeforeDecision(
            block_message=(
                "Sydney blocked duplicate execution because delivery is uncertain."
            )
        )
    return SydneyToolBeforeDecision(
        block_message=(
            "Sydney could not acknowledge the tool ledger; execution was blocked."
        )
    )


def tool_after(
    agent: Any,
    tool_call_id: str,
    tool_name: str,
    result: Any,
    *,
    failed: bool,
) -> None:
    provider = get_sydney_provider(agent)
    if (
        provider is None
        or not getattr(provider, "retry_enabled", False)
        or not provider.has_active_run_lease()
    ):
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
    aliases = getattr(agent, "_sydney_tool_call_aliases", None)
    canonical_tool_call_id = (
        aliases.pop(tool_call_id, tool_call_id)
        if isinstance(aliases, dict)
        else tool_call_id
    )
    attempts = getattr(agent, "_sydney_tool_attempt_keys", None)
    attempt_key = (
        attempts.pop(tool_call_id, None) if isinstance(attempts, dict) else None
    )
    provider.record_tool_after(
        run_id=provider.active_run_id,
        tool_call_id=canonical_tool_call_id,
        tool_name=tool_name,
        state=state,
        result_content=content,
        attempt_key=attempt_key,
    )
    provider.drain_once()
