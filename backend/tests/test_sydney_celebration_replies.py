from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_sydney_memory_provider import FakeBackend, _provider

# isort: split

from sydney_runtime import (
    record_delivery_by_key,
    record_inbound_before_model,
    stage_run_outcome,
)

CELEBRATION_TOOL = "mcp_atlas_backend_command_contact_celebrations_preview"
AUDIENCE_REF = "87a25fb9-04ad-4645-b632-05281f8fb202"
CHECKSUM = "c2" * 32
OTHER_REF = "822afda3-c3f3-4ea6-874b-dd5d673ad506"
VISIBLE_SUMMARY = (
    "September birthdays: 1. Home anniversaries excluded.\n"
    "Mailing-address readiness: 0 ready; 1 missing.\n\n"
    "Returned sample (not the full audience):\n"
    "- Morgan Ellis — September 19.\n\n"
    f"Your separate reference: {OTHER_REF}.\n"
    "Nothing was changed or sent."
)


def _preview(*, birthdays=True, anniversaries=False):
    return {
        "month": 9,
        "include_birthdays": birthdays,
        "include_home_anniversaries": anniversaries,
        "audience_ref": AUDIENCE_REF,
        "audience_checksum": CHECKSUM,
        "birthday_count": int(birthdays),
        "home_anniversary_count": int(anniversaries),
        "union_count": 1,
        "address_ready_count": 0,
        "missing_address_count": 1,
        "reconciliation_status": "incomplete",
        "samples": [
            {
                "display_name": "Morgan Ellis",
                "address_ready": False,
                "celebrations": [
                    *([{"kind": "birthday", "day": 19}] if birthdays else []),
                    *(
                        [{"kind": "home_anniversary", "day": 19}]
                        if anniversaries
                        else []
                    ),
                ],
            }
        ],
    }


def _stage(tmp_path, prompt, response, *, tool_name=CELEBRATION_TOOL, preview=None):
    backend = FakeBackend()
    provider = _provider(tmp_path, backend)
    agent = SimpleNamespace(
        _memory_manager=SimpleNamespace(get_provider=lambda name: provider),
        _persist_user_message_idx=0,
    )
    assert record_inbound_before_model(
        agent, platform_message_id="birthday-reply", content=prompt
    )
    payload = json.dumps(preview or _preview())
    messages = [
        {"role": "user", "content": prompt},
        {
            "role": "assistant",
            "tool_calls": [{"id": "preview-1", "function": {"name": tool_name}}],
        },
        {
            "role": "tool",
            "tool_call_id": "preview-1",
            # Pinned Hermes tools/mcp_tool.py wraps MCP text in result.
            "content": json.dumps({"result": payload}),
        },
        {"role": "assistant", "content": response},
    ]
    result = {"final_response": response, "completed": True, "messages": messages}
    raw_tool_result = copy.deepcopy(messages[2])
    assert stage_run_outcome(agent, result)
    assert messages[2] == raw_tool_result
    return provider, backend, result


@pytest.mark.parametrize(
    "birthdays,anniversaries", [(True, False), (False, True), (True, True)]
)
@pytest.mark.parametrize(
    "metadata",
    [
        f"- **Audience checksum:** `{CHECKSUM}`\n- **Audience reference:** `{AUDIENCE_REF}`",
        f"Checksum: {CHECKSUM}\nAudience ref: {AUDIENCE_REF}",
        f"| Audience checksum | {CHECKSUM} |\n| Audience reference | {AUDIENCE_REF} |",
        f"1. Audience checksum: {CHECKSUM}\n2. Audience reference: {AUDIENCE_REF}",
        f"**Audience metadata**\n\n| Field | Value |\n| --- | --- |\n| Checksum | {CHECKSUM} |\n| Audience ref | {AUDIENCE_REF} |",
        f"Audience checksum: {CHECKSUM.upper()}\nAudience reference: {AUDIENCE_REF.upper()}",
    ],
)
def test_celebration_reply_omits_returned_metadata_and_preserves_internal_results(
    tmp_path, birthdays, anniversaries, metadata
):
    provider, backend, result = _stage(
        tmp_path,
        "Please check my September birthday only. Show exact counts and the sample.",
        f"{VISIBLE_SUMMARY}\n\n{metadata}",
        preview=_preview(birthdays=birthdays, anniversaries=anniversaries),
    )
    try:
        assert result["final_response"] == VISIBLE_SUMMARY
        assert result["messages"][-1]["content"] == VISIBLE_SUMMARY
        record_delivery_by_key(
            ("telegram", "private-chat", "birthday-reply"), delivered=True
        )
        visible_events = [
            event
            for name, payload in backend.calls
            if name == "ingest"
            for event in payload["events"]
            if event["source_event_key"].endswith(":final_response")
        ]
        assert [event["content"] for event in visible_events] == [VISIBLE_SUMMARY]
    finally:
        provider.shutdown()


