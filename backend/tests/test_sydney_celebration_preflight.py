from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_sydney_memory_provider import FakeBackend, _provider

# isort: split

import sydney_runtime as runtime

ROOT = Path(__file__).resolve().parents[2]
SKILL_NAME = "atlas-backend-operations"
SKILL_CONTENT = (ROOT / "hermes/skills" / SKILL_NAME / "SKILL.md").read_text()
PREVIEW = "mcp_atlas_backend_command_contact_celebrations_preview"


class PreflightBackend(FakeBackend):
    restored_skill_result: str | None = None

    def start_tool(self, payload: dict) -> dict:
        if (
            self.restored_skill_result is not None
            and payload["tool_name"] == "skill_view"
        ):
            self.calls.append(("tool_before", payload))
            return {
                "state": "succeeded",
                "replay_decision": "restore_result",
                "canonical_tool_call_id": payload["tool_call_id"],
                "result_content": self.restored_skill_result,
            }
        return super().start_tool(payload)


@pytest.fixture
def subject(tmp_path):
    backend = PreflightBackend()
    provider = _provider(tmp_path, backend)
    content = "Check current Command home anniversaries and the returned sample."
    provider.record_inbound("current-preflight-request", content)
    provider.drain_once()
    message = {"role": "user", "content": content}
    agent = SimpleNamespace(
        _memory_manager=SimpleNamespace(get_provider=lambda name: provider),
        session_id="preflight-session",
    )
    runtime.pin_celebration_request(agent, message, content)
    try:
        yield agent, provider, backend, message
    finally:
        provider.shutdown()


def _skill_result(**overrides):
    return json.dumps(
        {"success": True, "name": SKILL_NAME, "content": SKILL_CONTENT, **overrides}
    )


def _read_skill(
    subject, *, result=None, arguments=None, failed=False, call_id="skill-1"
):
    agent, _provider, _backend, _message = subject
    decision = runtime.tool_before(
        agent, call_id, "skill_view", arguments or {"name": SKILL_NAME}
    )
    assert decision is None
    runtime.tool_after(
        agent,
        call_id,
        "skill_view",
        _skill_result() if result is None else result,
        failed=failed,
    )


def _assert_preview_blocked(subject, *, call_id="preview-before-skill"):
    agent, _provider, backend, _message = subject
    before = copy.deepcopy(backend.calls)
    decision = runtime.tool_before(agent, call_id, PREVIEW, {"month": 9})

    assert decision is not None
    assert decision.restored_result is None
    assert "skill_view" in decision.block_message
    assert SKILL_NAME in decision.block_message
    assert "retry" in decision.block_message.lower()
    assert "not executed" in decision.block_message.lower()
    assert getattr(agent, "_tool_guardrail_halt_decision", None) is None
    assert getattr(agent, "_sydney_terminal_tool_policy_response", None) is None
    assert backend.calls == before


def test_preview_requires_a_current_skill_read_without_halting_or_changing_history(
    subject,
):
    agent, _provider, _backend, message = subject
    historical = [
        {"role": "user", "content": "Earlier celebration question"},
        {"role": "tool", "name": "skill_view", "content": _skill_result()},
        message,
    ]
    before = copy.deepcopy(historical)

    _assert_preview_blocked(subject)

    assert historical == before
    assert agent._sydney_celebration_request[0] is message
    assert agent.session_id == "preflight-session"


def test_current_skill_content_hash_is_coupled_to_source_and_managed_manifest():
    manifest = json.loads((ROOT / "hermes/overlay/manifest.json").read_text())
    expected = manifest["managed_skills"][SKILL_NAME]["sha256"]

    assert hashlib.sha256(SKILL_CONTENT.encode()).hexdigest() == expected
    assert getattr(runtime, "_CELEBRATION_SKILL_SHA256", None) == expected


