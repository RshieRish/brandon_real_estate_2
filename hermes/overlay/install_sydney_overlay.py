#!/usr/bin/env python3
"""Install Sydney into the exact approved Hermes source tree, atomically."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

OVERLAY_DIRECTORY = Path(__file__).resolve().parent
MANIFEST_PATH = (
    OVERLAY_DIRECTORY / "sydney_overlay_manifest.json"
    if (OVERLAY_DIRECTORY / "sydney_overlay_manifest.json").exists()
    else (
        OVERLAY_DIRECTORY / "atlas_backend_overlay_manifest.json"
        if (OVERLAY_DIRECTORY / "atlas_backend_overlay_manifest.json").exists()
        else OVERLAY_DIRECTORY / "manifest.json"
    )
)


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _git(source: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(source), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def _head(source: Path) -> str:
    return _git(source, "rev-parse", "HEAD").decode().strip()


def _baseline(source: Path, relative: str) -> bytes:
    return _git(source, "show", f"HEAD:{relative}")


def _status(source: Path) -> set[str]:
    raw = _git(source, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    paths: set[str] = set()
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        if len(entry) < 4:
            raise ValueError("could not parse Hermes source status")
        status = entry[:2]
        if status[0:1] in {b"R", b"C"} or status[1:2] in {b"R", b"C"}:
            raise ValueError("renamed or copied Hermes paths are not supported")
        paths.add(entry[3:].decode("utf-8"))
    return paths


def _replace_exact(contents: str, old: str, new: str, label: str) -> str:
    if new in contents:
        return contents
    if contents.count(old) != 1:
        raise ValueError(f"exact Hermes anchor mismatch: {label}")
    return contents.replace(old, new, 1)


def _patch_credential_pool(contents: str) -> str:
    old = (
        '    sec_match = re.search(r"retry\\s+(?:after\\s+)?(\\d+(?:\\.\\d+)?)'
        '\\s*(?:sec|secs|seconds|s\\b)", message, re.IGNORECASE)'
    )
    new = (
        "    # SYDNEY_RETRY_DELAY_TEXT\n"
        '    sec_match = re.search(r"retry\\s+(?:(?:in|after)\\s+)?'
        '(\\d+(?:\\.\\d+)?)\\s*(?:sec|secs|seconds|s\\b)", '
        "message, re.IGNORECASE)"
    )
    return _replace_exact(contents, old, new, "credential retry delay")


def _patch_gemini_schema(contents: str) -> str:
    helper_anchor = "\n\ndef sanitize_gemini_schema(schema: Any) -> Dict[str, Any]:"
    helper_replacement = '''

def _gemini_union_branch_is_self_contained(schema: Dict[str, Any]) -> bool:
    """Return whether Gemini can validate one ``anyOf`` branch in isolation."""

    # SYDNEY_GEMINI_CONDITIONAL_UNION_FALLBACK
    # Gemini validates every union branch as a standalone Schema. JSON Schema
    # conditionals commonly inherit ``type`` and ``properties`` from their
    # parent, which Gemini rejects before the model can run. Those conditionals
    # are still enforced by the tool handler, so omit only the unsupported
    # union while retaining the parent object and its property definitions.
    schema_type = str(schema.get("type") or "").lower()
    if not schema_type:
        return False
    if "properties" in schema and schema_type != "object":
        return False
    required = schema.get("required")
    if required is None:
        return True
    properties = schema.get("properties")
    return (
        schema_type == "object"
        and isinstance(required, list)
        and isinstance(properties, dict)
        and all(isinstance(name, str) and name in properties for name in required)
    )


def sanitize_gemini_schema(schema: Any) -> Dict[str, Any]:'''
    contents = _replace_exact(
        contents,
        helper_anchor,
        helper_replacement,
        "Gemini conditional union helper",
    )
    union_anchor = """\
        if key == "anyOf":
            if not isinstance(value, list):
                continue
            cleaned[key] = [
                sanitize_gemini_schema(item)
                for item in value
                if isinstance(item, dict)
            ]
            continue"""
    union_replacement = """\
        if key == "anyOf":
            if not isinstance(value, list):
                continue
            cleaned_union = [
                sanitize_gemini_schema(item)
                for item in value
                if isinstance(item, dict)
            ]
            if cleaned_union and all(
                _gemini_union_branch_is_self_contained(item)
                for item in cleaned_union
            ):
                cleaned[key] = cleaned_union
            continue"""
    return _replace_exact(
        contents,
        union_anchor,
        union_replacement,
        "Gemini conditional union sanitization",
    )


def _patch_agent_init(contents: str) -> str:
    old_guardrails = """\
        agent._tool_guardrails = ToolCallGuardrailController(
            ToolCallGuardrailConfig.from_mapping(
                _agent_cfg.get("tool_loop_guardrails", {})
            )
        )"""
    new_guardrails = """\
        # SYDNEY_TOOL_GUARDRAIL_CONFIG
        _sydney_guardrails = _agent_cfg.get("tool_guardrails")
        if isinstance(_sydney_guardrails, dict):
            _tool_guardrail_mapping = {
                "warnings_enabled": bool(_sydney_guardrails.get("enabled", True)),
                "hard_stop_enabled": bool(_sydney_guardrails.get("enabled", True)),
                "exact_failure_block_after": _sydney_guardrails.get("exact_failure_limit", 5),
                "same_tool_failure_halt_after": _sydney_guardrails.get("same_tool_failure_limit", 8),
                "no_progress_block_after": _sydney_guardrails.get("no_progress_limit", 5),
            }
        else:
            _tool_guardrail_mapping = _agent_cfg.get("tool_loop_guardrails", {})
        agent._tool_guardrails = ToolCallGuardrailController(
            ToolCallGuardrailConfig.from_mapping(_tool_guardrail_mapping)
        )"""
    contents = _replace_exact(
        contents, old_guardrails, new_guardrails, "tool guardrail config"
    )
    old_registration = "                _mp = _load_mem(_mem_provider_name)"
    new_registration = """\
                _mp = _load_mem(_mem_provider_name)
                # SYDNEY_MEMORY_REGISTRATION
                if _mp is None and _mem_provider_name == "sydney":
                    from plugins.memory.sydney import SydneyMemoryProvider
                    _mp = SydneyMemoryProvider()"""
    contents = _replace_exact(
        contents, old_registration, new_registration, "memory registration"
    )
    old_prefixed_history_tool = """\
    if agent._memory_manager and agent.tools is not None and (
        agent.enabled_toolsets is None or "memory" in agent.enabled_toolsets
    ):
        _existing_tool_names = {"""
    new_prefixed_history_tool = """\
    if agent._memory_manager and agent.tools is not None and (
        agent.enabled_toolsets is None or "memory" in agent.enabled_toolsets
    ):
        if _mem_provider_name == "sydney":
            # SYDNEY_MCP_HISTORY_TOOL_HIDE
            # MCP registry names are prefixed by Hermes. Hide the authenticated
            # backend variant from the model because the provider-owned tool
            # injects identity_id and exposes the bounded caller-safe schema.
            _sydney_prefixed_history_tool = (
                "mcp_atlas_backend_context_history_search"
            )
            agent.tools = [
                tool
                for tool in agent.tools
                if tool.get("function", {}).get("name")
                != _sydney_prefixed_history_tool
            ]
            agent.valid_tool_names.discard(_sydney_prefixed_history_tool)
        _existing_tool_names = {"""
    contents = _replace_exact(
        contents,
        old_prefixed_history_tool,
        new_prefixed_history_tool,
        "Sydney prefixed MCP history tool",
    )
    compression_limit_anchor = "    agent.compression_enabled = compression_enabled"
    compression_limit_replacement = """\
    agent.compression_enabled = compression_enabled
    # SYDNEY_COMPRESSION_TOKEN_LIMIT
    try:
        _sydney_compression_tokens = int(
            _compression_cfg.get("threshold_tokens", 0) or 0
        )
    except (TypeError, ValueError):
        _sydney_compression_tokens = 0
    if _sydney_compression_tokens > 0 and hasattr(
        agent.context_compressor, "threshold_tokens"
    ):
        _sydney_context_length = int(
            getattr(agent.context_compressor, "context_length", 0) or 0
        )
        if _sydney_context_length > 0:
            _sydney_compression_tokens = min(
                _sydney_compression_tokens, _sydney_context_length
            )
        agent.context_compressor.threshold_tokens = max(
            MINIMUM_CONTEXT_LENGTH, _sydney_compression_tokens
        )
        if hasattr(agent.context_compressor, "tail_token_budget"):
            agent.context_compressor.tail_token_budget = int(
                agent.context_compressor.threshold_tokens
                * agent.context_compressor.summary_target_ratio
            )"""
    contents = _replace_exact(
        contents,
        compression_limit_anchor,
        compression_limit_replacement,
        "Sydney compression token limit",
    )
    contents = _replace_exact(
        contents,
        '    compression_target_ratio = float(_compression_cfg.get("target_ratio", 0.20))',
        '    compression_target_ratio = float(_compression_cfg.get("target", _compression_cfg.get("target_ratio", 0.20)))',
        "compression target alias",
    )
    contents = _replace_exact(
        contents,
        '    compression_protect_last = int(_compression_cfg.get("protect_last_n", 20))',
        '    compression_protect_last = int(_compression_cfg.get("protect_last", _compression_cfg.get("protect_last_n", 20)))',
        "compression tail alias",
    )
    return _replace_exact(
        contents,
        "    from agent.model_metadata import MINIMUM_CONTEXT_LENGTH\n    _ctx =",
        "    # MINIMUM_CONTEXT_LENGTH is imported at module scope. Keeping a "
        "function-local import here would make the earlier Sydney compression "
        "limit access an unbound local.\n    _ctx =",
        "compression floor import scope",
    )


def _patch_gateway_run(contents: str) -> str:
    reply_helper_import_anchor = """\
    _reply_anchor_for_event,
    merge_pending_message_event,"""
    reply_helper_import_replacement = """\
    _reply_anchor_for_event,
    _sydney_telegram_numeric_reply_anchor,
    merge_pending_message_event,"""
    contents = _replace_exact(
        contents,
        reply_helper_import_anchor,
        reply_helper_import_replacement,
        "GatewayRunner Telegram numeric reply helper import",
    )
    thread_anchor = '            anchor = reply_to_message_id or getattr(source, "message_id", None)'
    thread_replacement = """\
            # SYDNEY_GATEWAY_RUN_TELEGRAM_NUMERIC_REPLY_ANCHOR
            anchor = _sydney_telegram_numeric_reply_anchor(
                reply_to_message_id or getattr(source, "message_id", None)
            )"""
    contents = _replace_exact(
        contents,
        thread_anchor,
        thread_replacement,
        "GatewayRunner Telegram numeric reply anchor",
    )
    startup = "        self._schedule_resume_pending_sessions()"
    startup_replacement = """\
        self._schedule_resume_pending_sessions()

        # SYDNEY_CONTINUATION_WATCHER
        try:
            from gateway.sydney_gateway import sydney_continuation_watcher
            _sydney_task = asyncio.create_task(sydney_continuation_watcher(self))
            self._background_tasks.add(_sydney_task)
            _sydney_task.add_done_callback(self._background_tasks.discard)
        except Exception as _sydney_start_error:
            logger.warning("Sydney continuation watcher did not start: %s", _sydney_start_error)"""
    contents = _replace_exact(
        contents, startup, startup_replacement, "continuation watcher startup"
    )
    run_signature_anchor = """\
        event_message_id: Optional[str] = None,
        channel_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:"""
    run_signature_replacement = """\
        event_message_id: Optional[str] = None,
        channel_prompt: Optional[str] = None,
        _sydney_internal: bool = False,
        _sydney_persisted_message: Optional[str] = None,
    ) -> Dict[str, Any]:"""
    contents = _replace_exact(
        contents,
        run_signature_anchor,
        run_signature_replacement,
        "continuation run scope",
    )
    persistence_anchor = """\
                _conversation_kwargs = {
                    "conversation_history": agent_history,
                    "task_id": session_id,
                }
                if observed_group_context:
                    _conversation_kwargs["persist_user_message"] = message"""
    persistence_replacement = """\
                _conversation_kwargs = {
                    "conversation_history": agent_history,
                    "task_id": session_id,
                }
                if observed_group_context:
                    _conversation_kwargs["persist_user_message"] = message
                if _sydney_internal:
                    # The model receives recovered durable context plus the
                    # continuation marker, but state.db persists only the marker.
                    _conversation_kwargs["persist_user_message"] = str(
                        _sydney_persisted_message or ""
                    )"""
    contents = _replace_exact(
        contents,
        persistence_anchor,
        persistence_replacement,
        "internal continuation persistence",
    )
    run_call = "                result = agent.run_conversation(_api_run_message, **_conversation_kwargs)"
    run_replacement = """\
                # SYDNEY_INBOUND_SPOOL_BEFORE_MODEL
                from agent.sydney_runtime import record_inbound_before_model
                if event_message_id:
                    _sydney_message_id = str(event_message_id)
                else:
                    import hashlib as _sydney_hashlib
                    _sydney_message_id = _sydney_hashlib.sha256(
                        f"{source.platform.value}:{source.chat_id}:{session_id}:{message}".encode()
                    ).hexdigest()
                # SYDNEY_RUN_LEASE_GATE
                _sydney_has_run_lease = record_inbound_before_model(
                    agent,
                    platform_message_id=_sydney_message_id,
                    content=message,
                    internal=_sydney_internal,
                )
                # SYDNEY_ACCEPTED_ACK_BEFORE_MODEL
                from agent.sydney_runtime import (
                    cancel_inbound_acknowledgement,
                    confirm_inbound_acknowledgement,
                    stage_inbound_acknowledgement,
                )
                _sydney_ack = stage_inbound_acknowledgement(agent)
                if _sydney_ack:
                    if _status_adapter and _run_still_current():
                        _sydney_ack_future = safe_schedule_threadsafe(
                            _status_adapter.send(
                                _status_chat_id,
                                _sydney_ack,
                                metadata=_status_thread_metadata,
                            ),
                            _loop_for_step,
                            logger=logger,
                            log_message="Sydney accepted acknowledgement send error",
                        )
                        if _sydney_ack_future is None:
                            cancel_inbound_acknowledgement(agent, _sydney_ack)
                        else:
                            try:
                                _sydney_ack_result = _sydney_ack_future.result(timeout=20)
                            except Exception:
                                # The provider may have accepted the send even when
                                # its receipt was lost. Commit an ambiguous marker
                                # so a restart never sends the acknowledgement twice.
                                try:
                                    confirm_inbound_acknowledgement(
                                        agent,
                                        _sydney_ack,
                                        ambiguous=True,
                                    )
                                except Exception:
                                    pass
                            else:
                                if getattr(_sydney_ack_result, "success", False):
                                    try:
                                        confirm_inbound_acknowledgement(
                                            agent,
                                            _sydney_ack,
                                            ambiguous=False,
                                        )
                                    except Exception:
                                        pass
                                else:
                                    cancel_inbound_acknowledgement(
                                        agent,
                                        _sydney_ack,
                                    )
                    else:
                        cancel_inbound_acknowledgement(agent, _sydney_ack)
                if not _sydney_has_run_lease:
                    from agent.sydney_runtime import deferred_inbound_response
                    _sydney_saved_message = deferred_inbound_response(agent)
                    _sydney_terminal_replay = bool(
                        getattr(agent, "_sydney_terminal_replay_state", None)
                    )
                    result = {
                        "final_response": _sydney_saved_message,
                        "messages": agent_history,
                        "api_calls": 0,
                        "completed": _sydney_terminal_replay,
                        "deferred": not _sydney_terminal_replay,
                    }
                else:
                    result = agent.run_conversation(
                        _api_run_message, **_conversation_kwargs
                    )
                    if result.get("compression_exhausted"):
                        # SYDNEY_COMPRESSION_EXHAUSTION_CONTINUATION
                        from agent.sydney_runtime import defer_compression_exhaustion
                        _sydney_continuation = defer_compression_exhaustion(agent)
                        if _sydney_continuation:
                            result["final_response"] = _sydney_continuation
                            result["deferred"] = True
                            result["sydney_continuation_staged"] = True"""
    contents = _replace_exact(
        contents, run_call, run_replacement, "inbound spool before model"
    )
    outcome_anchor = """\
                "completed": result_holder[0].get("completed") if result_holder[0] else None,
                "interrupted": result_holder[0].get("interrupted", False) if result_holder[0] else False,"""
    outcome_replacement = """\
                "completed": result_holder[0].get("completed") if result_holder[0] else None,
                # SYDNEY_DURABLE_OUTCOME_PROPAGATION
                "deferred": result_holder[0].get("deferred", False) if result_holder[0] else False,
                "failed": result_holder[0].get("failed", False) if result_holder[0] else False,
                "compression_exhausted": result_holder[0].get("compression_exhausted", False) if result_holder[0] else False,
                "sydney_continuation_staged": result_holder[0].get("sydney_continuation_staged", False) if result_holder[0] else False,
                "interrupted": result_holder[0].get("interrupted", False) if result_holder[0] else False,"""
    contents = _replace_exact(
        contents,
        outcome_anchor,
        outcome_replacement,
        "durable outcome propagation",
    )
    streaming_anchor = """\
            _want_stream_deltas = _streaming_enabled
            _want_interim_messages = interim_assistant_messages_enabled
            _want_interim_consumer = _want_interim_messages"""
    streaming_replacement = """\
            _want_stream_deltas = _streaming_enabled
            _want_interim_messages = interim_assistant_messages_enabled
            _want_interim_consumer = _want_interim_messages

            # SYDNEY_DURABLE_STREAMING_DISABLED
            # Exactly-once retry requires the durable outbound marker to exist
            # before Telegram sees any final content. The normal final send is
            # staged below; token streaming and interim assistant previews can
            # cross the platform boundary before that result exists, so disable
            # them only for the exact private Sydney retry identity.
            _sydney_retry_delivery = os.environ.get(
                "SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED", ""
            ).lower() in {"1", "true", "yes", "on"}
            _sydney_delivery_user = os.environ.get(
                "SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID", ""
            ).strip()
            _sydney_delivery_chat = os.environ.get(
                "SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID", ""
            ).strip()
            if (
                _sydney_retry_delivery
                and source.platform == Platform.TELEGRAM
                and str(source.user_id or "") == _sydney_delivery_user
                and str(source.chat_id or "") == _sydney_delivery_chat
            ):
                _want_stream_deltas = False
                _want_interim_messages = False
                _want_interim_consumer = False"""
    contents = _replace_exact(
        contents,
        streaming_anchor,
        streaming_replacement,
        "durable Sydney streaming boundary",
    )
    result_anchor = """\
                channel_prompt=event.channel_prompt,
            )

            # Stop persistent typing indicator now that the agent is done"""
    result_replacement = """\
                channel_prompt=event.channel_prompt,
                _sydney_internal=bool(getattr(event, "internal", False)),
                _sydney_persisted_message=str(getattr(event, "text", "") or ""),
            )

            # Preserve the innermost queued turn's delivery key for the outer
            # adapter send boundary.
            if agent_result.get("_sydney_delivery_key"):
                event._sydney_delivery_key = agent_result["_sydney_delivery_key"]

            # Stop persistent typing indicator now that the agent is done"""
    contents = _replace_exact(
        contents,
        result_anchor,
        result_replacement,
        "delivery key propagation",
    )
    queued_anchor = """\
                    first_response = result.get("final_response", "")
                    if first_response and not _already_streamed:
                        try:
                            logger.info(
                                "Queued follow-up for session %s: final stream delivery not confirmed; sending first response before continuing.",
                                session_key or "?",
                            )
                            await adapter.send(
                                source.chat_id,
                                first_response,
                                metadata=_status_thread_metadata,
                            )
                        except Exception as e:
                            logger.warning("Failed to send first response before queued message: %s", e)
                    elif first_response:
                        logger.info(
                            "Queued follow-up for session %s: skipping resend because final streamed delivery was confirmed.",
                            session_key or "?",
                        )"""
    queued_replacement = """\
                    first_response = result.get("final_response", "")
                    # SYDNEY_QUEUED_DELIVERY_CONFIRMATION
                    from agent.sydney_runtime import (
                        record_delivery_by_key as _sydney_record_delivery_by_key,
                        stage_run_outcome as _sydney_stage_run_outcome,
                    )
                    _sydney_first_agent = agent_holder[0]
                    _sydney_first_key = getattr(
                        _sydney_first_agent, "_sydney_delivery_key", None
                    )
                    _sydney_first_delivered = bool(_already_streamed)
                    _sydney_first_durable = False
                    if first_response and _sydney_first_agent is not None:
                        _sydney_first_result = dict(result)
                        _sydney_first_result["already_sent"] = _already_streamed
                        _sydney_first_durable = bool(
                            _sydney_stage_run_outcome(
                                _sydney_first_agent, _sydney_first_result
                            )
                        )
                        first_response = str(_sydney_first_result.get("final_response") or "")
                    if first_response and not _already_streamed:
                        try:
                            logger.info(
                                "Queued follow-up for session %s: final stream delivery not confirmed; sending first response before continuing.",
                                session_key or "?",
                            )
                            _sydney_first_metadata = dict(
                                _status_thread_metadata or {}
                            )
                            if _sydney_first_durable:
                                _sydney_first_metadata[
                                    "sydney_durable_delivery"
                                ] = True
                            _sydney_first_send = await adapter.send(
                                source.chat_id,
                                first_response,
                                metadata=_sydney_first_metadata,
                            )
                            _sydney_first_delivered = bool(
                                getattr(_sydney_first_send, "success", False)
                            )
                        except Exception as e:
                            logger.warning("Failed to send first response before queued message: %s", e)
                    elif first_response:
                        logger.info(
                            "Queued follow-up for session %s: skipping resend because final streamed delivery was confirmed.",
                            session_key or "?",
                        )
                    if first_response:
                        _sydney_record_delivery_by_key(
                            _sydney_first_key,
                            delivered=_sydney_first_delivered,
                        )"""
    contents = _replace_exact(
        contents,
        queued_anchor,
        queued_replacement,
        "queued delivery confirmation",
    )
    queued_scope_anchor = """\
                next_message_id = None
                next_channel_prompt = None
                if pending_event is not None:"""
    queued_scope_replacement = """\
                next_message_id = None
                next_channel_prompt = None
                next_sydney_internal = False
                next_sydney_persisted_message = None
                if pending_event is not None:"""
    contents = _replace_exact(
        contents,
        queued_scope_anchor,
        queued_scope_replacement,
        "queued continuation scope defaults",
    )
    queued_event_scope_anchor = """\
                    next_message_id = self._reply_anchor_for_event(pending_event)
                    next_channel_prompt = getattr(pending_event, "channel_prompt", None)"""
    queued_event_scope_replacement = """\
                    next_message_id = self._reply_anchor_for_event(pending_event)
                    next_channel_prompt = getattr(pending_event, "channel_prompt", None)
                    next_sydney_internal = bool(
                        getattr(pending_event, "internal", False)
                    )
                    next_sydney_persisted_message = str(
                        getattr(pending_event, "text", "") or ""
                    )"""
    contents = _replace_exact(
        contents,
        queued_event_scope_anchor,
        queued_event_scope_replacement,
        "queued continuation event scope",
    )
    queued_run_call_anchor = """\
                    event_message_id=next_message_id,
                    channel_prompt=next_channel_prompt,
                )"""
    queued_run_call_replacement = """\
                    event_message_id=next_message_id,
                    channel_prompt=next_channel_prompt,
                    _sydney_internal=next_sydney_internal,
                    _sydney_persisted_message=next_sydney_persisted_message,
                )"""
    contents = _replace_exact(
        contents,
        queued_run_call_anchor,
        queued_run_call_replacement,
        "queued continuation run arguments",
    )
    compression_reset_anchor = """\
            if agent_result.get("compression_exhausted") and session_entry and session_key:
                logger.info(
                    "Auto-resetting session %s after compression exhaustion.",
                    session_entry.session_id,
                )
                self.session_store.reset_session(session_key)
                self._evict_cached_agent(session_key)
                self._session_model_overrides.pop(session_key, None)
                self._set_session_reasoning_override(session_key, None)
                if hasattr(self, "_pending_model_notes"):
                    self._pending_model_notes.pop(session_key, None)
                response = (response or "") + (
                    "\\n\\n🔄 Session auto-reset — the conversation exceeded the "
                    "maximum context size and could not be compressed further. "
                    "Your next message will start a fresh session."
                )"""
    compression_reset_replacement = """\
            if agent_result.get("compression_exhausted") and session_entry and session_key:
                logger.info(
                    "Auto-resetting session %s after compression exhaustion.",
                    session_entry.session_id,
                )
                # SYDNEY_LINEAGE_AWARE_COMPRESSION_RESET
                _sydney_old_session_id = session_entry.session_id
                _sydney_continuation_entry = self.session_store.reset_session(
                    session_key
                )
                if agent_result.get("sydney_continuation_staged"):
                    try:
                        if agent._memory_manager and _sydney_continuation_entry:
                            agent._memory_manager.on_session_switch(
                                _sydney_continuation_entry.session_id,
                                parent_session_id=_sydney_old_session_id,
                                reset=False,
                                reason="compression_exhausted",
                            )
                    except Exception as _sydney_lineage_error:
                        logger.warning(
                            "Sydney compression lineage update failed: %s",
                            _sydney_lineage_error,
                        )
                self._evict_cached_agent(session_key)
                self._session_model_overrides.pop(session_key, None)
                self._set_session_reasoning_override(session_key, None)
                if hasattr(self, "_pending_model_notes"):
                    self._pending_model_notes.pop(session_key, None)
                if not agent_result.get("sydney_continuation_staged"):
                    response = (response or "") + (
                        "\\n\\n🔄 Session auto-reset — the conversation exceeded the "
                        "maximum context size and could not be compressed further. "
                        "Your next message will start a fresh session."
                    )"""
    contents = _replace_exact(
        contents,
        compression_reset_anchor,
        compression_reset_replacement,
        "lineage-aware compression reset",
    )
    final_stage_anchor = """\
        # Schedule deletion of tracked temporary progress bubbles after the
        # final response lands."""
    final_stage_replacement = """\
        # SYDNEY_FINAL_DELIVERY_STAGE
        # This runs after streaming/edit confirmation and before the result is
        # returned to the adapter's final send boundary.
        _sydney_final_agent = agent_holder[0]
        if _sydney_final_agent is not None and isinstance(response, dict):
            from agent.sydney_runtime import stage_run_outcome as _sydney_stage_run_outcome
            _sydney_stage_run_outcome(_sydney_final_agent, response)
            response["_sydney_delivery_key"] = getattr(
                _sydney_final_agent, "_sydney_delivery_key", None
            )

        # Schedule deletion of tracked temporary progress bubbles after the
        # final response lands."""
    return _replace_exact(
        contents,
        final_stage_anchor,
        final_stage_replacement,
        "final delivery stage",
    )


