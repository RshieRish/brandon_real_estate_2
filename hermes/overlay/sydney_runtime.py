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
class SydneyToolPolicyHalt:
    """Duck-typed terminal decision consumed by Hermes' guarded turn exit."""

    code: str
    message: str
    tool_name: str
    count: int
    action: str = "halt"

    @property
    def should_halt(self) -> bool:
        return True

    def to_metadata(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "code": self.code,
            "message": self.message,
            "tool_name": self.tool_name,
            "count": self.count,
        }


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

REVIEW_ONLY_RECOVERY_BLOCK_MESSAGE = (
    "This recovered request is review-only. The mutating tool was not executed. "
    "Return the review packet, state that nothing was sent, and wait for fresh "
    "Brandon approval."
)
NORMAL_BUSINESS_TOOL_BLOCK_MESSAGE = (
    "This private Sydney run may use only the approved Atlas business tools and "
    "skill_view. The requested local tool was not executed."
)
TOOL_INVOCATION_LIMIT_BLOCK_MESSAGE = (
    "Sydney reached this request's server-enforced tool limit. The tool was not "
    "executed; stop now and use the results already gathered."
)
ACCEPTED_ACKNOWLEDGEMENT = (
    "Got it — Sydney saved this request and is working on it now. "
    "You do not need to reset or resend it."
)
COALESCED_ACKNOWLEDGEMENT = (
    "This request is already in progress. Sydney will continue it "
    "automatically; you do not need to reset or resend it."
)

_REVIEW_ONLY_READ_TOOLS = frozenset(
    {
        "actions_list",
        "bookings_recent",
        "calendar_events_read",
        "command_contact_audience_preview",
        "command_contacts_search",
        "contacts_search",
        "context_history_search",
        "crm_task_suggestions_read",
        "crm_tasks_read",
        "drive_file_read",
        "drive_search",
        "gmail_search",
        "gmail_thread_read",
        "leads_recent",
        "status_read",
        "workspace_status",
    }
)
_ATLAS_MCP_TOOL_PREFIX = "mcp_atlas_backend_"
_ATLAS_BUSINESS_TOOLS = frozenset(
    {
        "actions_list",
        "bookings_recent",
        "calendar_event_create",
        "calendar_events_read",
        "command_card_campaign_draft_create",
        "command_contact_audience_preview",
        "command_contact_celebrations_preview",
        "command_contacts_search",
        "contacts_search",
        "context_history_search",
        "crm_task_clarifications_answer",
        "crm_task_drafts_create",
        "crm_task_suggestions_approval_link",
        "crm_task_suggestions_dismiss_proposal",
        "crm_task_suggestions_read",
        "crm_tasks_read",
        "docs_create",
        "drive_file_read",
        "drive_search",
        "gmail_draft_create",
        "gmail_search",
        "gmail_send",
        "gmail_thread_read",
        "leads_recent",
        "sheets_append",
        "status_read",
        "workspace_status",
    }
)


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


