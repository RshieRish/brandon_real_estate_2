from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

OVERLAY = Path(__file__).resolve().parents[2] / "hermes" / "overlay"
sys.path.insert(0, str(OVERLAY))

from sydney_memory_provider import SydneyMemoryProvider
from sydney_retry import AUTOMATIC_CONTINUATION_MESSAGE
from sydney_spool import SydneySpool

NAMESPACE = UUID("9eaa27c5-e399-4c3b-b329-8ee2d80f87c0")


class SyntheticRateLimit(RuntimeError):
    status_code = 429


class InMemorySydneyBackend:
    """Deterministic service-contract double; it never opens a socket."""

    def __init__(self) -> None:
        self.identity_id = str(uuid5(NAMESPACE, "identity:brandon"))
        self.clock = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
        self.events: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.tools: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.command_reads: list[dict[str, Any]] = []
        self.external_writes: list[dict[str, Any]] = []

    @staticmethod
    def _id(label: str) -> str:
        return str(uuid5(NAMESPACE, label))

    def ingest_events(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("ingest", payload))
        event_ids: list[str] = []
        inserted = replayed = 0
        for event in payload["events"]:
            source_key = str(event["source_event_key"])
            event_id = self._id(f"event:{source_key}")
            event_ids.append(event_id)
            if source_key in self.events:
                replayed += 1
                continue
            self.events[source_key] = {"id": event_id, **event}
            inserted += 1
        return {
            "identity_id": self.identity_id,
            "session_id": self._id(f"session:{payload['hermes_session_id']}"),
            "logical_conversation_id": payload["logical_conversation_id"],
            "event_ids": event_ids,
            "inserted_count": inserted,
            "replayed_count": replayed,
        }

    def retrieve_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("retrieve", payload))
        ordered = list(self.events.values())[-20:]
        rendered = "\n".join(
            f"{event.get('content', '')} [source: {event['id']}]" for event in ordered
        )
        return {
            "identity_id": self.identity_id,
            "logical_conversation_id": payload["logical_conversation_id"],
            "rendered_context": rendered,
            "estimated_tokens": len(rendered.encode("utf-8")) // 4 + 1,
            "sections": [
                {
                    "kind": "recent_events",
                    "text": rendered,
                    "source_event_ids": [event["id"] for event in ordered],
                    "estimated_tokens": len(rendered.encode("utf-8")) // 4 + 1,
                }
            ],
            "degraded": False,
            "newest_event_id": ordered[-1]["id"] if ordered else None,
        }

    def history_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("history", payload))
        query = str(payload.get("query") or "").lower()
        matches = [
            event
            for event in self.events.values()
            if not query or query in str(event.get("content") or "").lower()
        ]
        return {
            "events": matches[: payload.get("limit", 25)],
            "total": len(matches),
            "truncated": False,
        }

    def start_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("run", payload))
        run_id = self._id(f"run:{payload['platform_message_id']}")
        replayed = run_id in self.runs
        if not replayed:
            self.runs[run_id] = {
                "id": run_id,
                "identity_id": payload["identity_id"],
                "platform_message_id": payload["platform_message_id"],
                "state": "queued",
                "attempt_count": 0,
                "lease_owner": None,
                "terminal_deadline_at": payload["terminal_deadline_at"],
                "next_attempt_at": None,
            }
        return {"run": dict(self.runs[run_id]), "replayed": replayed}

    def claim_runs(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("claim", payload))
        claimed: list[dict[str, Any]] = []
        for run in self.runs.values():
            next_attempt = run.get("next_attempt_at")
            due = run["state"] == "queued" or (
                run["state"] == "waiting_retry"
                and isinstance(next_attempt, datetime)
                and next_attempt <= self.clock
            )
            if not due or run["identity_id"] != payload.get("identity_id"):
                continue
            run["state"] = "running"
            run["attempt_count"] += 1
            run["lease_owner"] = payload["lease_owner"]
            run["next_attempt_at"] = None
            claimed.append(dict(run))
            break
        return {"runs": claimed}

    def update_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("run_update", payload))
        run = self.runs[payload["run_id"]]
        if run.get("lease_owner") and payload.get("lease_owner") != run["lease_owner"]:
            raise RuntimeError("invalid lease")
        run.update(payload)
        if isinstance(run.get("next_attempt_at"), str):
            run["next_attempt_at"] = datetime.fromisoformat(run["next_attempt_at"])
        if run["state"] != "running":
            run["lease_owner"] = None
        return dict(run)

    def start_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("tool_before", payload))
        key = (payload["run_id"], payload["tool_call_id"])
        existing = self.tools.get(key)
        if existing is None:
            self.tools[key] = {**payload, "state": "started", "result_event_id": None}
            decision = "execute"
        elif existing["state"] == "succeeded" and existing["result_event_id"]:
            decision = "restore_result"
        elif existing["side_effect_class"] == "read_only":
            decision = "repeat_read"
        else:
            decision = "block_uncertain"
        return {"state": self.tools[key]["state"], "replay_decision": decision}

    def update_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("tool_after", payload))
        key = (payload["run_id"], payload["tool_call_id"])
        self.tools[key].update(payload)
        return {"state": payload["state"], "replay_decision": "restore_result"}

    def command_contacts_search(self, query: str) -> dict[str, Any]:
        request = {"query": query, "page_size": 25}
        self.command_reads.append(request)
        return {
            "total": 1,
            "contacts": [
                {
                    "contact_id": self._id("command-contact:jamie"),
                    "display_name": "Jamie Example",
                    "stage": "Active",
                    "source": "Command",
                }
            ],
        }