def _patch_gateway_base(contents: str) -> str:
    reply_helper_anchor = "def _thread_metadata_for_source("
    reply_helper_replacement = """\
def _sydney_telegram_numeric_reply_anchor(value) -> str | None:
    # SYDNEY_TELEGRAM_NUMERIC_REPLY_ANCHOR
    # Telegram reply_to_message_id accepts only a positive integer. Durable
    # continuation IDs are local ledger keys, never Telegram message IDs.
    raw = str(value or "").strip()
    if not raw.isascii() or not raw.isdigit() or int(raw) < 1:
        return None
    return raw


def _thread_metadata_for_source("""
    contents = _replace_exact(
        contents,
        reply_helper_anchor,
        reply_helper_replacement,
        "Telegram numeric reply helper",
    )
    thread_anchor = (
        '        anchor = reply_to_message_id or getattr(source, "message_id", None)'
    )
    thread_replacement = """\
        anchor = _sydney_telegram_numeric_reply_anchor(
            reply_to_message_id or getattr(source, "message_id", None)
        )"""
    contents = _replace_exact(
        contents,
        thread_anchor,
        thread_replacement,
        "Telegram thread metadata reply anchor",
    )
    reply_anchor = """\
def _reply_anchor_for_event(event) -> str | None:
    \"\"\"Return reply_to id for platforms that need reply semantics.

    Telegram forum/supergroup topics should be routed by topic metadata, not by
    replying to the triggering message. Hermes-created Telegram private-chat
    topic lanes prefer replying to the triggering user message so the answer
    stays attached to the active lane; synthetic/resumed sends fall back to
    ``direct_messages_topic_id`` metadata when no message id is available.
    \"\"\"
    source = getattr(event, \"source\", None)
    platform = _platform_name(getattr(source, \"platform\", None))
    thread_id = getattr(source, \"thread_id\", None)
    if platform == \"telegram\" and thread_id and getattr(source, \"chat_type\", None) == \"dm\":
        # Reply to the triggering user message. Replying to Telegram's earlier
        # topic seed/anchor can render the bot response outside the active lane.
        return getattr(event, \"message_id\", None) or getattr(event, \"reply_to_message_id\", None)
    if platform == \"telegram\" and thread_id:
        return None
    if platform == \"feishu\" and thread_id and getattr(event, \"reply_to_message_id\", None):
        return getattr(event, \"reply_to_message_id\", None)
    return getattr(event, \"message_id\", None)
"""
    reply_replacement = """\
def _reply_anchor_for_event(event) -> str | None:
    \"\"\"Return reply_to id for platforms that need reply semantics.

    Telegram forum/supergroup topics should be routed by topic metadata, not by
    replying to the triggering message. Hermes-created Telegram private-chat
    topic lanes prefer replying to the triggering user message so the answer
    stays attached to the active lane; synthetic/resumed sends fall back to
    ``direct_messages_topic_id`` metadata when no message id is available.
    \"\"\"
    source = getattr(event, \"source\", None)
    platform = _platform_name(getattr(source, \"platform\", None))
    thread_id = getattr(source, \"thread_id\", None)
    if platform == \"telegram\" and thread_id and getattr(source, \"chat_type\", None) == \"dm\":
        # Reply to the triggering user message. Replying to Telegram's earlier
        # topic seed/anchor can render the bot response outside the active lane.
        return _sydney_telegram_numeric_reply_anchor(
            getattr(event, \"message_id\", None)
            or getattr(event, \"reply_to_message_id\", None)
        )
    if platform == \"telegram\" and thread_id:
        return None
    if platform == \"feishu\" and thread_id and getattr(event, \"reply_to_message_id\", None):
        return getattr(event, \"reply_to_message_id\", None)
    anchor = getattr(event, \"message_id\", None)
    if platform == \"telegram\":
        return _sydney_telegram_numeric_reply_anchor(anchor)
    return anchor
"""
    contents = _replace_exact(
        contents,
        reply_anchor,
        reply_replacement,
        "Telegram event reply anchor",
    )
    durable_metadata_anchor = """\
        _thread_metadata = _thread_metadata_for_source(event.source, _reply_anchor_for_event(event))
        _keep_typing_kwargs = {"metadata": _thread_metadata}"""
    durable_metadata_replacement = """\
        _thread_metadata = _thread_metadata_for_source(event.source, _reply_anchor_for_event(event))
        if getattr(event, "_sydney_delivery_key", None):
            # SYDNEY_DURABLE_DELIVERY_METADATA
            _thread_metadata = dict(_thread_metadata or {})
            _thread_metadata["sydney_durable_delivery"] = True
        _keep_typing_kwargs = {"metadata": _thread_metadata}"""
    contents = _replace_exact(
        contents,
        durable_metadata_anchor,
        durable_metadata_replacement,
        "durable delivery metadata",
    )
    post_handler_metadata_anchor = """\
            # Call the handler (this can take a while with tool calls)
            response = await self._message_handler(event)

            # Slash-command handlers may return an EphemeralReply sentinel to"""
    post_handler_metadata_replacement = """\
            # Call the handler (this can take a while with tool calls)
            response = await self._message_handler(event)
            if getattr(event, "_sydney_delivery_key", None):
                # SYDNEY_DURABLE_DELIVERY_METADATA_REFRESH
                # GatewayRunner assigns the key while the handler runs. Refresh
                # metadata here so the actual response send uses one attempt.
                _thread_metadata = dict(_thread_metadata or {})
                _thread_metadata["sydney_durable_delivery"] = True

            # Slash-command handlers may return an EphemeralReply sentinel to"""
    contents = _replace_exact(
        contents,
        post_handler_metadata_anchor,
        post_handler_metadata_replacement,
        "post-handler durable delivery metadata",
    )
    retry_anchor = """\
        if result.success:
            return result

        error_str = result.error or ""
        is_network = result.retryable or self._is_retryable_error(error_str)"""
    retry_replacement = """\
        if result.success:
            return result
        if metadata and metadata.get("sydney_durable_delivery"):
            # SYDNEY_AMBIGUOUS_DELIVERY_SINGLE_ATTEMPT
            # A transport failure after a Telegram POST cannot prove whether
            # the final response landed. Preserve the staged ledger and do not
            # emit a duplicate retry or delivery-failure notice.
            return result

        error_str = result.error or ""
        is_network = result.retryable or self._is_retryable_error(error_str)"""
    contents = _replace_exact(
        contents,
        retry_anchor,
        retry_replacement,
        "ambiguous durable delivery retry",
    )
    tracking_anchor = """\
        delivery_attempted = False
        delivery_succeeded = False

        def _record_delivery(result):
            nonlocal delivery_attempted, delivery_succeeded
            if result is None:
                return
            delivery_attempted = True
            if getattr(result, "success", False):
                delivery_succeeded = True"""
    tracking_replacement = """\
        delivery_attempted = False
        delivery_succeeded = True

        def _record_delivery(result):
            nonlocal delivery_attempted, delivery_succeeded
            delivery_attempted = True
            delivery_succeeded = delivery_succeeded and bool(
                getattr(result, "success", False)
            )"""
    contents = _replace_exact(
        contents,
        tracking_anchor,
        tracking_replacement,
        "delivery result aggregation",
    )
    tts_anchor = """\
                        _tts_caption_delivered = bool(
                            telegram_tts_caption and getattr(tts_result, "success", False)
                        )"""
    tts_replacement = """\
                        _record_delivery(tts_result)
                        _tts_caption_delivered = bool(
                            telegram_tts_caption and getattr(tts_result, "success", False)
                        )"""
    contents = _replace_exact(
        contents,
        tts_anchor,
        tts_replacement,
        "TTS delivery aggregation",
    )
    image_anchor = """\
                if images:
                    logger.info("[%s] Extracted %d image(s) to send as attachments", self.name, len(images))
                    try:
                        await self.send_multiple_images(
                            chat_id=event.source.chat_id,
                            images=images,
                            metadata=_thread_metadata,
                            human_delay=human_delay,
                        )
                    except Exception as batch_err:
                        logger.warning("[%s] Error batching images: %s", self.name, batch_err, exc_info=True)"""
    image_replacement = """\
                if images:
                    logger.info("[%s] Extracted %d image(s) to send as attachments", self.name, len(images))
                    if getattr(event, "_sydney_delivery_key", None):
                        # SYDNEY_DURABLE_IMAGE_DELIVERY
                        # Batch helpers do not return per-image receipts and may
                        # swallow partial failures. Durable runs use the direct
                        # SendResult-returning methods so every required image is
                        # included in the final acknowledgement.
                        from urllib.parse import unquote as _sydney_unquote
                        for _sydney_image_url, _sydney_alt_text in images:
                            try:
                                if _sydney_image_url.startswith("file://"):
                                    _sydney_image_result = await self.send_image_file(
                                        chat_id=event.source.chat_id,
                                        image_path=_sydney_unquote(_sydney_image_url[7:]),
                                        caption=_sydney_alt_text or None,
                                        metadata=_thread_metadata,
                                    )
                                elif self._is_animation_url(_sydney_image_url):
                                    _sydney_image_result = await self.send_animation(
                                        chat_id=event.source.chat_id,
                                        animation_url=_sydney_image_url,
                                        caption=_sydney_alt_text or None,
                                        metadata=_thread_metadata,
                                    )
                                else:
                                    _sydney_image_result = await self.send_image(
                                        chat_id=event.source.chat_id,
                                        image_url=_sydney_image_url,
                                        caption=_sydney_alt_text or None,
                                        metadata=_thread_metadata,
                                    )
                                _record_delivery(_sydney_image_result)
                            except Exception as _sydney_image_error:
                                _record_delivery(False)
                                logger.warning(
                                    "[%s] Error sending durable image: %s",
                                    self.name,
                                    _sydney_image_error,
                                    exc_info=True,
                                )
                    else:
                        try:
                            await self.send_multiple_images(
                                chat_id=event.source.chat_id,
                                images=images,
                                metadata=_thread_metadata,
                                human_delay=human_delay,
                            )
                        except Exception as batch_err:
                            logger.warning("[%s] Error batching images: %s", self.name, batch_err, exc_info=True)"""
    contents = _replace_exact(
        contents,
        image_anchor,
        image_replacement,
        "durable URL image delivery aggregation",
    )
    local_image_anchor = """\
                if _image_paths:
                    try:
                        _batch = [(f"file://{_quote(p)}", "") for p in _image_paths]
                        await self.send_multiple_images(
                            chat_id=event.source.chat_id,
                            images=_batch,
                            metadata=_thread_metadata,
                            human_delay=human_delay,
                        )
                    except Exception as batch_err:
                        logger.warning("[%s] Error batching images: %s", self.name, batch_err, exc_info=True)"""
    local_image_replacement = """\
                if _image_paths:
                    if getattr(event, "_sydney_delivery_key", None):
                        for _sydney_image_path in _image_paths:
                            try:
                                _sydney_image_result = await self.send_image_file(
                                    chat_id=event.source.chat_id,
                                    image_path=_sydney_image_path,
                                    metadata=_thread_metadata,
                                )
                                _record_delivery(_sydney_image_result)
                            except Exception as _sydney_image_error:
                                _record_delivery(False)
                                logger.warning(
                                    "[%s] Error sending durable local image: %s",
                                    self.name,
                                    _sydney_image_error,
                                    exc_info=True,
                                )
                    else:
                        try:
                            _batch = [(f"file://{_quote(p)}", "") for p in _image_paths]
                            await self.send_multiple_images(
                                chat_id=event.source.chat_id,
                                images=_batch,
                                metadata=_thread_metadata,
                                human_delay=human_delay,
                            )
                        except Exception as batch_err:
                            logger.warning("[%s] Error batching images: %s", self.name, batch_err, exc_info=True)"""
    contents = _replace_exact(
        contents,
        local_image_anchor,
        local_image_replacement,
        "durable local image delivery aggregation",
    )
    media_result_anchor = """\
                        if not media_result.success:
                            logger.warning("[%s] Failed to send media (%s): %s", self.name, ext, media_result.error)
                    except Exception as media_err:
                        logger.warning("[%s] Error sending media: %s", self.name, media_err)"""
    media_result_replacement = """\
                        _record_delivery(media_result)
                        if not media_result.success:
                            logger.warning("[%s] Failed to send media (%s): %s", self.name, ext, media_result.error)
                    except Exception as media_err:
                        _record_delivery(False)
                        logger.warning("[%s] Error sending media: %s", self.name, media_err)"""
    contents = _replace_exact(
        contents,
        media_result_anchor,
        media_result_replacement,
        "media delivery aggregation",
    )
    local_file_anchor = """\
                        if ext in _VIDEO_EXTS:
                            await self.send_video(
                                chat_id=event.source.chat_id,
                                video_path=file_path,
                                metadata=_thread_metadata,
                            )
                        else:
                            await self.send_document(
                                chat_id=event.source.chat_id,
                                file_path=file_path,
                                metadata=_thread_metadata,
                            )
                    except Exception as file_err:
                        logger.error("[%s] Error sending local file %s: %s", self.name, file_path, file_err)"""
    local_file_replacement = """\
                        if ext in _VIDEO_EXTS:
                            file_result = await self.send_video(
                                chat_id=event.source.chat_id,
                                video_path=file_path,
                                metadata=_thread_metadata,
                            )
                        else:
                            file_result = await self.send_document(
                                chat_id=event.source.chat_id,
                                file_path=file_path,
                                metadata=_thread_metadata,
                            )
                        _record_delivery(file_result)
                    except Exception as file_err:
                        _record_delivery(False)
                        logger.error("[%s] Error sending local file %s: %s", self.name, file_path, file_err)"""
    contents = _replace_exact(
        contents,
        local_file_anchor,
        local_file_replacement,
        "local file delivery aggregation",
    )
    delivery_anchor = """\
            # Determine overall success for the processing hook
            processing_ok = delivery_succeeded if delivery_attempted else not bool(response)
            await self._run_processing_hook("""
    delivery_replacement = """\
            # Determine overall success for the processing hook
            processing_ok = delivery_succeeded if delivery_attempted else not bool(response)

            # SYDNEY_DELIVERY_CONFIRMATION
            # Model completion is not run completion: acknowledge the durable
            # run only after the final Telegram response actually lands. A
            # confirmed stream sets already_sent on the staged result.
            try:
                from agent.sydney_runtime import record_delivery_outcome as _sydney_delivery_outcome
                _sydney_delivery_outcome(
                    event,
                    delivered=bool(delivery_attempted and delivery_succeeded),
                )
            except Exception as _sydney_delivery_error:
                logger.warning(
                    "Sydney delivery acknowledgement failed: %s",
                    _sydney_delivery_error,
                )
            await self._run_processing_hook("""
    contents = _replace_exact(
        contents,
        delivery_anchor,
        delivery_replacement,
        "delivery confirmation",
    )
    execution_release_anchor = """\
        finally:
            # Fire any one-shot post-delivery callback registered for this
            # session (e.g. deferred background-review notifications)."""
    execution_release_replacement = """\
        finally:
            # SYDNEY_EXECUTION_LEASE_RELEASE
            # A persisted active run is not proof that its model task survived.
            # Release process-local renewal ownership on every handler exit.
            try:
                from agent.sydney_runtime import release_active_execution_for_event as _sydney_release_execution
                _sydney_release_execution(event)
            except Exception as _sydney_release_error:
                logger.warning(
                    "Sydney execution lease release failed: %s",
                    _sydney_release_error,
                )

            # Fire any one-shot post-delivery callback registered for this
            # session (e.g. deferred background-review notifications)."""
    return _replace_exact(
        contents,
        execution_release_anchor,
        execution_release_replacement,
        "execution lease release",
    )