def filter_business_tool_surface(agent: Any) -> None:
    """Offer only executable tools to the identity-scoped private Sydney agent.

    Keep the executor guard as defense in depth for stale/history-generated
    calls. Never alter the shared Hermes registry or another user's surface.
    """
    provider = get_sydney_provider(agent)
    if (
        provider is None
        or not provider.is_available()
        or not getattr(provider, "retry_enabled", False)
    ):
        return
    definitions = getattr(agent, "tools", None)
    if not isinstance(definitions, list):
        return
    filtered = [
        tool
        for tool in definitions
        if isinstance(tool, dict)
        and isinstance(tool.get("function"), dict)
        and _normal_business_tool_is_allowed(tool["function"].get("name", ""))
    ]
    if filtered != definitions:
        agent.tools = filtered
        agent._cached_system_prompt = None
        agent._sydney_refresh_tool_surface_prompt = True
    agent.valid_tool_names = {tool["function"]["name"] for tool in filtered}


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
    agent._sydney_inbound_coalesced = False
    agent._sydney_acknowledgement_eligible = False
    agent._sydney_terminal_tool_policy_response = None
    provider = get_sydney_provider(agent)
    if provider is None:
        return True
    if not provider.is_available():
        return True
    filter_business_tool_surface(agent)
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
    if previous_key and previous_key != delivery_key:
        prior_finalization_pending = provider.has_pending_run_finalization(previous_key)
        if prior_finalization_pending:
            provider.drain_once()
            prior_finalization_pending = provider.has_pending_run_finalization(
                previous_key
            )
        if prior_finalization_pending:
            provider.record_inbound(platform_message_id, content)
            return False
    provider.record_inbound(platform_message_id, content)
    provider.drain_once()
    terminal_state = provider.inbound_terminal_state(platform_message_id)
    if terminal_state is not None:
        agent._sydney_terminal_replay_state = terminal_state
        return False
    if provider.inbound_was_coalesced(platform_message_id):
        agent._sydney_inbound_coalesced = True
        agent._sydney_acknowledgement_eligible = True
        return False
    incoming_run_id = provider.inbound_run_id(platform_message_id)
    active_run_id = str(getattr(provider, "active_run_id", "") or "")
    replacing_active_run = bool(
        incoming_run_id and active_run_id and incoming_run_id != active_run_id
    )
    if replacing_active_run:
        normalized_previous_key = _normalized_delivery_key(previous_key)
        if normalized_previous_key is not None:
            _release_active_execution_by_key(normalized_previous_key)
        prior_finalization_pending = provider.has_pending_run_finalization(previous_key)
        if prior_finalization_pending:
            provider.drain_once()
            prior_finalization_pending = provider.has_pending_run_finalization(
                previous_key
            )
        if prior_finalization_pending:
            agent._sydney_acknowledgement_eligible = True
            return False
        provider.supersede_active_run()
        provider.claim_inbound(platform_message_id)
    agent._sydney_acknowledgement_eligible = bool(incoming_run_id)
    if provider.owns_run_lease(platform_message_id):
        return _begin_active_execution(provider, delivery_key)
    if bool(getattr(provider, "last_drain_backend_unavailable", False)) and bool(
        provider.inbound_is_pending(platform_message_id)
    ):
        agent._sydney_degraded_delivery_key = delivery_key
        return True
    return False


def stage_inbound_acknowledgement(agent: Any) -> str | None:
    """Stage one visible acceptance receipt before the first model call."""
    if not getattr(agent, "_sydney_acknowledgement_eligible", False):
        return None
    agent._sydney_acknowledgement_eligible = False
    provider = get_sydney_provider(agent)
    key = _normalized_delivery_key(getattr(agent, "_sydney_delivery_key", None))
    if provider is None or key is None:
        return None
    response = (
        COALESCED_ACKNOWLEDGEMENT
        if getattr(agent, "_sydney_inbound_coalesced", False)
        else ACCEPTED_ACKNOWLEDGEMENT
    )
    try:
        status = provider.stage_control_delivery(
            key,
            response,
            delivery_kind="accepted",
        )
    except Exception:  # noqa: BLE001 - optional provider boundary fails closed.
        return None
    return response if status == "staged" else None


def confirm_inbound_acknowledgement(
    agent: Any,
    response: str,
    *,
    ambiguous: bool,
) -> None:
    """Commit the staged acceptance after success or an ambiguous send."""
    provider = get_sydney_provider(agent)
    key = _normalized_delivery_key(getattr(agent, "_sydney_delivery_key", None))
    if provider is None or key is None or not response:
        return
    provider.confirm_control_delivery(
        key,
        response,
        delivery_kind="accepted",
        ambiguous=ambiguous,
    )