def test_successful_exact_current_skill_read_unlocks_repeated_previews(subject):
    _assert_preview_blocked(subject)
    _read_skill(subject)
    agent, _provider, _backend, _message = subject

    for call_id in ("preview-1", "preview-2"):
        assert runtime.tool_before(agent, call_id, PREVIEW, {"month": 9}) is None
    assert getattr(agent, "_tool_guardrail_halt_decision", None) is None


@pytest.mark.parametrize(
    ("result", "failed"),
    [
        (
            _skill_result(
                content=SKILL_CONTENT.replace("version: 2.2.3", "version: 2.2.2")
            ),
            False,
        ),
        (
            _skill_result(content=SKILL_CONTENT + "\nUnexpected extra instructions"),
            False,
        ),
        (_skill_result(name="unrelated-skill"), False),
        (_skill_result(success=False), False),
        (_skill_result(success="true"), False),
        (_skill_result(isError=True), False),
        (_skill_result(error="skill read failed"), False),
        (_skill_result(content={"markdown": SKILL_CONTENT}), False),
        ("not valid JSON", False),
        (_skill_result(), True),
    ],
    ids=[
        "old",
        "modified",
        "wrong-name",
        "unsuccessful",
        "unproven-success",
        "mcp-error",
        "error",
        "wrong-content-shape",
        "malformed",
        "failed-execution",
    ],
)
def test_wrong_old_or_failed_skill_result_does_not_unlock_preview(
    subject, result, failed
):
    _read_skill(subject, result=result, failed=failed)

    _assert_preview_blocked(subject)


@pytest.mark.parametrize(
    "arguments",
    [
        {"name": "unrelated-skill"},
        {"name": SKILL_NAME, "file_path": "references/old.md"},
    ],
)
def test_exact_content_from_the_wrong_skill_request_does_not_count(subject, arguments):
    _read_skill(subject, arguments=arguments)

    _assert_preview_blocked(subject)


def test_unstarted_or_restored_skill_result_does_not_count(subject):
    agent, _provider, backend, _message = subject
    runtime.tool_after(
        agent, "unstarted-skill", "skill_view", _skill_result(), failed=False
    )
    _assert_preview_blocked(subject, call_id="preview-unstarted")
    backend.restored_skill_result = _skill_result()

    restored = runtime.tool_before(
        agent, "restored-skill", "skill_view", {"name": SKILL_NAME}
    )
    assert restored is not None
    assert restored.restored_result == _skill_result()
    runtime.tool_after(
        agent, "restored-skill", "skill_view", restored.restored_result, failed=False
    )

    _assert_preview_blocked(subject, call_id="preview-restored")


@pytest.mark.parametrize(
    "result,failed",
    [(_skill_result(content="old"), False), (_skill_result(), True)],
    ids=["wrong-refresh-content", "failed-refresh"],
)
def test_a_failed_current_skill_refresh_cannot_leave_previous_proof(
    subject, result, failed
):
    _read_skill(subject)
    _read_skill(subject, result=result, failed=failed, call_id="skill-refresh")

    _assert_preview_blocked(subject)


def test_new_real_request_with_identical_text_requires_a_new_skill_read(subject):
    _read_skill(subject)
    agent, _provider, _backend, message = subject
    runtime.pin_celebration_request(agent, dict(message), message["content"])

    _assert_preview_blocked(subject)
    _read_skill(subject, call_id="new-request-skill")
    assert runtime.tool_before(agent, "new-request-preview", PREVIEW, {}) is None


def test_outstanding_skill_result_from_previous_request_cannot_unlock_new_request(
    subject,
):
    agent, _provider, _backend, message = subject
    assert (
        runtime.tool_before(agent, "previous-skill", "skill_view", {"name": SKILL_NAME})
        is None
    )
    runtime.pin_celebration_request(agent, dict(message), message["content"])
    runtime.tool_after(
        agent, "previous-skill", "skill_view", _skill_result(), failed=False
    )

    _assert_preview_blocked(subject)


