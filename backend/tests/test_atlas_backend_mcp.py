import importlib.util
import json
import signal
from pathlib import Path
import socket
import time
import unittest
from unittest.mock import patch
from uuid import uuid4


def _load_bridge_module():
    module_path = (
        Path(__file__).resolve().parents[2] / "hermes" / "atlas_backend_mcp.py"
    )
    spec = importlib.util.spec_from_file_location("atlas_backend_mcp", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeBackendClient:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else {"ok": True}
        self.error = error
        self.calls = []

    def request(self, method, path, *, params=None, body=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params or {},
                "body": body,
            }
        )
        if self.error:
            raise self.error
        return self.response


class TrickleResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        deadline = time.monotonic() + 3.05
        while time.monotonic() < deadline:
            time.sleep(0.05)
        return b'{"ok":true}'


class ImmediateResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"ok":true}'


class AtlasBackendMcpTests(unittest.TestCase):
    def setUp(self):
        self.bridge = _load_bridge_module()

    def test_lists_expected_backend_tools(self):
        tools = self.bridge.list_tools()
        tool_names = {tool["name"] for tool in tools}

        self.assertEqual(len(tools), 26)
        self.assertEqual(
            [tool["name"] for tool in tools],
            [
                "status_read",
                "actions_list",
                "leads_recent",
                "bookings_recent",
                "workspace_status",
                "drive_search",
                "drive_file_read",
                "gmail_search",
                "gmail_thread_read",
                "gmail_draft_create",
                "gmail_send",
                "docs_create",
                "sheets_append",
                "calendar_events_read",
                "calendar_event_create",
                "contacts_search",
                "crm_tasks_read",
                "crm_task_suggestions_read",
                "crm_task_clarifications_answer",
                "crm_task_drafts_create",
                "crm_task_suggestions_approval_link",
                "crm_task_suggestions_dismiss_proposal",
                "context_history_search",
                "command_contacts_search",
                "command_contact_audience_preview",
                "command_contact_celebrations_preview",
            ],
        )
        self.assertEqual(
            tool_names,
            {
                "status_read",
                "actions_list",
                "leads_recent",
                "bookings_recent",
                "workspace_status",
                "drive_search",
                "drive_file_read",
                "gmail_search",
                "gmail_thread_read",
                "gmail_draft_create",
                "gmail_send",
                "docs_create",
                "sheets_append",
                "calendar_events_read",
                "calendar_event_create",
                "contacts_search",
                "crm_tasks_read",
                "crm_task_suggestions_read",
                "crm_task_clarifications_answer",
                "crm_task_drafts_create",
                "crm_task_suggestions_approval_link",
                "crm_task_suggestions_dismiss_proposal",
                "context_history_search",
                "command_contacts_search",
                "command_contact_audience_preview",
                "command_contact_celebrations_preview",
            },
        )
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")

        by_name = {tool["name"]: tool for tool in tools}
        self.assertIn("confirmed_by_brandon", by_name["gmail_send"]["description"])
        self.assertIn(
            "confirmed_by_brandon", by_name["calendar_event_create"]["description"]
        )

        gmail_send_schema = by_name["gmail_send"]["inputSchema"]
        self.assertEqual(
            gmail_send_schema["required"],
            [
                "request_id",
                "to",
                "subject",
                "body_text",
                "confirmed_by_brandon",
            ],
        )
        request_id_schema = gmail_send_schema["properties"]["request_id"]
        self.assertEqual(request_id_schema["type"], "string")
        self.assertEqual(request_id_schema["format"], "uuid")
        self.assertIn("caller", request_id_schema["description"].lower())
        retry_schema = gmail_send_schema["properties"]["retry_of_request_id"]
        self.assertEqual(retry_schema["type"], "string")
        self.assertEqual(retry_schema["format"], "uuid")
        self.assertIn("not-delivered", retry_schema["description"].lower())
        self.assertEqual(
            by_name["contacts_search"]["description"],
            "Search Google Contacts only; never Command.",
        )

        history = by_name["context_history_search"]
        self.assertEqual(
            history["description"],
            "Search Sydney's durable conversation history by text, date, type, event window, or recent conversation.",
        )
        self.assertEqual(
            set(history["inputSchema"]["properties"]),
            {
                "identity_id",
                "query",
                "event_types",
                "started_at",
                "ended_at",
                "around_event_id",
                "recent_conversations",
                "limit",
                "window_size",
            },
        )
        self.assertEqual(history["inputSchema"]["required"], ["identity_id"])
        self.assertEqual(
            history["inputSchema"]["anyOf"],
            [
                {"required": ["query"]},
                {"required": ["around_event_id"]},
                {
                    "properties": {"recent_conversations": {"const": True}},
                    "required": ["recent_conversations"],
                },
            ],
        )
        command_search = by_name["command_contacts_search"]
        self.assertEqual(
            command_search["description"],
            "Search Command only; never Google Contacts or the admin UI.",
        )
        self.assertEqual(
            command_search["inputSchema"]["properties"]["page_size"]["maximum"],
            25,
        )
        self.assertIn("cursor", command_search["inputSchema"]["properties"])
        self.assertNotIn("page", command_search["inputSchema"]["properties"])
        preview = by_name["command_contact_audience_preview"]
        self.assertNotIn("page", preview["inputSchema"]["properties"])
        self.assertNotIn("page_size", preview["inputSchema"]["properties"])
        celebrations = by_name["command_contact_celebrations_preview"]
        self.assertEqual(celebrations["inputSchema"]["required"], ["month"])
        self.assertEqual(
            celebrations["inputSchema"]["properties"],
            {
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "include_birthdays": {"type": "boolean", "default": True},
                "include_home_anniversaries": {
                    "type": "boolean",
                    "default": True,
                },
            },
        )

        answer_schema = by_name["crm_task_clarifications_answer"]["inputSchema"]
        self.assertEqual(
            answer_schema["required"], ["code", "expected_version", "answer"]
        )
        self.assertEqual(
            set(answer_schema["properties"]),
            {"code", "expected_version", "answer"},
        )
        self.assertIn(
            "untrusted hermes draft evidence",
            by_name["crm_task_clarifications_answer"]["description"].lower(),
        )
        self.assertEqual(
            by_name["crm_task_suggestions_read"]["inputSchema"]["properties"],
            {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
        )
        self.assertEqual(
            by_name["crm_task_drafts_create"]["inputSchema"]["required"],
            ["request_id", "title"],
        )
        self.assertEqual(
            set(by_name["crm_task_drafts_create"]["inputSchema"]["properties"]),
            {"request_id", "title", "description", "priority", "due_at", "contact_id"},
        )
        self.assertEqual(
            by_name["crm_task_suggestions_approval_link"]["inputSchema"]["required"],
            ["suggestion_id", "expected_version", "expected_payload_hash"],
        )

        dismiss = by_name["crm_task_suggestions_dismiss_proposal"]
        self.assertIn("non-authoritative", dismiss["description"].lower())
        self.assertIn("cannot dismiss", dismiss["description"].lower())
        self.assertIn("suppress", dismiss["description"].lower())
        self.assertIn("release", dismiss["description"].lower())
        self.assertIn("review proposal", dismiss["description"].lower())
        self.assertEqual(
            dismiss["inputSchema"]["required"],
            ["suggestion_id", "request_id", "expected_version", "reason"],
        )

        forbidden = {
            "crm_task_suggestions_dismiss",
            "crm_task_suggestions_approve",
            "crm_tasks_create_confirmed",
            "crm_tasks_archive",
            "crm_tasks_restore",
        }
        self.assertFalse(tool_names.intersection(forbidden))
        self.assertEqual(
            [tool["name"] for tool in tools][:22],
            [
                "status_read",
                "actions_list",
                "leads_recent",
                "bookings_recent",
                "workspace_status",
                "drive_search",
                "drive_file_read",
                "gmail_search",
                "gmail_thread_read",
                "gmail_draft_create",
                "gmail_send",
                "docs_create",
                "sheets_append",
                "calendar_events_read",
                "calendar_event_create",
                "contacts_search",
                "crm_tasks_read",
                "crm_task_suggestions_read",
                "crm_task_clarifications_answer",
                "crm_task_drafts_create",
                "crm_task_suggestions_approval_link",
                "crm_task_suggestions_dismiss_proposal",
            ],
        )
        self.assertEqual(
            {
                name: by_name[name]["description"]
                for name in tool_names
                if name.startswith("crm_")
            },
            {
                "crm_tasks_read": "Read active CRM task summaries for review.",
                "crm_task_suggestions_read": "Read CRM task suggestions awaiting Brandon review.",
                "crm_task_clarifications_answer": (
                    "Answer an opaque Sydney clarification with the required suggestion version "
                    "using untrusted Hermes draft evidence; this cannot approve or create a task."
                ),
                "crm_task_drafts_create": (
                    "Create a non-authoritative Brandon-owned review draft from untrusted "
                    "Hermes draft evidence; it cannot create a confirmed task."
                ),
                "crm_task_suggestions_approval_link": (
                    "Create a fragment-only handoff link with the required suggestion version "
                    "and payload hash for Brandon's authenticated review; actual approval remains "
                    "authenticated Command-only."
                ),
                "crm_task_suggestions_dismiss_proposal": (
                    "Record a non-authoritative review proposal with the required suggestion "
                    "version only; it cannot dismiss, suppress, or release anything."
                ),
            },
        )

    def test_gmail_send_passes_caller_request_uuids_through_without_generating_them(
        self,
    ):
        client = FakeBackendClient(response={"delivery_state": "succeeded"})
        request_id = str(uuid4())
        retry_of_request_id = str(uuid4())
        payload = {
            "request_id": request_id,
            "retry_of_request_id": retry_of_request_id,
            "to": ["client@example.com"],
            "subject": "Inspection follow-up",
            "body_text": "The report is attached.",
            "confirmed_by_brandon": True,
        }

        result = self.bridge.call_tool("gmail_send", payload, client=client)

        self.assertEqual(
            client.calls,
            [
                {
                    "method": "POST",
                    "path": "/api/v1/agent-control/workspace/gmail/send",
                    "params": {},
                    "body": payload,
                }
            ],
        )
        self.assertEqual(
            json.loads(result["content"][0]["text"]),
            {"delivery_state": "succeeded"},
        )

        no_request_id = {
            "to": ["client@example.com"],
            "subject": "Missing caller UUID",
            "body_text": "The backend must reject this payload.",
            "confirmed_by_brandon": True,
        }
        self.bridge.call_tool("gmail_send", no_request_id, client=client)
        self.assertEqual(client.calls[-1]["body"], no_request_id)
        self.assertNotIn("request_id", client.calls[-1]["body"])

    def test_gmail_send_surfaces_backend_uuid_validation_without_bridge_fabrication(
        self,
    ):
        error = self.bridge.BackendRequestError(
            status_code=422,
            message="request_id is required",
            payload={"detail": "request_id is required"},
        )
        client = FakeBackendClient(error=error)
        payload = {
            "to": ["client@example.com"],
            "subject": "Missing UUID",
            "body_text": "The bridge must not invent an idempotency key.",
            "confirmed_by_brandon": True,
        }

        result = self.bridge.call_tool("gmail_send", payload, client=client)

        self.assertTrue(result["isError"])
        response = json.loads(result["content"][0]["text"])
        self.assertEqual(response["status_code"], 422)
        self.assertEqual(response["message"], "Backend request failed.")
        self.assertEqual(client.calls[0]["body"], payload)
        self.assertNotIn("request_id", client.calls[0]["body"])

    def test_call_tool_maps_get_params_to_backend(self):
        client = FakeBackendClient(response={"leads": []})

        result = self.bridge.call_tool(
            "leads_recent",
            {"limit": 7, "lead_type": "seller", "routing_status": None},
            client=client,
        )

        self.assertEqual(
            client.calls,
            [
                {
                    "method": "GET",
                    "path": "/api/v1/agent-control/leads/recent",
                    "params": {"limit": 7, "lead_type": "seller"},
                    "body": None,
                }
            ],
        )
        self.assertEqual(json.loads(result["content"][0]["text"]), {"leads": []})
        self.assertNotIn("isError", result)

    def test_call_tool_maps_post_body_to_backend(self):
        client = FakeBackendClient(response={"draft_id": "draft-1"})
        payload = {
            "to": ["client@example.com"],
            "subject": "Follow up",
            "body_text": "Draft body",
        }

        result = self.bridge.call_tool("gmail_draft_create", payload, client=client)

        self.assertEqual(
            client.calls,
            [
                {
                    "method": "POST",
                    "path": "/api/v1/agent-control/workspace/gmail/draft",
                    "params": {},
                    "body": payload,
                }
            ],
        )
        self.assertEqual(
            json.loads(result["content"][0]["text"]), {"draft_id": "draft-1"}
        )

    def test_crm_tools_map_typed_requests_and_responses_to_backend(self):
        suggestion_id = str(uuid4())
        request_id = str(uuid4())
        client = FakeBackendClient(
            response={"suggestion_id": suggestion_id, "replayed": False}
        )

        read_result = self.bridge.call_tool(
            "crm_tasks_read", {"limit": 7}, client=client
        )
        suggestions_result = self.bridge.call_tool(
            "crm_task_suggestions_read", {"limit": 11}, client=client
        )
        answer_result = self.bridge.call_tool(
            "crm_task_clarifications_answer",
            {
                "code": "opaque-code",
                "expected_version": 3,
                "answer": {"kind": "due_none"},
            },
            client=client,
        )
        draft_result = self.bridge.call_tool(
            "crm_task_drafts_create",
            {
                "request_id": request_id,
                "title": "Prepare the offer review",
                "description": "Draft context for Brandon.",
                "priority": "high",
                "due_at": "2026-08-23T09:00:00+00:00",
                "contact_id": 19,
            },
            client=client,
        )
        approval_result = self.bridge.call_tool(
            "crm_task_suggestions_approval_link",
            {
                "suggestion_id": suggestion_id,
                "expected_version": 3,
                "expected_payload_hash": "a" * 64,
            },
            client=client,
        )
        dismiss_result = self.bridge.call_tool(
            "crm_task_suggestions_dismiss_proposal",
            {
                "suggestion_id": suggestion_id,
                "request_id": request_id,
                "expected_version": 3,
                "reason": "The requested follow-up is already complete.",
            },
            client=client,
        )

        self.assertEqual(
            client.calls,
            [
                {
                    "method": "GET",
                    "path": "/api/v1/agent-control/crm/tasks",
                    "params": {"limit": 7},
                    "body": None,
                },
                {
                    "method": "GET",
                    "path": "/api/v1/agent-control/crm/task-suggestions",
                    "params": {"limit": 11},
                    "body": None,
                },
                {
                    "method": "POST",
                    "path": "/api/v1/agent-control/crm/task-clarifications/answer",
                    "params": {},
                    "body": {
                        "code": "opaque-code",
                        "expected_version": 3,
                        "answer": {"kind": "due_none"},
                    },
                },
                {
                    "method": "POST",
                    "path": "/api/v1/agent-control/crm/task-drafts",
                    "params": {},
                    "body": {
                        "request_id": request_id,
                        "title": "Prepare the offer review",
                        "description": "Draft context for Brandon.",
                        "priority": "high",
                        "due_at": "2026-08-23T09:00:00+00:00",
                        "contact_id": 19,
                    },
                },
                {
                    "method": "POST",
                    "path": f"/api/v1/agent-control/crm/task-suggestions/{suggestion_id}/approval-link",
                    "params": {},
                    "body": {"expected_version": 3, "expected_payload_hash": "a" * 64},
                },
                {
                    "method": "POST",
                    "path": f"/api/v1/agent-control/crm/task-suggestions/{suggestion_id}/dismiss-proposal",
                    "params": {},
                    "body": {
                        "request_id": request_id,
                        "expected_version": 3,
                        "reason": "The requested follow-up is already complete.",
                    },
                },
            ],
        )
        for result in (
            read_result,
            suggestions_result,
            answer_result,
            draft_result,
            approval_result,
            dismiss_result,
        ):
            self.assertEqual(
                json.loads(result["content"][0]["text"]),
                {"suggestion_id": suggestion_id, "replayed": False},
            )

    def test_context_and_command_read_tools_map_exact_bounded_bodies(self):
        identity_id = str(uuid4())
        event_id = str(uuid4())
        client = FakeBackendClient(response={"ok": True})
        history = {
            "identity_id": identity_id,
            "query": "gold folder",
            "event_types": ["user", "assistant"],
            "started_at": "2026-08-01T00:00:00Z",
            "ended_at": "2026-08-25T23:59:59Z",
            "around_event_id": event_id,
            "recent_conversations": False,
            "limit": 10,
            "window_size": 3,
        }
        search = {
            "query": "Alex",
            "stage": "lead",
            "tag_ids": [7],
            "sources": ["kw_command"],
            "origins": ["recovered"],
            "cursor": "eyJ2IjoxLCJhIjo0MSwidSI6OTl9",
            "page_size": 25,
        }
        preview = {
            "stage": "lead",
            "tag_ids": [7],
            "sources": ["kw_command"],
            "origins": ["recovered"],
        }
        celebrations = {
            "month": 9,
            "include_birthdays": True,
            "include_home_anniversaries": True,
        }

        self.bridge.call_tool("context_history_search", history, client=client)
        self.bridge.call_tool("command_contacts_search", search, client=client)
        self.bridge.call_tool(
            "command_contact_audience_preview",
            preview,
            client=client,
        )
        self.bridge.call_tool(
            "command_contact_celebrations_preview",
            celebrations,
            client=client,
        )

        self.assertEqual(
            client.calls,
            [
                {
                    "method": "POST",
                    "path": "/api/v1/agent-control/context/history/search",
                    "params": {},
                    "body": history,
                },
                {
                    "method": "POST",
                    "path": "/api/v1/agent-control/crm/command-contacts/search",
                    "params": {},
                    "body": search,
                },
                {
                    "method": "POST",
                    "path": "/api/v1/agent-control/crm/command-contact-audiences/preview",
                    "params": {},
                    "body": preview,
                },
                {
                    "method": "POST",
                    "path": "/api/v1/agent-control/crm/command-contact-celebrations/preview",
                    "params": {},
                    "body": celebrations,
                },
            ],
        )

    def test_backend_timeout_is_bounded_and_errors_do_not_leak_secrets(self):
        client = self.bridge.BackendClient(
            base_url="https://backend.example.test",
            token="bridge-secret-value",
            timeout_seconds=999,
        )
        with patch.object(
            self.bridge.request,
            "urlopen",
            side_effect=socket.timeout("bridge-secret-value"),
        ) as urlopen:
            with self.assertRaises(self.bridge.BackendRequestError) as raised:
                client.request("GET", "/api/v1/agent-control/crm/tasks")

        self.assertEqual(raised.exception.status_code, 504)
        self.assertNotIn("bridge-secret-value", raised.exception.message)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30.0)

        error = self.bridge.BackendRequestError(
            status_code=502,
            message="upstream leaked bridge-secret-value",
            payload={"detail": "bridge-secret-value"},
        )
        result = self.bridge.call_tool(
            "crm_tasks_read", {}, client=FakeBackendClient(error=error)
        )
        text = result["content"][0]["text"]
        self.assertTrue(result["isError"])
        self.assertNotIn("bridge-secret-value", text)

    def test_backend_deadline_interrupts_a_trickle_response_without_leaking_secrets(
        self,
    ):
        client = self.bridge.BackendClient(
            base_url="https://backend.example.test",
            token="bridge-secret-value",
            timeout_seconds=1,
        )
        started_at = time.monotonic()
        with patch.object(
            self.bridge.request, "urlopen", return_value=TrickleResponse()
        ):
            with self.assertRaises(self.bridge.BackendRequestError) as raised:
                client.request("GET", "/api/v1/agent-control/crm/tasks")
        elapsed = time.monotonic() - started_at

        self.assertEqual(raised.exception.status_code, 504)
        self.assertLess(elapsed, 2.0)
        self.assertNotIn("bridge-secret-value", raised.exception.message)

    def test_backend_deadline_includes_payload_preparation_before_io(self):
        client = self.bridge.BackendClient(
            base_url="https://backend.example.test",
            token="bridge-secret-value",
            timeout_seconds=1,
        )

        def delayed_drop_none(value):
            time.sleep(3.05)
            return value

        started_at = time.monotonic()
        with (
            patch.object(self.bridge, "_drop_none", side_effect=delayed_drop_none),
            patch.object(self.bridge.request, "urlopen") as urlopen,
        ):
            with self.assertRaises(self.bridge.BackendRequestError) as raised:
                client.request(
                    "POST",
                    "/api/v1/agent-control/crm/task-drafts",
                    body={"title": "Prepare review"},
                )
        elapsed = time.monotonic() - started_at

        self.assertEqual(raised.exception.status_code, 504)
        self.assertLess(elapsed, 2.0)
        self.assertFalse(urlopen.called)
        self.assertNotIn("bridge-secret-value", raised.exception.message)

    def test_url_errors_distinguish_timeouts_from_backend_unavailability(self):
        client = self.bridge.BackendClient(
            base_url="https://backend.example.test",
            token="bridge-secret-value",
            timeout_seconds=1,
        )
        for reason, status_code in (
            (socket.timeout(), 504),
            (OSError("connection refused"), 502),
        ):
            with patch.object(
                self.bridge.request,
                "urlopen",
                side_effect=self.bridge.error.URLError(reason),
            ):
                with self.assertRaises(self.bridge.BackendRequestError) as raised:
                    client.request("GET", "/api/v1/agent-control/crm/tasks")
            self.assertEqual(raised.exception.status_code, status_code)
            self.assertNotIn("bridge-secret-value", raised.exception.message)

    def test_backend_refuses_an_active_process_alarm_without_delaying_it(self):
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        if previous_timer != (0.0, 0.0):
            self.skipTest("the test process already owns ITIMER_REAL")

        fired = []

        def existing_alarm(signum, frame):
            fired.append(signum)

        try:
            signal.signal(signal.SIGALRM, existing_alarm)
            signal.setitimer(signal.ITIMER_REAL, 0.2)
            client = self.bridge.BackendClient(
                base_url="https://backend.example.test",
                token="bridge-secret-value",
                timeout_seconds=1,
            )
            raised = None
            with patch.object(
                self.bridge.request, "urlopen", return_value=ImmediateResponse()
            ) as urlopen:
                try:
                    client.request("GET", "/api/v1/agent-control/crm/tasks")
                except self.bridge.BackendRequestError as error:
                    raised = error
            self.assertFalse(urlopen.called)
            self.assertIs(signal.getsignal(signal.SIGALRM), existing_alarm)
            time.sleep(0.3)
            self.assertIsNotNone(raised)
            self.assertEqual(raised.status_code, 503)
            self.assertEqual(fired, [signal.SIGALRM])
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    def test_invalid_timeout_never_mutates_the_process_alarm(self):
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        if previous_timer != (0.0, 0.0):
            self.skipTest("the test process already owns ITIMER_REAL")

        for invalid_timeout in (float("nan"), float("inf"), float("-inf"), 0, -1):
            client = self.bridge.BackendClient(
                base_url="https://backend.example.test",
                token="bridge-secret-value",
                timeout_seconds=invalid_timeout,
            )
            with patch.object(self.bridge.request, "urlopen") as urlopen:
                with self.assertRaises(self.bridge.BackendRequestError) as raised:
                    client.request("GET", "/api/v1/agent-control/crm/tasks")
            self.assertEqual(raised.exception.status_code, 500)
            self.assertNotIn("bridge-secret-value", raised.exception.message)
            self.assertFalse(urlopen.called)
            self.assertIs(signal.getsignal(signal.SIGALRM), previous_handler)
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL), previous_timer)

    def test_partial_deadline_setup_failure_restores_the_process_alarm(self):
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        if previous_timer != (0.0, 0.0):
            self.skipTest("the test process already owns ITIMER_REAL")

        deadline = self.bridge._HardRequestDeadline(1)
        try:
            with patch.object(
                self.bridge.signal, "setitimer", side_effect=ValueError("invalid timer")
            ):
                with self.assertRaises(ValueError):
                    deadline.__enter__()
            self.assertIs(signal.getsignal(signal.SIGALRM), previous_handler)
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL), previous_timer)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    def test_call_tool_returns_backend_error_as_mcp_error_content(self):
        error = self.bridge.BackendRequestError(
            status_code=422,
            message="Calendar event creation requires confirmed_by_brandon=true.",
            payload={
                "detail": "Calendar event creation requires confirmed_by_brandon=true."
            },
        )
        client = FakeBackendClient(error=error)

        result = self.bridge.call_tool(
            "calendar_event_create",
            {"summary": "Intro call"},
            client=client,
        )

        self.assertTrue(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["status_code"], 422)
        self.assertEqual(payload["message"], "Backend request failed.")

    def test_json_rpc_initialize_tools_call_and_notification(self):
        client = FakeBackendClient(response={"connected": True})

        initialize = self.bridge.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            },
            client=client,
        )
        self.assertEqual(initialize["id"], 1)
        self.assertEqual(initialize["result"]["serverInfo"]["name"], "atlas-backend")
        self.assertIn("tools", initialize["result"]["capabilities"])

        listed = self.bridge.handle_request(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            client=client,
        )
        self.assertEqual(listed["id"], 2)
        self.assertEqual(len(listed["result"]["tools"]), 26)

        called = self.bridge.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "workspace_status", "arguments": {}},
            },
            client=client,
        )
        self.assertEqual(called["id"], 3)
        self.assertEqual(
            client.calls[-1]["path"], "/api/v1/agent-control/workspace/status"
        )
        self.assertEqual(
            json.loads(called["result"]["content"][0]["text"]),
            {"connected": True},
        )

        notification = self.bridge.handle_request(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            client=client,
        )
        self.assertIsNone(notification)
