#!/usr/bin/env python3
"""Install Sydney into the exact approved Hermes source tree, atomically."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Callable


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


def _patch_agent_init(contents: str) -> str:
    old_guardrails = '''\
        agent._tool_guardrails = ToolCallGuardrailController(
            ToolCallGuardrailConfig.from_mapping(
                _agent_cfg.get("tool_loop_guardrails", {})
            )
        )'''
    new_guardrails = '''\
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
        )'''
    contents = _replace_exact(
        contents, old_guardrails, new_guardrails, "tool guardrail config"
    )
    old_registration = "                _mp = _load_mem(_mem_provider_name)"
    new_registration = '''\
                _mp = _load_mem(_mem_provider_name)
                # SYDNEY_MEMORY_REGISTRATION
                if _mp is None and _mem_provider_name == "sydney":
                    from plugins.memory.sydney import SydneyMemoryProvider
                    _mp = SydneyMemoryProvider()'''
    contents = _replace_exact(
        contents, old_registration, new_registration, "memory registration"
    )
    contents = _replace_exact(
        contents,
        '    compression_target_ratio = float(_compression_cfg.get("target_ratio", 0.20))',
        '    compression_target_ratio = float(_compression_cfg.get("target", _compression_cfg.get("target_ratio", 0.20)))',
        "compression target alias",
    )
    return _replace_exact(
        contents,
        '    compression_protect_last = int(_compression_cfg.get("protect_last_n", 20))',
        '    compression_protect_last = int(_compression_cfg.get("protect_last", _compression_cfg.get("protect_last_n", 20)))',
        "compression tail alias",
    )


def _patch_gateway_run(contents: str) -> str:
    startup = "        self._schedule_resume_pending_sessions()"
    startup_replacement = '''\
        self._schedule_resume_pending_sessions()

        # SYDNEY_CONTINUATION_WATCHER
        try:
            from gateway.sydney_gateway import sydney_continuation_watcher
            _sydney_task = asyncio.create_task(sydney_continuation_watcher(self))
            self._background_tasks.add(_sydney_task)
            _sydney_task.add_done_callback(self._background_tasks.discard)
        except Exception as _sydney_start_error:
            logger.warning("Sydney continuation watcher did not start: %s", _sydney_start_error)'''
    contents = _replace_exact(
        contents, startup, startup_replacement, "continuation watcher startup"
    )
    run_call = "                result = agent.run_conversation(_api_run_message, **_conversation_kwargs)"
    run_replacement = '''\
                # SYDNEY_INBOUND_SPOOL_BEFORE_MODEL
                from agent.sydney_runtime import record_inbound_before_model, record_run_outcome
                if event_message_id:
                    _sydney_message_id = str(event_message_id)
                else:
                    import hashlib as _sydney_hashlib
                    _sydney_message_id = _sydney_hashlib.sha256(
                        f"{source.platform.value}:{source.chat_id}:{session_id}:{message}".encode()
                    ).hexdigest()
                record_inbound_before_model(
                    agent,
                    platform_message_id=_sydney_message_id,
                    content=message,
                )
                result = agent.run_conversation(_api_run_message, **_conversation_kwargs)
                record_run_outcome(agent, result)'''
    return _replace_exact(
        contents, run_call, run_replacement, "inbound spool before model"
    )


def _patch_conversation_loop(contents: str) -> str:
    budget_anchor = '''\
                except Exception:
                    pass

                if env_var_enabled("HERMES_DUMP_REQUESTS"):'''
    budget_replacement = '''\
                except Exception:
                    pass

                # SYDNEY_RETRY_AND_USAGE_GUARD
                from agent.sydney_runtime import reserve_input_budget
                reserve_input_budget(agent, approx_request_tokens)

                if env_var_enabled("HERMES_DUMP_REQUESTS"):'''
    contents = _replace_exact(
        contents, budget_anchor, budget_replacement, "rolling input budget"
    )
    usage_anchor = '''\
                    canonical_usage = normalize_usage(
                        response.usage,
                        provider=agent.provider,
                        api_mode=agent.api_mode,
                    )
                    prompt_tokens = canonical_usage.prompt_tokens'''
    usage_replacement = '''\
                    canonical_usage = normalize_usage(
                        response.usage,
                        provider=agent.provider,
                        api_mode=agent.api_mode,
                    )
                    # SYDNEY_USAGE_METADATA_ACCOUNTING
                    from agent.sydney_runtime import reconcile_input_usage
                    reconcile_input_usage(agent, canonical_usage.input_tokens)
                    prompt_tokens = canonical_usage.prompt_tokens'''
    contents = _replace_exact(
        contents, usage_anchor, usage_replacement, "usage metadata accounting"
    )
    retry_anchor = '''\
                retry_count += 1
                elapsed_time = time.time() - api_start_time'''
    retry_replacement = '''\
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
                elapsed_time = time.time() - api_start_time'''
    return _replace_exact(
        contents, retry_anchor, retry_replacement, "durable retry handoff"
    )


def _patch_tool_executor(contents: str) -> str:
    concurrent_before = '''\
                block_result = agent._guardrail_block_result(guardrail_decision)
                blocked_by_guardrail = True

        parsed_calls.append((tool_call, function_name, function_args, block_result, blocked_by_guardrail))'''
    concurrent_before_replacement = '''\
                block_result = agent._guardrail_block_result(guardrail_decision)
                blocked_by_guardrail = True

        # SYDNEY_TOOL_BEFORE
        if block_result is None:
            from agent.sydney_runtime import tool_before as _sydney_tool_before
            _sydney_block = _sydney_tool_before(
                agent, tool_call.id, function_name, function_args
            )
            if _sydney_block:
                block_result = json.dumps({"error": _sydney_block}, ensure_ascii=False)

        parsed_calls.append((tool_call, function_name, function_args, block_result, blocked_by_guardrail))'''
    contents = _replace_exact(
        contents,
        concurrent_before,
        concurrent_before_replacement,
        "concurrent tool before",
    )
    concurrent_after = '''\
        duration = time.time() - start
        is_error, _ = _detect_tool_failure(function_name, result)
        if is_error:'''
    concurrent_after_replacement = '''\
        duration = time.time() - start
        is_error, _ = _detect_tool_failure(function_name, result)
        # SYDNEY_TOOL_AFTER
        from agent.sydney_runtime import tool_after as _sydney_tool_after
        _sydney_tool_after(
            agent, tool_call.id, function_name, result, failed=is_error
        )
        if is_error:'''
    contents = _replace_exact(
        contents,
        concurrent_after,
        concurrent_after_replacement,
        "concurrent tool after",
    )
    sequential_before = '''\
            if not guardrail_decision.allows_execution:
                _guardrail_block_decision = guardrail_decision

        _execution_blocked = _block_msg is not None or _guardrail_block_decision is not None'''
    sequential_before_replacement = '''\
            if not guardrail_decision.allows_execution:
                _guardrail_block_decision = guardrail_decision

        # SYDNEY_TOOL_BEFORE_SEQUENTIAL
        if _block_msg is None and _guardrail_block_decision is None:
            from agent.sydney_runtime import tool_before as _sydney_tool_before
            _block_msg = _sydney_tool_before(
                agent, tool_call.id, function_name, function_args
            )

        _execution_blocked = _block_msg is not None or _guardrail_block_decision is not None'''
    contents = _replace_exact(
        contents,
        sequential_before,
        sequential_before_replacement,
        "sequential tool before",
    )
    sequential_after = '''\
        _is_error_result, _ = _detect_tool_failure(function_name, function_result)
        if not _execution_blocked:
            function_result = agent._append_guardrail_observation('''
    sequential_after_replacement = '''\
        _is_error_result, _ = _detect_tool_failure(function_name, function_result)
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
            function_result = agent._append_guardrail_observation('''
    return _replace_exact(
        contents,
        sequential_after,
        sequential_after_replacement,
        "sequential tool after",
    )


PATCHERS: dict[str, Callable[[str], str]] = {
    "agent/credential_pool.py": _patch_credential_pool,
    "agent/agent_init.py": _patch_agent_init,
    "gateway/run.py": _patch_gateway_run,
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
        raise ValueError("overlay manifest is missing hermes_upstream")
    expected_commit = str(hermes.get("commit") or "")
    if _head(source) != expected_commit:
        raise ValueError("Hermes checkout does not match the approved commit")
    source_hashes = hermes.get("source_sha256")
    if not isinstance(source_hashes, dict):
        raise ValueError("overlay manifest is missing Hermes source hashes")
    desired = _desired(source, {str(k): str(v) for k, v in source_hashes.items()})
    dirty = _status(source)
    exact = all(
        (source / relative).is_file()
        and (source / relative).read_bytes() == contents
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
            raise ValueError(f"Hermes checkout contains a partial Sydney file: {relative}")
    _atomic_replace(source, desired)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    install(args.source)


if __name__ == "__main__":
    main()