@pytest.mark.parametrize(
    "prompt",
    [
        "Show September birthdays including the audience reference and checksum.",
        "What is the audience checksum for September birthdays?",
        "Tell me the audience reference and checksum for September birthdays.",
        "Give me the audience reference and checksum, but do not send anything.",
        "Please give me the audience metadata for September birthdays.",
        "Can I have the audience reference and checksum for these birthdays?",
        "Please get the audience reference and checksum for these birthdays.",
    ],
)
def test_explicit_celebration_metadata_requests_keep_the_returned_values(
    tmp_path, prompt
):
    response = f"Audience checksum: {CHECKSUM}\nAudience reference: {AUDIENCE_REF}"
    provider, _, result = _stage(tmp_path, prompt, response)
    try:
        assert result["final_response"] == response
    finally:
        record_delivery_by_key(
            ("telegram", "private-chat", "birthday-reply"), delivered=False
        )
        provider.shutdown()


def test_general_audience_reply_is_governed_separately(tmp_path):
    response = f"Audience checksum: {CHECKSUM}\nAudience reference: {AUDIENCE_REF}"
    provider, _, result = _stage(
        tmp_path,
        "Show my complete Command contact audience.",
        response,
        tool_name="mcp_atlas_backend_command_contact_audience_preview",
    )
    try:
        assert result["final_response"] == response
    finally:
        record_delivery_by_key(
            ("telegram", "private-chat", "birthday-reply"), delivered=False
        )
        provider.shutdown()


@pytest.mark.parametrize(
    "prompt",
    [
        "Check September birthdays. Do not show checksums or audience references.",
        "Show September birthdays, not audience references or checksums.",
        "Give me birthday sample and leave out the audience reference.",
        "Show September birthdays; no audience reference or checksum, please.",
        "Show September birthdays, and remember that the checksum is internal.",
        "Show September birthdays, the previous answer had an audience reference.",
        "Why did you tell me the audience reference for these birthdays?",
        "Explain the sentence “show me the audience checksum” without displaying the value.",
        "Show me the checksum for these birthdays. Actually, omit it.",
        "Please show me the audience reference, which should stay internal.",
    ],
)
def test_negative_metadata_request_does_not_enable_disclosure(tmp_path, prompt):
    provider, _, result = _stage(
        tmp_path,
        prompt,
        f"{VISIBLE_SUMMARY}\n\nChecksum: {CHECKSUM}\nAudience reference: {AUDIENCE_REF}",
    )
    try:
        assert result["final_response"] == VISIBLE_SUMMARY
    finally:
        record_delivery_by_key(
            ("telegram", "private-chat", "birthday-reply"), delivered=False
        )
        provider.shutdown()


def test_inline_celebration_metadata_keeps_contact_details(tmp_path):
    response = f"Morgan Ellis — September 19 (checksum: {CHECKSUM}) (audience ref: {AUDIENCE_REF})."
    provider, _, result = _stage(tmp_path, "Check September birthdays.", response)
    try:
        assert result["final_response"] == "Morgan Ellis — September 19."
    finally:
        record_delivery_by_key(
            ("telegram", "private-chat", "birthday-reply"), delivered=False
        )
        provider.shutdown()