def _patch_telegram(contents: str) -> str:
    attempt_anchor = """\
                msg = None
                for _send_attempt in range(3):"""
    attempt_replacement = """\
                msg = None
                _sydney_single_attempt = bool(
                    metadata and metadata.get("sydney_durable_delivery")
                )
                for _send_attempt in range(3):"""
    contents = _replace_exact(
        contents,
        attempt_anchor,
        attempt_replacement,
        "Telegram durable delivery attempt marker",
    )
    network_anchor = """\
                        # TimedOut is also a subclass of NetworkError. A
                        # generic timeout may have reached Telegram, so don't
                        # retry; a wrapped ConnectTimeout means no connection
                        # was established, so retrying is safe."""
    network_replacement = """\
                        # SYDNEY_AMBIGUOUS_DELIVERY_SINGLE_ATTEMPT
                        # The durable final-response ledger has no authoritative
                        # Telegram receipt after a network exception. Do not
                        # risk replaying the same user-visible response.
                        if _sydney_single_attempt:
                            raise
                        # TimedOut is also a subclass of NetworkError. A
                        # generic timeout may have reached Telegram, so don't
                        # retry; a wrapped ConnectTimeout means no connection
                        # was established, so retrying is safe."""
    return _replace_exact(
        contents,
        network_anchor,
        network_replacement,
        "Telegram ambiguous durable delivery",
    )