def cancel_inbound_acknowledgement(agent: Any, response: str) -> None:
    """Clear a staged acceptance only when the adapter proves it was rejected."""
    provider = get_sydney_provider(agent)
    key = _normalized_delivery_key(getattr(agent, "_sydney_delivery_key", None))
    if provider is None or key is None or not response:
        return
    provider.cancel_control_delivery(
        key,
        response,
        delivery_kind="accepted",
    )


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
    if getattr(agent, "_sydney_inbound_coalesced", False):
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


def reconcile_input_usage(agent: Any, actual_tokens: Any) -> None:
    """Account for any provider-reported input beyond the preflight estimate."""
    provider = get_sydney_provider(agent)
    if provider is None or not getattr(provider, "retry_enabled", False):
        return
    if type(actual_tokens) is not int or actual_tokens < 0:
        return
    actual = actual_tokens
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


def _celebration_metadata(content: Any) -> dict[str, str]:
    """Read exact internal values from the known preview/MCP response shapes."""
    for _ in range(4):
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (TypeError, ValueError):
                return {}
        if not isinstance(content, dict) or content.get("isError"):
            return {}
        if "result" in content and set(content) <= {"result", "structuredContent"}:
            content = content["result"]
            continue
        reference = content.get("audience_ref")
        checksum = content.get("audience_checksum")
        if (
            isinstance(reference, str)
            and re.fullmatch(
                r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", reference
            )
            and isinstance(checksum, str)
            and re.fullmatch(r"[0-9a-fA-F]{64}", checksum)
        ):
            return {"reference": reference, "checksum": checksum}
        blocks = content.get("content")
        if not isinstance(blocks, list) or len(blocks) != 1:
            return {}
        block = blocks[0]
        if not isinstance(block, dict) or block.get("type") != "text":
            return {}
        content = block.get("text")
    return {}


def _requests_celebration_metadata(content: Any) -> bool:
    if not isinstance(content, str):
        return False
    metadata_term = r"\b(?:checksums?|audience[ _-]+(?:checksums?|refs?|references?|metadata|identifiers?))\b"
    modifiers = r"(?:(?:me|us|the|a|an|exact|current|internal|technical|returned|actual|full|my|their|its|our)\s+){0,5}"
    polite = r"(?:(?:please|now|also)\s+)*(?:(?:can|could|will|would)\s+you\s+(?:please\s+)?)?"
    # Quoted instructions are discussion content, not this turn's permission.
    # Only this local intent string changes; original user/history text is intact.
    intent = re.sub(
        r'"[^"\n]*"|“[^”]*”|‘[^’]*’|`[^`]*`|(?<!\w)\'[^\'\n]+\'(?!\w)',
        " ",
        content,
    ).replace("’", "'")
    metadata_request = (
        r"\s*(?:"
        + polite
        + r"(?:show|give|get|include|return|display|provide|tell|report|share|list|print)|"
        r"(?:can|could|may)\s+I\s+(?:please\s+)?have|I\s+(?:want|need)|"
        r"I(?:'d|\s+would)\s+like|what(?:\s+(?:is|are|was|were))?|which(?:\s+(?:is|are))?)\s+"
        + modifiers
        + metadata_term
    )
    requested = False
    metadata_seen = False
    for sentence in re.split(r"[.!?;\n]", intent):
        has_metadata = bool(re.search(metadata_term, sentence, re.IGNORECASE))
        metadata_seen = metadata_seen or has_metadata
        if has_metadata and (
            re.search(
                r"\b(?:not|without|omit|exclude|hide|no|leave\s+out|leaving\s+out|(?:do not|don't|never)\s+"
                r"(?:show|give|include|return|display|provide|print|report|list|tell|share|disclose|expose))"
                r"\b.{0,100}" + metadata_term,
                sentence,
                re.IGNORECASE,
            )
            or re.search(
                r"\bkeep\b.{0,80}" + metadata_term + r".{0,40}\binternal\b",
                sentence,
                re.IGNORECASE,
            )
        ):
            return False
        # A later/referring exclusion wins over an earlier affirmative request.
        if metadata_seen and re.search(
            r"\b(?:omit|exclude|hide|leave\s+out|(?:do not|don't|never)\s+"
            r"(?:show|include|display|provide|print|share))\s+"
            r"(?:it|them|those|these|(?:the\s+)?(?:values?|metadata|identifiers?))\b|"
            r"\b(?:which|it|they|these|those|values?|metadata)\s+"
            r"(?:(?:should|must)\s+)?(?:stay|remain|be(?:\s+kept)?)\s+internal\b",
            sentence,
            re.IGNORECASE,
        ):
            return False
        if not has_metadata or re.match(
            r"\s*" + polite + r"(?:why|how|when|explain|describe|discuss|summarize)\b",
            sentence,
            re.IGNORECASE,
        ):
            continue
        # Match a direct request at a clause boundary, never a verb embedded in
        # a retrospective question such as "Why did you tell me ...?".
        requested = requested or any(
            re.match(metadata_request, clause, re.IGNORECASE)
            for clause in re.split(r",|\band\b", sentence, flags=re.IGNORECASE)
        )
        requested = requested or bool(
            re.match(
                r"\s*" + polite + r"(?:show|give|check|list|preview)\b.{0,120}"
                r"\b(?:birthdays?|anniversaries|celebrations?)\b.{0,120}\bincluding\s+"
                + modifiers
                + metadata_term,
                sentence,
                re.IGNORECASE,
            )
        )
    return bool(requested)