def test_historical_celebration_ids_do_not_trigger_the_reply_guard(tmp_path):
    import sydney_runtime

    provider = _provider(tmp_path)
    agent = SimpleNamespace(
        _memory_manager=SimpleNamespace(get_provider=lambda name: provider),
        _persist_user_message_idx=2,
    )
    response = f"Your unrelated UUID is {AUDIENCE_REF}; checksum {CHECKSUM}."
    messages = [
        {"role": "user", "content": "Check September birthdays."},
        {"role": "tool", "name": CELEBRATION_TOOL, "content": json.dumps(_preview())},
        {"role": "user", "content": "Repeat the identifiers I provided."},
        {"role": "assistant", "content": response},
    ]
    original = copy.deepcopy(messages)
    try:
        assert (
            sydney_runtime.finalize_celebration_reply(agent, response, messages)
            == response
        )
        assert messages == original
    finally:
        provider.shutdown()


def _run_exact_hermes_reply_scenario(tmp_path, scenario):
    from tests.test_hermes_overlay import HERMES_COMMIT

    checkout = os.environ.get("HERMES_EXACT_CHECKOUT")
    if not checkout:
        pytest.skip("HERMES_EXACT_CHECKOUT is not configured")
    assert (
        subprocess.check_output(
            ["git", "-C", checkout, "rev-parse", "HEAD"], text=True
        ).strip()
        == HERMES_COMMIT
    )
    prefix = """
import ast, copy, json, os, subprocess, sys
from pathlib import Path
from types import SimpleNamespace
from tests.test_sydney_celebration_replies import (
    AUDIENCE_REF, CHECKSUM, CELEBRATION_TOOL, VISIBLE_SUMMARY, _preview,
)
from tests.test_sydney_memory_provider import _provider
from tests.test_hermes_overlay import HERMES_COMMIT, _load_overlay_module
import sydney_runtime
sys.path.insert(0, os.environ["HERMES_EXACT_CHECKOUT"])
sys.modules["agent.sydney_runtime"] = sydney_runtime
provider = _provider(Path(os.environ["HERMES_HOME"]))

def begin_current_request(agent, messages, content):
    source = subprocess.check_output([
        "git", "-C", os.environ["HERMES_EXACT_CHECKOUT"], "show",
        f"{HERMES_COMMIT}:agent/conversation_loop.py",
    ], text=True)
    patched = _load_overlay_module("install_sydney_overlay.py")._patch_conversation_loop(source)
    conversation = next(node for node in ast.parse(patched).body if isinstance(node, ast.FunctionDef) and node.name == "run_conversation")
    start = next(index for index, node in enumerate(conversation.body) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "user_msg" for target in node.targets))
    end = next(index for index, node in enumerate(conversation.body[start:], start) if isinstance(node, ast.If) and ast.unparse(node.test) == "not agent.quiet_mode")
    module = ast.fix_missing_locations(ast.Module(body=conversation.body[start:end], type_ignores=[]))
    exec(compile(module, "exact-hermes-current-request-boundary", "exec"), {
        "agent": agent, "messages": messages, "user_message": content,
        "original_user_message": content,
    })
"""
    completed = subprocess.run(
        [sys.executable, "-c", prefix + textwrap.dedent(scenario)],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "HERMES_HOME": str(tmp_path),
            "HERMES_REDACT_SECRETS": "true",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("synthetic_continuation", [False, True])
def test_exact_hermes_compression_relocates_the_current_celebration_turn(
    tmp_path, synthetic_continuation
):
    _run_exact_hermes_reply_scenario(
        tmp_path,
        """
        from agent.conversation_compression import compress_context

        current = [
            {"role": "user", "content": "Check September birthdays only."},
            {"role": "assistant", "tool_calls": [{"id": "skill-1", "function": {"name": "skill_view"}}]},
            {"role": "tool", "tool_call_id": "skill-1", "content": "Current skill instructions"},
            {"role": "assistant", "tool_calls": [{"id": "preview-1", "function": {"name": CELEBRATION_TOOL}}]},
            {"role": "tool", "tool_call_id": "preview-1", "content": json.dumps({"result": json.dumps(_preview())})},
        ]
        original = [
            {"role": role, "content": "Earlier discussion."}
            for _ in range(3) for role in ("user", "assistant")
        ]
        summary = {"role": "user", "content": "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier discussion."}
        agent = SimpleNamespace(
            _persist_user_message_idx=6,
            _memory_manager=SimpleNamespace(get_provider=lambda name: provider, on_pre_compress=lambda messages: None),
            _compression_feasibility_checked=True,
            context_compressor=SimpleNamespace(compress=lambda *args, **kwargs: [summary] + copy.deepcopy(current), compression_count=1),
            _emit_status=lambda *args: None,
            _todo_store=SimpleNamespace(format_for_injection=lambda: ""),
            _invalidate_system_prompt=lambda: None,
            _build_system_prompt=lambda *args: "Current instructions",
            _session_db=None,
            session_id="isolated-review",
            model="fixture",
            tools=[],
        )
        begin_current_request(agent, original, current[0]["content"])
        original.extend(copy.deepcopy(current[1:]))
        before = copy.deepcopy(original)
        compressed, _ = compress_context(agent, original, "Current instructions", approx_tokens=1000)
        continuation = [{"role": "user", "content": "[System: Continue now and complete the response.]"}] if ADD_CONTINUATION else []
        compressed.extend(continuation)
        response = f"{VISIBLE_SUMMARY}\\n\\nAudience checksum: {CHECKSUM}\\nAudience reference: {AUDIENCE_REF}"
        compressed.append({"role": "assistant", "content": response})
        assert agent._persist_user_message_idx == 6
        assert compressed[6]["role"] == ("user" if ADD_CONTINUATION else "assistant")
        assert compressed[1] == current[0]
        try:
            assert sydney_runtime.finalize_celebration_reply(agent, response, compressed) == VISIBLE_SUMMARY
            assert compressed[-1]["content"] == VISIBLE_SUMMARY
            assert compressed[:-1] == [summary] + current + continuation
            assert original == before
            assert agent.session_id == "isolated-review"
        finally:
            provider.shutdown()
        """.replace("ADD_CONTINUATION", str(synthetic_continuation)),
    )


def test_exact_hermes_pinned_request_does_not_reuse_historical_preview(tmp_path):
    _run_exact_hermes_reply_scenario(
        tmp_path,
        """
        agent = SimpleNamespace(_memory_manager=SimpleNamespace(get_provider=lambda name: provider))
        messages = [
            {"role": "user", "content": "Check September birthdays."},
            {"role": "tool", "name": CELEBRATION_TOOL, "content": json.dumps(_preview())},
        ]
        begin_current_request(agent, messages, "Repeat the reference I supplied.")
        messages.append({"role": "user", "content": "[System: Continue now and complete the response.]"})
        response = f"Your supplied reference is {AUDIENCE_REF}; checksum {CHECKSUM}."
        messages.append({"role": "assistant", "content": response})
        agent._persist_user_message_idx = 100
        original = copy.deepcopy(messages)
        try:
            assert sydney_runtime.finalize_celebration_reply(agent, response, messages) == response
            assert messages == original
        finally:
            provider.shutdown()
        """,
    )


def test_exact_hermes_sanitized_assistant_keeps_redaction_when_metadata_is_cleaned(
    tmp_path,
):
    _run_exact_hermes_reply_scenario(
        tmp_path,
        """
        from agent.chat_completion_helpers import build_assistant_message

        agent = SimpleNamespace(
            _memory_manager=SimpleNamespace(get_provider=lambda name: provider),
            _persist_user_message_idx=0,
            _extract_reasoning=lambda message: None,
            verbose_logging=False,
            reasoning_callback=None,
            _strip_think_blocks=lambda content: content,
        )
        synthetic_token = "ghp_" + "z" * 30
        response = f"{VISIBLE_SUMMARY}\\nExample token: {synthetic_token}\\nAudience checksum: {CHECKSUM}\\nAudience reference: {AUDIENCE_REF}"
        final_message = build_assistant_message(agent, SimpleNamespace(content=response, tool_calls=None), "stop")
        sanitized = final_message["content"]
        assert sanitized != response
        assert synthetic_token not in sanitized
        expected_stored = sanitized.split("\\nAudience checksum:")[0]
        messages = [
            {"role": "user", "content": "Check September birthdays only."},
            {"role": "tool", "name": CELEBRATION_TOOL, "content": json.dumps(_preview())},
            final_message,
        ]
        before = copy.deepcopy(messages)
        try:
            result = sydney_runtime.finalize_celebration_reply(agent, response, messages)
            assert AUDIENCE_REF not in result and CHECKSUM not in result
            assert final_message["content"] == expected_stored
            assert synthetic_token not in final_message["content"]
            assert messages[:-1] == before[:-1]
            assert {key: value for key, value in final_message.items() if key != "content"} == {
                key: value for key, value in before[-1].items() if key != "content"
            }
        finally:
            provider.shutdown()
        """,
    )


def test_exact_hermes_celebration_reply_is_clean_before_history_persistence(
    tmp_path, monkeypatch
):
    import sydney_runtime

    from tests.test_hermes_overlay import HERMES_COMMIT, _load_overlay_module

    checkout = os.environ.get("HERMES_EXACT_CHECKOUT")
    if not checkout:
        pytest.skip("HERMES_EXACT_CHECKOUT is not configured")
    baseline = subprocess.run(
        ["git", "-C", checkout, "show", f"{HERMES_COMMIT}:agent/conversation_loop.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    installer = _load_overlay_module("install_sydney_overlay.py")
    patched = installer._patch_conversation_loop(baseline)
    conversation = next(
        node
        for node in ast.parse(patched).body
        if isinstance(node, ast.FunctionDef) and node.name == "run_conversation"
    )
    # Execute the real terminal section through persistence, with only the
    # unrelated trajectory/resource/persistence adapters kept in memory.
    start = next(
        index
        for index, node in enumerate(conversation.body)
        if isinstance(node, ast.If)
        and ast.unparse(node.test).startswith("final_response is None and")
    )
    end = next(
        index
        for index, node in enumerate(conversation.body[start:], start)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "_persist_session"
    )
    finish = ast.parse("def finish(agent, messages, final_response):\n    pass").body[0]
    finish.body = [
        *conversation.body[start : end + 1],
        ast.parse("return final_response").body[0],
    ]
    module = ast.fix_missing_locations(ast.Module(body=[finish], type_ignores=[]))
    prompt = "Check my September birthday only, with full sample names."
    response = f"{VISIBLE_SUMMARY}\n\nAudience checksum: {CHECKSUM}\nAudience reference: {AUDIENCE_REF}"
    provider = _provider(tmp_path)
    persisted = []
    agent = SimpleNamespace(
        _memory_manager=SimpleNamespace(get_provider=lambda name: provider),
        _persist_user_message_idx=0,
        max_iterations=10,
        _save_trajectory=lambda *args: None,
        _cleanup_task_resources=lambda *args: None,
        _drop_trailing_empty_response_scaffolding=lambda *args: None,
        _persist_session=lambda messages, history: persisted.append(
            copy.deepcopy(messages)
        ),
    )
    messages = [
        {"role": "user", "content": prompt},
        {"role": "tool", "name": CELEBRATION_TOOL, "content": json.dumps(_preview())},
        {"role": "assistant", "content": response},
    ]
    monkeypatch.setitem(sys.modules, "agent.sydney_runtime", sydney_runtime)
    namespace = {
        "api_call_count": 1,
        "failed": False,
        "user_message": prompt,
        "original_user_message": prompt,
        "effective_task_id": "fixture",
        "conversation_history": [],
        "_summarize_user_message_for_log": str,
    }
    exec(compile(module, "exact-hermes-reply-boundary", "exec"), namespace)  # noqa: S102 - exact pinned source fixture
    try:
        assert namespace["finish"](agent, messages, response) == VISIBLE_SUMMARY
        assert persisted[0][-1]["content"] == VISIBLE_SUMMARY
        assert persisted[0][1]["content"] == json.dumps(_preview())
    finally:
        provider.shutdown()