def _patch_conversation_loop(contents: str) -> str:
    budget_anchor = """\
                except Exception:
                    pass

                if env_var_enabled("HERMES_DUMP_REQUESTS"):"""
    budget_replacement = """\
                except Exception:
                    pass

                # SYDNEY_RETRY_AND_USAGE_GUARD
                from agent.sydney_runtime import reserve_input_budget
                reserve_input_budget(agent, approx_request_tokens)

                if env_var_enabled("HERMES_DUMP_REQUESTS"):"""
    contents = _replace_exact(
        contents, budget_anchor, budget_replacement, "rolling input budget"
    )
    usage_anchor = """\
                    canonical_usage = normalize_usage(
                        response.usage,
                        provider=agent.provider,
                        api_mode=agent.api_mode,
                    )
                    prompt_tokens = canonical_usage.prompt_tokens"""
    usage_replacement = """\
                    canonical_usage = normalize_usage(
                        response.usage,
                        provider=agent.provider,
                        api_mode=agent.api_mode,
                    )
                    # SYDNEY_USAGE_METADATA_ACCOUNTING
                    from agent.sydney_runtime import reconcile_input_usage
                    reconcile_input_usage(agent, canonical_usage.input_tokens)
                    prompt_tokens = canonical_usage.prompt_tokens"""
    contents = _replace_exact(
        contents, usage_anchor, usage_replacement, "usage metadata accounting"
    )
    terminal_policy_anchor = """\
                    final_response = agent._toolguard_controlled_halt_response(decision)"""
    terminal_policy_replacement = """\
                    # SYDNEY_TERMINAL_TOOL_POLICY_RESPONSE
                    from agent.sydney_runtime import terminal_tool_policy_response
                    final_response = (
                        terminal_tool_policy_response(agent)
                        or agent._toolguard_controlled_halt_response(decision)
                    )"""
    contents = _replace_exact(
        contents,
        terminal_policy_anchor,
        terminal_policy_replacement,
        "terminal Sydney tool policy response",
    )
    retry_anchor = """\
                retry_count += 1
                elapsed_time = time.time() - api_start_time"""
    retry_replacement = """\
                retry_count += 1
                # SYDNEY_DURABLE_RETRY_HANDOFF
                from agent.sydney_runtime import defer_retry_if_needed
                _sydney_deferred = defer_retry_if_needed(
                    agent, api_error, attempt=retry_count - 1
                )
                if _sydney_deferred:
                    agent._persist_session(messages, conversation_history)
                    return {
                        "final_response": _sydney_deferred,
                        "messages": messages,
                        "api_calls": api_call_count,
                        "completed": False,
                        "deferred": True,
                    }
                elapsed_time = time.time() - api_start_time"""
    return _replace_exact(
        contents, retry_anchor, retry_replacement, "durable retry handoff"
    )