def pin_celebration_request(agent: Any, message: dict, content: Any) -> None:
    """Remember the real request outside transcript/synthetic message metadata."""
    provider = get_sydney_provider(agent)
    agent._sydney_celebration_request = (
        (message, content) if provider is not None and provider.is_available() else None
    )


def finalize_celebration_reply(agent: Any, response: Any, messages: Any) -> Any:
    """Hide only metadata proven by this private Sydney turn's celebration read.

    Tool payloads remain intact for review/draft binding and durable evidence.
    Nothing is inferred from arbitrary UUIDs, historical turns, or general tools.
    """
    provider = get_sydney_provider(agent)
    if (
        provider is None
        or not isinstance(response, str)
        or not response
        or not isinstance(messages, list)
        or not provider.is_available()
    ):
        return response
    pinned = getattr(agent, "_sydney_celebration_request", None)
    if isinstance(pinned, tuple) and len(pinned) == 2:
        user_message, request_content = pinned
        # Compression may retain or copy the real message, and append internal
        # role=user continuations. Resolve the pinned request, not the last user.
        start = next(
            (i for i, message in enumerate(messages) if message is user_message), -1
        )
        if start < 0:
            start = next(
                (
                    i
                    for i in range(len(messages) - 1, -1, -1)
                    if isinstance(messages[i], dict)
                    and messages[i].get("role") == "user"
                    and messages[i].get("content") == user_message.get("content")
                ),
                -1,
            )
    else:
        # Compatibility for isolated callers that do not run the Hermes loop.
        start = getattr(agent, "_persist_user_message_idx", None)
        if (
            not isinstance(start, int)
            or not 0 <= start < len(messages)
            or not isinstance(messages[start], dict)
            or messages[start].get("role") != "user"
        ):
            start = next(
                (
                    i
                    for i in range(len(messages) - 1, -1, -1)
                    if isinstance(messages[i], dict)
                    and messages[i].get("role") == "user"
                ),
                -1,
            )
        request_content = messages[start].get("content") if start >= 0 else None
    if (
        start < 0
        or not isinstance(messages[start], dict)
        or messages[start].get("role") != "user"
    ):
        return response
    if _requests_celebration_metadata(request_content):
        return response
    current = [
        message for message in messages[start + 1 :] if isinstance(message, dict)
    ]
    tool_names = {
        call.get("id"): call.get("function", {}).get("name")
        for message in current
        if message.get("role") == "assistant"
        for call in (message.get("tool_calls") or [])
        if isinstance(call, dict) and isinstance(call.get("function"), dict)
    }
    metadata: set[str] = set()
    for message in current:
        name = (
            message.get("name")
            or message.get("tool_name")
            or tool_names.get(message.get("tool_call_id"))
        )
        if message.get("role") == "tool" and name in {
            "command_contact_celebrations_preview",
            "mcp_atlas_backend_command_contact_celebrations_preview",
        }:
            metadata.update(_celebration_metadata(message.get("content")).values())
    if not metadata:
        return response
    if (
        current
        and current[-1].get("role") == "assistant"
        and not current[-1].get("tool_calls")
        and isinstance(current[-1].get("content"), str)
    ):
        # Hermes may already have removed secrets/reasoning from this message.
        # Clean its existing text independently; never restore raw model text.
        current[-1]["content"] = _clean_celebration_metadata(
            current[-1]["content"], metadata
        )
    return _clean_celebration_metadata(response, metadata)