def _provider(tmp_path: Path, backend: InMemorySydneyBackend) -> SydneyMemoryProvider:
    provider = SydneyMemoryProvider(
        backend=backend,
        start_drain_thread=False,
        shutdown_deadline_seconds=0.2,
    )
    provider.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="telegram",
        user_id="brandon-user",
        chat_id="brandon-chat",
        display_label="Brandon",
        agent_context="primary",
    )
    return provider


def test_no_network_durable_context_and_command_read_e2e(tmp_path: Path) -> None:
    backend = InMemorySydneyBackend()
    provider = _provider(tmp_path, backend)

    provider.record_inbound(
        "telegram-1",
        "The private showing code is aurum-17.",
        occurred_at="2026-08-25T18:00:00+00:00",
    )
    assert backend.calls == []
    provider.drain_once()
    assert [name for name, _payload in backend.calls[:3]] == ["ingest", "run", "claim"]

    first_context = provider.prefetch("What is the showing code?")
    assert "aurum-17" in first_context
    assert "[source:" in first_context

    result = backend.command_contacts_search("Jamie")
    provider.record_tool_before(
        run_id=provider.active_run_id or "",
        tool_call_id="command-read-1",
        tool_name="command_contacts_search",
        arguments={"query": "Jamie", "page_size": 25},
        side_effect_class="read_only",
    )
    provider.drain_once()
    provider.record_tool_after(
        run_id=provider.active_run_id or "",
        tool_call_id="command-read-1",
        tool_name="command_contacts_search",
        state="succeeded",
        result_content=json.dumps(result, sort_keys=True),
    )
    provider.drain_once()
    provider.complete_active_run("Jamie is an active Command contact.")

    provider.on_session_switch(
        "session-2", parent_session_id="session-1", reason="compression"
    )
    provider.record_inbound("telegram-2", "Remind me of the private showing code.")
    provider.drain_once()
    continued_context = provider.prefetch("showing code")
    provider.complete_active_run("The private showing code is aurum-17.")

    assert "aurum-17" in continued_context
    assert provider.spool.pending_count == 0
    assert backend.command_reads == [{"query": "Jamie", "page_size": 25}]
    assert backend.external_writes == []
    assert {record["tool_name"] for record in backend.tools.values()} == {
        "command_contacts_search"
    }
    assert not any(
        marker in name
        for name, _payload in backend.calls
        for marker in ("gmail", "calendar", "crm_write")
    )


def test_retry_wait_survives_restart_and_finishes_exactly_once(tmp_path: Path) -> None:
    backend = InMemorySydneyBackend()
    first = _provider(tmp_path, backend)
    first.record_inbound("telegram-retry", "Complete this when capacity returns.")
    first.drain_once()
    run_id = first.active_run_id
    assert run_id is not None

    message = first.defer_retry(SyntheticRateLimit("retry in 2s"), attempt=2)
    assert message == AUTOMATIC_CONTINUATION_MESSAGE
    waiting_update = [
        payload for name, payload in backend.calls if name == "run_update"
    ][-1]
    assert waiting_update["state"] == "waiting_retry"
    assert waiting_update["parsed_retry_delay_seconds"] == 2
    due_at = backend.runs[run_id]["next_attempt_at"]
    first.shutdown()

    backend.clock = due_at - timedelta(milliseconds=1)
    assert backend.claim_runs(
        {
            "lease_owner": "hermes:replacement:42",
            "identity_id": backend.identity_id,
            "limit": 1,
        }
    ) == {"runs": []}
    backend.clock = due_at
    claimed = backend.claim_runs(
        {
            "lease_owner": "hermes:replacement:42",
            "identity_id": backend.identity_id,
            "limit": 1,
        }
    )
    assert [run["id"] for run in claimed["runs"]] == [run_id]

    spool = SydneySpool(tmp_path / "sydney_spool.db")
    spool.set_meta(
        f"claimed_run:{run_id}",
        {"lease_owner": "hermes:replacement:42", "attempt_count": 2},
    )
    spool.close()
    second = _provider(tmp_path, backend)
    second.record_inbound("telegram-retry", "Complete this when capacity returns.")
    second.complete_active_run("Eventually done.")

    assert backend.claim_runs(
        {
            "lease_owner": "hermes:duplicate:99",
            "identity_id": backend.identity_id,
            "limit": 1,
        }
    ) == {"runs": []}
    final_events = [
        event
        for event in backend.events.values()
        if event.get("content") == "Eventually done."
    ]
    succeeded = [
        payload
        for name, payload in backend.calls
        if name == "run_update" and payload["state"] == "succeeded"
    ]
    assert len(final_events) == 1
    assert len(succeeded) == 1
    assert backend.runs[run_id]["state"] == "succeeded"
    assert backend.external_writes == []