def _patch_tool_executor(contents: str) -> str:
    concurrent_before = """\
                block_result = agent._guardrail_block_result(guardrail_decision)
                blocked_by_guardrail = True

        parsed_calls.append((tool_call, function_name, function_args, block_result, blocked_by_guardrail))"""
    concurrent_before_replacement = """\
                block_result = agent._guardrail_block_result(guardrail_decision)
                blocked_by_guardrail = True

        # SYDNEY_TOOL_BEFORE
        if block_result is None:
            from agent.sydney_runtime import tool_before as _sydney_tool_before
            _sydney_decision = _sydney_tool_before(
                agent, tool_call.id, function_name, function_args
            )
            if _sydney_decision is not None:
                if _sydney_decision.restored_result is not None:
                    block_result = _sydney_decision
                else:
                    block_result = json.dumps(
                        {"error": _sydney_decision.block_message}, ensure_ascii=False
                    )

        parsed_calls.append((tool_call, function_name, function_args, block_result, blocked_by_guardrail))"""
    contents = _replace_exact(
        contents,
        concurrent_before,
        concurrent_before_replacement,
        "concurrent tool before",
    )
    concurrent_precomputed = """\
        if block_result is not None:
            results[i] = (name, args, block_result, 0.0, True, True)"""
    concurrent_precomputed_replacement = """\
        if block_result is not None:
            _restored_result = getattr(block_result, "restored_result", None)
            if _restored_result is not None:
                results[i] = (name, args, _restored_result, 0.0, False, True)
            else:
                results[i] = (name, args, block_result, 0.0, True, True)"""
    contents = _replace_exact(
        contents,
        concurrent_precomputed,
        concurrent_precomputed_replacement,
        "concurrent restored result",
    )
    concurrent_after = """\
        duration = time.time() - start
        is_error, _ = _detect_tool_failure(function_name, result)
        if is_error:"""
    concurrent_after_replacement = """\
        duration = time.time() - start
        is_error, _ = _detect_tool_failure(function_name, result)
        # SYDNEY_TOOL_AFTER
        from agent.sydney_runtime import tool_after as _sydney_tool_after
        _sydney_tool_after(
            agent, tool_call.id, function_name, result, failed=is_error
        )
        if is_error:"""
    contents = _replace_exact(
        contents,
        concurrent_after,
        concurrent_after_replacement,
        "concurrent tool after",
    )
    sequential_before = """\
            if not guardrail_decision.allows_execution:
                _guardrail_block_decision = guardrail_decision

        _execution_blocked = _block_msg is not None or _guardrail_block_decision is not None"""
    sequential_before_replacement = """\
            if not guardrail_decision.allows_execution:
                _guardrail_block_decision = guardrail_decision

        # SYDNEY_TOOL_BEFORE_SEQUENTIAL
        _sydney_restored_result = None
        if _block_msg is None and _guardrail_block_decision is None:
            from agent.sydney_runtime import tool_before as _sydney_tool_before
            _sydney_decision = _sydney_tool_before(
                agent, tool_call.id, function_name, function_args
            )
            if _sydney_decision is not None:
                if _sydney_decision.restored_result is not None:
                    _sydney_restored_result = _sydney_decision.restored_result
                else:
                    _block_msg = _sydney_decision.block_message

        _execution_blocked = (
            _block_msg is not None
            or _guardrail_block_decision is not None
            or _sydney_restored_result is not None
        )"""
    contents = _replace_exact(
        contents,
        sequential_before,
        sequential_before_replacement,
        "sequential tool before",
    )
    sequential_precomputed = """\
        if _block_msg is not None:
            # Tool blocked by plugin policy — return error without executing.
            function_result = json.dumps({"error": _block_msg}, ensure_ascii=False)
            tool_duration = 0.0"""
    sequential_precomputed_replacement = """\
        if _sydney_restored_result is not None:
            # Durable retry: reuse the successful prior result without executing.
            function_result = _sydney_restored_result
            tool_duration = 0.0
        elif _block_msg is not None:
            # Tool blocked by plugin policy — return error without executing.
            function_result = json.dumps({"error": _block_msg}, ensure_ascii=False)
            tool_duration = 0.0"""
    contents = _replace_exact(
        contents,
        sequential_precomputed,
        sequential_precomputed_replacement,
        "sequential restored result",
    )
    sequential_after = """\
        _is_error_result, _ = _detect_tool_failure(function_name, function_result)
        if not _execution_blocked:
            function_result = agent._append_guardrail_observation("""
    sequential_after_replacement = """\
        _is_error_result, _ = _detect_tool_failure(function_name, function_result)
        if _sydney_restored_result is not None:
            _is_error_result = False
        if not _execution_blocked:
            # SYDNEY_TOOL_AFTER_SEQUENTIAL
            from agent.sydney_runtime import tool_after as _sydney_tool_after
            _sydney_tool_after(
                agent,
                tool_call.id,
                function_name,
                function_result,
                failed=_is_error_result,
            )
            function_result = agent._append_guardrail_observation("""
    return _replace_exact(
        contents,
        sequential_after,
        sequential_after_replacement,
        "sequential tool after",
    )


