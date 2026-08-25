from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

OVERLAY = Path(__file__).resolve().parents[2] / "hermes" / "overlay"
sys.path.insert(0, str(OVERLAY))

from sydney_memory_provider import SydneyMemoryProvider  # noqa: E402


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_retrieve = False

    def ingest_events(self, payload: dict) -> dict:
        self.calls.append(("ingest", payload))
        return {
            "identity_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "session_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "logical_conversation_id": payload["logical_conversation_id"],
            "event_ids": ["cccccccc-cccc-4ccc-8ccc-cccccccccccc"],
            "inserted_count": len(payload["events"]),
            "replayed_count": 0,
        }

    def start_run(self, payload: dict) -> dict:
        self.calls.append(("run", payload))
        return {
            "run": {
                "id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                "identity_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "state": "queued",
            }
        }

    def claim_runs(self, payload: dict) -> dict:
        self.calls.append(("claim", payload))
        return {
            "runs": [
                {
                    "id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                    "identity_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "state": "running",
                    "lease_owner": payload["lease_owner"],
                    "attempt_count": 1,
                }
            ]
        }

    def retrieve_context(self, payload: dict) -> dict:
        self.calls.append(("retrieve", payload))
        if self.fail_retrieve:
            raise TimeoutError("backend unavailable")
        return {
            "identity_id": payload["identity_id"],
            "logical_conversation_id": payload["logical_conversation_id"],
            "rendered_context": "Remember the closing date. [source: cccc]",
            "estimated_tokens": 12,
            "sections": [
                {
                    "kind": "recent_events",
                    "text": "closing date",
                    "source_event_ids": ["cccccccc-cccc-4ccc-8ccc-cccccccccccc"],
                    "estimated_tokens": 3,
                }
            ],
            "degraded": False,
            "newest_event_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        }

    def history_search(self, payload: dict) -> dict:
        self.calls.append(("history", payload))
        return {"events": [], "total": 0, "truncated": False}

    def update_run(self, payload: dict) -> dict:
        self.calls.append(("run_update", payload))
        return payload

    def start_tool(self, payload: dict) -> dict:
        self.calls.append(("tool_before", payload))
        return {"state": "started", "replay_decision": "execute"}

    def update_tool(self, payload: dict) -> dict:
        self.calls.append(("tool_after", payload))
        return {"state": payload["state"], "replay_decision": "restore_result"}


def _provider(
    tmp_path: Path, backend: FakeBackend | None = None
) -> SydneyMemoryProvider:
    provider = SydneyMemoryProvider(
        backend=backend or FakeBackend(),
        start_drain_thread=False,
        shutdown_deadline_seconds=0.2,
    )
    provider.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="telegram",
        user_id="brandon",
        chat_id="private-chat",
        display_label="Brandon",
        agent_context="primary",
    )
    return provider


