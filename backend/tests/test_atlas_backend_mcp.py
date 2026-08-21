import importlib.util
import json
from pathlib import Path
import unittest
from uuid import uuid4


def _load_bridge_module():
    module_path = Path(__file__).resolve().parents[2] / "hermes" / "atlas_backend_mcp.py"
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


class AtlasBackendMcpTests(unittest.TestCase):
    def setUp(self):
        self.bridge = _load_bridge_module()

    def test_lists_expected_backend_tools(self):
        tools = self.bridge.list_tools()
        tool_names = {tool["name"] for tool in tools}

        self.assertEqual(len(tools), 16)
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
            },
        )
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")

        by_name = {tool["name"]: tool for tool in tools}
        self.assertIn("confirmed_by_brandon", by_name["gmail_send"]["description"])
        self.assertIn("confirmed_by_brandon", by_name["calendar_event_create"]["description"])

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

    def test_gmail_send_passes_caller_request_uuids_through_without_generating_them(self):
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

    def test_gmail_send_surfaces_backend_uuid_validation_without_bridge_fabrication(self):
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
        self.assertEqual(response["message"], "request_id is required")
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
        self.assertEqual(json.loads(result["content"][0]["text"]), {"draft_id": "draft-1"})

    def test_call_tool_returns_backend_error_as_mcp_error_content(self):
        error = self.bridge.BackendRequestError(
            status_code=422,
            message="Calendar event creation requires confirmed_by_brandon=true.",
            payload={"detail": "Calendar event creation requires confirmed_by_brandon=true."},
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
        self.assertIn("confirmed_by_brandon", payload["message"])

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
        self.assertEqual(len(listed["result"]["tools"]), 16)

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
        self.assertEqual(client.calls[-1]["path"], "/api/v1/agent-control/workspace/status")
        self.assertEqual(
            json.loads(called["result"]["content"][0]["text"]),
            {"connected": True},
        )

        notification = self.bridge.handle_request(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            client=client,
        )
        self.assertIsNone(notification)