PATCHERS: dict[str, Callable[[str], str]] = {
    "agent/credential_pool.py": _patch_credential_pool,
    "agent/agent_init.py": _patch_agent_init,
    "agent/gemini_schema.py": _patch_gemini_schema,
    "gateway/run.py": _patch_gateway_run,
    "gateway/platforms/base.py": _patch_gateway_base,
    "gateway/platforms/telegram.py": _patch_telegram,
    "agent/conversation_loop.py": _patch_conversation_loop,
    "agent/tool_executor.py": _patch_tool_executor,
}


def _desired(source: Path, source_hashes: dict[str, str]) -> dict[str, bytes]:
    desired: dict[str, bytes] = {}
    for relative, patcher in PATCHERS.items():
        baseline = _baseline(source, relative)
        digest = hashlib.sha256(baseline).hexdigest()
        if digest != source_hashes.get(relative):
            raise ValueError(f"Hermes baseline hash mismatch: {relative}")
        desired[relative] = patcher(baseline.decode("utf-8")).encode("utf-8")

    copies = {
        "plugins/memory/sydney/__init__.py": "sydney_memory_provider.py",
        "plugins/memory/sydney/sydney_spool.py": "sydney_spool.py",
        "plugins/memory/sydney/sydney_retry.py": "sydney_retry.py",
        "plugins/memory/sydney/sydney_backfill.py": "sydney_backfill.py",
        "plugins/memory/sydney/sydney_recovery.py": "sydney_recovery.py",
        "agent/sydney_runtime.py": "sydney_runtime.py",
        "gateway/sydney_gateway.py": "sydney_gateway.py",
    }
    for relative, local_name in copies.items():
        desired[relative] = (OVERLAY_DIRECTORY / local_name).read_bytes()
    desired["plugins/memory/sydney/plugin.yaml"] = (
        b"name: sydney\n"
        b"version: 1.0.0\n"
        b'description: "Sydney durable context and automatic continuation."\n'
        b"hooks:\n  - on_session_end\n"
    )
    return desired