def test_provider_identity_is_stable_and_inbound_is_local_before_backend(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    provider = _provider(tmp_path, backend)

    local_id = provider.record_inbound(
        "telegram-message-1",
        "What did we decide?",
        occurred_at="2026-08-25T12:00:00+00:00",
    )

    assert local_id > 0
    assert backend.calls == []
    assert provider.spool.pending_count == 1
    logical_id = provider.logical_conversation_id
    assert UUID(logical_id).version == 5

    provider.drain_once()
    assert [call[0] for call in backend.calls] == ["ingest", "run", "claim"]
    assert backend.calls[1][1]["inbound_event_id"] == (
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    )
    assert backend.calls[1][1]["session_id"] == ("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    assert provider.spool.pending_count == 0


def test_run_completion_uses_the_claimed_lease_and_persists_final_event(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    provider = _provider(tmp_path, backend)
    provider.record_inbound("telegram-message-1", "Finish this")
    provider.drain_once()

    provider.complete_active_run("Finished automatically.")

    update = [payload for name, payload in backend.calls if name == "run_update"][-1]
    assert update["state"] == "succeeded"
    assert update["lease_owner"].startswith("hermes:")
    assert update["final_response_event_id"] == (
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    )


def test_replayed_inbound_restores_a_claimed_run_lease_after_restart(
    tmp_path: Path,
) -> None:
    first_backend = FakeBackend()
    first = _provider(tmp_path, first_backend)
    first.record_inbound("telegram-message-1", "Continue after restart")
    first.drain_once()
    first.spool.set_meta(
        "claimed_run:dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        {"lease_owner": "hermes:replacement:42", "attempt_count": 2},
    )
    first.shutdown()

    second_backend = FakeBackend()
    second = _provider(tmp_path, second_backend)
    second.record_inbound("telegram-message-1", "Continue after restart")
    second.complete_active_run("Recovered.")

    update = [payload for name, payload in second_backend.calls if name == "run_update"][-1]
    assert update["lease_owner"] == "hermes:replacement:42"


def test_prefetch_uses_fresh_source_linked_context_then_cached_fallback(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    provider = _provider(tmp_path, backend)
    provider.record_inbound(
        "message-1", "Closing date?", occurred_at="2026-08-25T12:00:00+00:00"
    )
    provider.drain_once()

    fresh = provider.prefetch("When do we close?", session_id="session-1")
    assert fresh == "Remember the closing date. [source: cccc]"
    retrieve_payload = [
        payload for name, payload in backend.calls if name == "retrieve"
    ][-1]
    assert retrieve_payload["token_budget"] == 16_000
    assert retrieve_payload["hermes_session_id"] == "session-1"

    backend.fail_retrieve = True
    cached = provider.prefetch("Try again", session_id="session-1")
    assert cached == fresh


def test_sync_turn_queues_only_new_visible_messages_and_tool_records(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    messages = [
        {"role": "system", "content": "hidden system"},
        {
            "role": "user",
            "id": "user-1",
            "content": "Visible user text",
            "reasoning": "hidden reasoning",
        },
        {
            "role": "assistant",
            "id": "assistant-1",
            "content": "Visible answer",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {
                        "name": "command_contacts_search",
                        "arguments": '{"query":"Brandon"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "command_contacts_search",
            "content": '{"total":1}',
        },
    ]

    provider.sync_turn(
        "Visible user text",
        "Visible answer",
        session_id="session-1",
        messages=messages,
    )
    first_count = provider.spool.pending_count
    provider.sync_turn(
        "Visible user text",
        "Visible answer",
        session_id="session-1",
        messages=messages,
    )

    assert first_count == 4
    assert provider.spool.pending_count == first_count
    payloads = [record.payload for record in provider.spool.pending(limit=10)]
    serialized = json.dumps(payloads)
    assert "Visible user text" in serialized
    assert "Visible answer" in serialized
    assert "command_contacts_search" in serialized
    assert "hidden system" not in serialized
    assert "hidden reasoning" not in serialized


def test_session_switch_preserves_logical_lineage(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    logical_id = provider.logical_conversation_id
    provider.on_session_switch(
        "session-2",
        parent_session_id="session-1",
        reset=False,
        reason="compression",
    )

    assert provider.session_id == "session-2"
    assert provider.logical_conversation_id == logical_id
    row = provider.spool.get_session("session-2")
    assert row["parent_session_id"] == "session-1"
    assert row["continuation_reason"] == "compression"


def test_history_tool_delegates_to_backend_contract(tmp_path: Path) -> None:
    backend = FakeBackend()
    provider = _provider(tmp_path, backend)
    provider.record_inbound(
        "message-1", "Seed", occurred_at="2026-08-25T12:00:00+00:00"
    )
    provider.drain_once()

    schemas = provider.get_tool_schemas()
    assert [schema["name"] for schema in schemas] == ["context_history_search"]
    result = json.loads(
        provider.handle_tool_call(
            "context_history_search",
            {"query": "closing", "limit": 5},
        )
    )

    assert result == {"events": [], "total": 0, "truncated": False}
    call_name, payload = backend.calls[-1]
    assert call_name == "history"
    assert payload["identity_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert payload["query"] == "closing"


def test_tool_hooks_queue_before_and_after_without_raw_secret(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    provider.record_tool_before(
        run_id="run-1",
        tool_call_id="call-1",
        tool_name="command_contacts_search",
        arguments={"Authorization": "Bearer top-secret", "query": "Brandon"},
        side_effect_class="read_only",
    )
    provider.record_tool_after(
        run_id="run-1",
        tool_call_id="call-1",
        state="succeeded",
        result_event_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    )

    serialized = json.dumps([r.payload for r in provider.spool.pending(limit=10)])
    assert "top-secret" not in serialized
    assert "REDACTED" in serialized
    assert [r.kind for r in provider.spool.pending(limit=10)] == [
        "tool_before",
        "tool_after",
    ]


def test_non_primary_context_does_not_persist(tmp_path: Path) -> None:
    provider = SydneyMemoryProvider(backend=FakeBackend(), start_drain_thread=False)
    provider.initialize(
        "session-subagent",
        hermes_home=str(tmp_path),
        platform="telegram",
        user_id="brandon",
        chat_id="private-chat",
        agent_context="subagent",
    )
    assert provider.is_available() is False
    assert provider.record_inbound("message-1", "Do not store") is None


def test_provider_rejects_an_identity_outside_the_runtime_allowlist(
    tmp_path: Path,
) -> None:
    provider = SydneyMemoryProvider(backend=FakeBackend(), start_drain_thread=False)
    with patch.dict(
        os.environ,
        {"SYDNEY_DURABLE_CONTEXT_ALLOWED_USER_IDS": "approved-user"},
        clear=False,
    ):
        provider.initialize(
            "session-unauthorized",
            hermes_home=str(tmp_path),
            platform="telegram",
            user_id="not-approved",
            chat_id="private-chat",
            agent_context="primary",
        )
    assert provider.is_available() is False
    assert provider.record_inbound("message-1", "Do not store") is None