def test_preview_without_a_real_current_request_pin_is_blocked(subject):
    agent, _provider, _backend, _message = subject
    del agent._sydney_celebration_request
    _read_skill(subject)

    _assert_preview_blocked(subject)


@pytest.mark.parametrize(
    "tool_name",
    [
        "crm_tasks_read",
        "mcp_atlas_backend_crm_tasks_read",
        "command_contacts_search",
        "command_contact_audience_preview",
    ],
)
def test_unrelated_reads_do_not_require_the_celebration_skill(subject, tool_name):
    agent, _provider, _backend, _message = subject

    assert runtime.tool_before(agent, "unrelated-read", tool_name, {}) is None


def test_non_sydney_context_keeps_the_existing_tool_behavior():
    agent = SimpleNamespace()

    assert runtime.tool_before(agent, "other-context", PREVIEW, {}) is None


@pytest.mark.parametrize("available,retry", [(False, True), (True, False)])
def test_inactive_provider_cannot_create_or_require_celebration_skill_proof(
    available, retry
):
    provider = SimpleNamespace(is_available=lambda: available, retry_enabled=retry)
    agent = SimpleNamespace(
        _memory_manager=SimpleNamespace(get_provider=lambda name: provider)
    )
    message = {"role": "user", "content": "Check celebrations."}
    runtime.pin_celebration_request(agent, message, message["content"])
    runtime.begin_celebration_skill_read(
        agent, "skill-1", "skill_view", {"name": SKILL_NAME}
    )
    runtime.complete_celebration_skill_read(
        agent, "skill-1", "skill_view", _skill_result(), failed=False
    )

    assert runtime.celebration_tool_preflight(agent, "preview-1", PREVIEW, {}) is None
    assert agent._sydney_celebration_skill_proof is None
    assert agent._sydney_celebration_skill_pending == {}


def test_backend_outage_still_requires_current_skill_and_preserves_read_only_fallback(
    tmp_path,
):
    class BackendOutage(PreflightBackend):
        def ingest_events(self, payload):
            self.calls.append(("ingest", payload))
            raise TimeoutError("isolated backend outage")

    backend = BackendOutage()
    provider = _provider(tmp_path, backend)
    agent = SimpleNamespace(
        _memory_manager=SimpleNamespace(get_provider=lambda name: provider)
    )
    message = {"role": "user", "content": "Check current Command anniversaries."}
    try:
        assert runtime.record_inbound_before_model(
            agent, platform_message_id="preflight-outage", content=message["content"]
        )
        runtime.pin_celebration_request(agent, message, message["content"])
        assert not provider.has_active_run_lease()
        blocked = runtime.tool_before(agent, "outage-preview-1", PREVIEW, {})
        assert blocked is not None and "skill_view" in blocked.block_message

        _read_skill((agent, provider, backend, message))

        assert runtime.tool_before(agent, "outage-preview-2", PREVIEW, {}) is None
        assert (
            runtime.tool_before(agent, "outage-task-read", "crm_tasks_read", {}) is None
        )
        denied_write = runtime.tool_before(agent, "outage-write", "gmail_send", {})
        assert (
            denied_write is not None
            and "mutating tools are blocked" in denied_write.block_message
        )
        assert not any(
            name in {"tool_before", "tool_after"} for name, _payload in backend.calls
        )
        assert getattr(agent, "_tool_guardrail_halt_decision", None) is None
    finally:
        provider.shutdown()


def test_synthetic_turns_and_copied_history_do_not_invalidate_the_real_request_proof(
    subject,
):
    _assert_preview_blocked(subject)
    _read_skill(subject)
    agent, _provider, _backend, message = subject
    pinned = agent._sydney_celebration_request
    messages = [
        copy.deepcopy(message),
        {"role": "user", "content": "[System: Continue]"},
    ]
    before = copy.deepcopy(messages)

    assert runtime.tool_before(agent, "after-compression", PREVIEW, {}) is None
    assert messages == before
    assert agent._sydney_celebration_request is pinned