def _stage(target: Path, contents: bytes, mode: int) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".sydney-install-", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), mode)
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_replace(source: Path, desired: dict[str, bytes]) -> None:
    targets = {source / relative: contents for relative, contents in desired.items()}
    created_directories: list[Path] = []
    for target in targets:
        missing: list[Path] = []
        parent = target.parent
        while parent != source and not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            directory.mkdir(mode=0o755)
            created_directories.append(directory)
    originals = {
        target: (
            target.exists(),
            target.read_bytes() if target.exists() else b"",
            stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644,
        )
        for target in targets
    }
    staged: dict[Path, Path] = {}
    applied: list[Path] = []
    try:
        for target, contents in targets.items():
            staged[target] = _stage(target, contents, originals[target][2])
        for target in targets:
            os.replace(staged[target], target)
            applied.append(target)
    except Exception:
        for target in reversed(applied):
            existed, contents, mode = originals[target]
            if existed:
                rollback = _stage(target, contents, mode)
                os.replace(rollback, target)
            else:
                target.unlink(missing_ok=True)
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def install(source: Path) -> None:
    source = source.expanduser().resolve()
    manifest = _manifest()
    hermes = manifest.get("hermes_upstream")
    if not isinstance(hermes, dict):
        raise TypeError("overlay manifest is missing hermes_upstream")
    expected_commit = str(hermes.get("commit") or "")
    if _head(source) != expected_commit:
        raise ValueError("Hermes checkout does not match the approved commit")
    source_hashes = hermes.get("source_sha256")
    if not isinstance(source_hashes, dict):
        raise TypeError("overlay manifest is missing Hermes source hashes")
    desired = _desired(source, {str(k): str(v) for k, v in source_hashes.items()})
    dirty = _status(source)
    exact = all(
        (source / relative).is_file() and (source / relative).read_bytes() == contents
        for relative, contents in desired.items()
    )
    if exact:
        if dirty != set(desired):
            raise ValueError("Hermes checkout has unrelated or tampered changes")
        return
    if dirty:
        raise ValueError("Hermes checkout must be pristine before Sydney install")
    for relative in desired:
        target = source / relative
        if relative not in PATCHERS and target.exists():
            raise ValueError(
                f"Hermes checkout contains a partial Sydney file: {relative}"
            )
    _atomic_replace(source, desired)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    install(args.source)


if __name__ == "__main__":
    main()