def _clean_celebration_metadata(response: str, metadata: set[str]) -> str:
    values = {value for value in metadata if value.lower() in response.lower()}
    if not values:
        return response
    value_pattern = re.compile(
        "|".join(re.escape(value) for value in sorted(values)), re.IGNORECASE
    )
    kept: list[str | None] = []
    for line in response.splitlines():
        if not value_pattern.search(line):
            kept.append(line)
            continue
        remainder = value_pattern.sub("", line)
        plain = re.sub(r"[*_`|]", " ", remainder)
        plain = re.sub(r"^\s*(?:[-+>]\s*|\d+[.)]\s*)", "", plain)
        plain = re.sub(
            r"\b(?:audience|checksum|reference|ref)\b", "", plain, flags=re.IGNORECASE
        )
        if not plain.strip(" \t:=-,;()[]"):
            kept.append(None)
            continue
        # Keep business details on a mixed line. Remove labelled metadata spans,
        # then replace an unusually phrased exact value without guessing its text.
        for value in values:
            remainder_pattern = (
                r"(?:\(\s*)?(?:\*\*|__)?(?:audience[ _-]+)?(?:checksum|reference|ref)"
                r"(?:\*\*|__)?\s*[:=]\s*(?:\*\*|__)?\s*`?"
                + re.escape(value)
                + r"`?(?:\*\*|__)?(?:\s*\))?"
            )
            line = re.sub(remainder_pattern, "", line, flags=re.IGNORECASE)
        line = value_pattern.sub("kept internally", line)
        line = re.sub(r"[ \t]+([.!?,;])", r"\1", line)
        kept.append(re.sub(r"[ \t]{2,}", " ", line).rstrip())
    # Remove only scaffolding attached to a metadata row we actually removed.
    # A neighboring business row or unrelated reference ends the cleanup.
    for index, line in enumerate(kept):
        if line is not None:
            continue
        for previous in range(index - 1, -1, -1):
            candidate = kept[previous]
            if candidate is None:
                continue
            label = re.sub(r"[*_`|#:=+>\-]", " ", candidate)
            label = re.sub(r"^\s*\d+[.)]\s*", "", label)
            label = " ".join(label.split()).lower()
            if label and not re.fullmatch(
                r"(?:(?:internal|technical) )?(?:audience )?"
                r"(?:metadata|details|checksum|reference|ref)|field value",
                label,
            ):
                break
            kept[previous] = None
    cleaned = re.sub(
        r"\n{3,}", "\n\n", "\n".join(line for line in kept if line is not None)
    ).strip()
    if not cleaned:
        cleaned = "The celebration audience metadata is kept internally."
    return cleaned


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
    error_code = "model_terminal_failure"
    if terminal_tool_policy_response(agent):
        # A successfully delivered explanation is not a successful business
        # run. Hermes reports controlled halts as completed model turns.
        result["completed"] = False
        result["failed"] = True
        decision = getattr(agent, "_tool_guardrail_halt_decision", None)
        if isinstance(decision, SydneyToolPolicyHalt):
            error_code = decision.code
    response = finalize_celebration_reply(
        agent, result.get("final_response"), result.get("messages")
    )
    result["final_response"] = response
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
            provider.fail_active_run(error_code=error_code)
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
                error_code=error_code,
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
        "view",
    }
    if lowered in read_only_tools or tokens.intersection(read_markers):
        return "read_only"
    return "non_idempotent_write"