@pytest.mark.parametrize("executor", ["sequential", "concurrent"])
def test_exact_pinned_request_and_executor_seams_require_actual_current_skill_content(
    tmp_path, executor
):
    from tests.test_sydney_celebration_replies import _run_exact_hermes_reply_scenario

    _run_exact_hermes_reply_scenario(
        tmp_path,
        """
        from tools import skills_tool
        from tests.test_sydney_celebration_preflight import SKILL_CONTENT, SKILL_NAME, PREVIEW

        raw_executor = subprocess.check_output([
            "git", "-C", os.environ["HERMES_EXACT_CHECKOUT"], "show",
            f"{HERMES_COMMIT}:agent/tool_executor.py",
        ], text=True)
        patched = _load_overlay_module("install_sydney_overlay.py")._patch_tool_executor(raw_executor)
        function = next(node for node in ast.parse(patched).body if isinstance(node, ast.FunctionDef) and node.name == "execute_tool_calls_EXECUTOR")

        def seam(name):
            for node in ast.walk(function):
                for _field, statements in ast.iter_fields(node):
                    if not isinstance(statements, list):
                        continue
                    for index, statement in enumerate(statements):
                        if isinstance(statement, ast.ImportFrom) and statement.module == "agent.sydney_runtime" and any(alias.name == name for alias in statement.names):
                            return ast.fix_missing_locations(ast.Module(body=statements[index:index + 2], type_ignores=[]))
            raise AssertionError("Pinned executor lost its Sydney seam")

        agent = SimpleNamespace(_memory_manager=SimpleNamespace(get_provider=lambda name: provider), quiet_mode=True, session_id="same-history")
        messages = [{"role": "user", "content": "Earlier request"}, {"role": "tool", "name": "skill_view", "content": SKILL_CONTENT}]
        begin_current_request(agent, messages, "Check current home anniversaries.")
        original = copy.deepcopy(messages)
        provider.record_inbound("exact-preflight", "Check current home anniversaries.")
        provider.drain_once()

        def before(call_id, tool_name, arguments):
            scope = {"agent": agent, "tool_call": SimpleNamespace(id=call_id), "function_name": tool_name, "function_args": arguments, "json": json}
            exec(compile(seam("tool_before"), "exact-hermes-preflight-before", "exec"), scope)
            return scope["_sydney_decision"]

        def after(call_id, result):
            scope = {"agent": agent, "tool_call": SimpleNamespace(id=call_id), "function_name": "skill_view", "function_result": result, "result": result, "_is_error_result": False, "is_error": False}
            exec(compile(seam("tool_after"), "exact-hermes-preflight-after", "exec"), scope)

        try:
            blocked = before("premature-preview", PREVIEW, {})
            assert blocked is not None, "Exact Hermes seam executed a preview before current skill proof"
            assert "skill_view" in blocked.block_message
            assert getattr(agent, "_tool_guardrail_halt_decision", None) is None
            skill_root = Path(os.environ["HERMES_HOME"]) / "skills"
            skill_path = skill_root / "productivity" / SKILL_NAME / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text(SKILL_CONTENT)
            skills_tool.SKILLS_DIR = skill_root
            assert before("current-skill", "skill_view", {"name": SKILL_NAME}) is None
            result = skills_tool.skill_view(SKILL_NAME)
            assert json.loads(result)["content"] == SKILL_CONTENT
            after("current-skill", result)
            assert before("permitted-preview", PREVIEW, {}) is None
            assert messages == original

            messages = copy.deepcopy(messages) + [{"role": "user", "content": "[System: Continue]"}]
            assert before("after-compression", PREVIEW, {}) is None
            begin_current_request(agent, messages, "Check current home anniversaries.")
            assert before("new-real-request-preview", PREVIEW, {}) is not None
            assert agent.session_id == "same-history"
            assert getattr(agent, "_tool_guardrail_halt_decision", None) is None
        finally:
            provider.shutdown()
        """.replace("EXECUTOR", executor),
    )