def _review_only_tool_is_allowed(tool_name: str) -> bool:
    """Allow only the reviewed read-tool registry during legacy recovery."""
    normalized = tool_name.casefold()
    if normalized.startswith(_ATLAS_MCP_TOOL_PREFIX):
        normalized = normalized.removeprefix(_ATLAS_MCP_TOOL_PREFIX)
    return normalized in _REVIEW_ONLY_READ_TOOLS


def _normal_business_tool_is_allowed(tool_name: str) -> bool:
    normalized = tool_name.casefold()
    if normalized == "skill_view":
        return True
    if normalized.startswith(_ATLAS_MCP_TOOL_PREFIX):
        normalized = normalized.removeprefix(_ATLAS_MCP_TOOL_PREFIX)
    return normalized in _ATLAS_BUSINESS_TOOLS


def _set_terminal_tool_policy(
    agent: Any,
    *,
    code: str,
    block_message: str,
    response: str,
    tool_name: str,
    count: int,
) -> None:
    if getattr(agent, "_tool_guardrail_halt_decision", None) is None:
        agent._tool_guardrail_halt_decision = SydneyToolPolicyHalt(
            code=code,
            message=block_message,
            tool_name=tool_name,
            count=max(0, count),
        )
    if not getattr(agent, "_sydney_terminal_tool_policy_response", None):
        agent._sydney_terminal_tool_policy_response = response


def terminal_tool_policy_response(agent: Any) -> str | None:
    response = getattr(agent, "_sydney_terminal_tool_policy_response", None)
    return response if isinstance(response, str) and response else None


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
    recovery_policy = provider.active_recovery_policy()
    if recovery_policy == "review_only" and not _review_only_tool_is_allowed(tool_name):
        provider.record_policy_denial(
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
        )
        return SydneyToolBeforeDecision(
            block_message=REVIEW_ONLY_RECOVERY_BLOCK_MESSAGE
        )
    if recovery_policy != "review_only" and not _normal_business_tool_is_allowed(
        tool_name
    ):
        provider.record_policy_denial(
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            policy="atlas_business_tools_only",
            error_code="normal_business_tool_blocked",
            side_effect_class=side_effect_class,
        )
        _set_terminal_tool_policy(
            agent,
            code="sydney_business_tool_policy",
            block_message=NORMAL_BUSINESS_TOOL_BLOCK_MESSAGE,
            response=(
                "I stopped this request because Sydney attempted a tool outside the "
                "approved business-tool lane. Nothing outside Atlas was executed."
            ),
            tool_name=tool_name,
            count=1,
        )
        return SydneyToolBeforeDecision(
            block_message=NORMAL_BUSINESS_TOOL_BLOCK_MESSAGE
        )
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
    if decision == "block_limit":
        count = receipt.get("invocation_count")
        limit = receipt.get("invocation_limit")
        safe_count = count if type(count) is int and count >= 0 else 0
        safe_limit = limit if type(limit) is int and limit > 0 else safe_count
        _set_terminal_tool_policy(
            agent,
            code="sydney_run_tool_limit",
            block_message=TOOL_INVOCATION_LIMIT_BLOCK_MESSAGE,
            response=(
                f"I stopped this request at Sydney's {safe_limit}-tool safety limit. "
                "I will use the results already gathered and will not keep retrying "
                "or ask you to reset."
            ),
            tool_name=tool_name,
            count=safe_count,
        )
        return SydneyToolBeforeDecision(
            block_message=TOOL_INVOCATION_LIMIT_BLOCK_MESSAGE
        )
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
