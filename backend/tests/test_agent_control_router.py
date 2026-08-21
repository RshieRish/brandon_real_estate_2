import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from database import get_db
from middleware.agent_control import require_agent_control
from models.agent_action_audit import AgentActionAudit
from models.booking import Booking
from models.lead import Lead
from routers import agent_control
from schemas.agent_control import WorkspaceGmailSendResponse
from services.agent_control_audit import write_agent_audit


class _FakeURL:
    path = "/api/v1/agent-control/status"


class _FakeRequest:
    method = "GET"
    url = _FakeURL()


class _FakeDB:
    def __init__(self, rows=None):
        self.added = []
        self.rows = rows or []
        self.flush = AsyncMock()
        self.last_statement = None

    def add(self, item):
        self.added.append(item)

    async def execute(self, statement):
        self.last_statement = statement
        return _FakeResult(self.rows)


class _FakeScalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return _FakeScalars(self.rows)


class AgentControlAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_agent_audit_stores_metadata_without_pii_body(self):
        db = _FakeDB()
        await write_agent_audit(
            db,
            request=_FakeRequest(),
            actor="hermes",
            action_id="status.read",
            status_code=200,
            allowed=True,
            response_meta={"count": 2, "ids": [1, 2]},
        )

        self.assertEqual(len(db.added), 1)
        audit = db.added[0]
        self.assertIsInstance(audit, AgentActionAudit)
        self.assertEqual(audit.actor, "hermes")
        self.assertEqual(audit.action_id, "status.read")
        self.assertEqual(audit.status_code, 200)
        self.assertTrue(audit.allowed)
        self.assertEqual(json.loads(audit.response_meta_json), {"count": 2, "ids": [1, 2]})
        db.flush.assert_awaited_once()


class AgentControlRouterTests(unittest.IsolatedAsyncioTestCase):
    def test_gmail_send_route_openapi_requires_uuid_and_keeps_agent_auth_dependency(self):
        app = FastAPI()
        app.include_router(
            agent_control.router,
            prefix="/api/v1/agent-control",
            tags=["agent-control"],
        )

        schema = app.openapi()
        operation = schema["paths"][
            "/api/v1/agent-control/workspace/gmail/send"
        ]["post"]
        request_schema = schema["components"]["schemas"]["WorkspaceGmailSendRequest"]
        required = set(request_schema["required"])
        self.assertIn("request_id", required)
        self.assertNotIn("retry_of_request_id", required)
        request_id_schema = request_schema["properties"]["request_id"]
        self.assertEqual(request_id_schema["type"], "string")
        self.assertEqual(request_id_schema["format"], "uuid")
        retry_schema = request_schema["properties"]["retry_of_request_id"]
        self.assertIn(
            {"type": "string", "format": "uuid"},
            retry_schema["anyOf"],
        )
        self.assertIn({"type": "null"}, retry_schema["anyOf"])
        self.assertTrue(operation["requestBody"]["required"])
        self.assertEqual(operation["tags"], ["agent-control"])

        route = next(
            route
            for route in app.routes
            if isinstance(route, APIRoute)
            and route.path == "/api/v1/agent-control/workspace/gmail/send"
        )
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        self.assertIn(require_agent_control, dependency_calls)
        self.assertIs(route.response_model, WorkspaceGmailSendResponse)

    def test_real_gmail_send_route_rejects_missing_agent_bearer_before_handler(self):
        app = FastAPI()
        app.include_router(agent_control.router, prefix="/api/v1/agent-control")
        app.dependency_overrides[get_db] = lambda: SimpleNamespace()

        with (
            patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
            patch("middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "agent-secret"),
            TestClient(app) as client,
        ):
            response = client.post(
                "/api/v1/agent-control/workspace/gmail/send",
                json={
                    "request_id": str(uuid4()),
                    "to": ["client@example.com"],
                    "subject": "Authenticated route",
                    "body_text": "This request has no bearer token.",
                    "confirmed_by_brandon": True,
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Invalid agent control credentials."},
        )

    def test_authenticated_http_rejects_missing_and_malformed_request_uuid_before_send(self):
        app = FastAPI()
        app.include_router(agent_control.router, prefix="/api/v1/agent-control")
        app.dependency_overrides[get_db] = lambda: SimpleNamespace()
        base_payload = {
            "to": ["client@example.com"],
            "subject": "Caller idempotency",
            "body_text": "This must not send without a valid caller UUID.",
            "confirmed_by_brandon": True,
        }

        with (
            patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
            patch("middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "agent-secret"),
            patch(
                "routers.agent_control.send_agent_gmail_with_origin",
                new_callable=AsyncMock,
                create=True,
            ) as durable_send,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            missing = client.post(
                "/api/v1/agent-control/workspace/gmail/send",
                json=base_payload,
                headers={"Authorization": "Bearer agent-secret"},
            )
            malformed = client.post(
                "/api/v1/agent-control/workspace/gmail/send",
                json={**base_payload, "request_id": "not-a-uuid"},
                headers={"Authorization": "Bearer agent-secret"},
            )

        self.assertEqual(missing.status_code, 422)
        self.assertEqual(malformed.status_code, 422)
        durable_send.assert_not_awaited()

    def test_authenticated_http_passes_valid_uuid_to_durable_send_and_returns_state(self):
        app = FastAPI()
        app.include_router(agent_control.router, prefix="/api/v1/agent-control")
        db = SimpleNamespace()
        app.dependency_overrides[get_db] = lambda: db
        request_id = uuid4()
        result = SimpleNamespace(
            request_id=request_id,
            message_id="provider-message",
            thread_id="provider-thread",
            delivery_state="succeeded",
            replayed=True,
        )

        with (
            patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True),
            patch("middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "agent-secret"),
            patch(
                "routers.agent_control.send_agent_gmail_with_origin",
                new_callable=AsyncMock,
                return_value=result,
                create=True,
            ) as durable_send,
            patch(
                "routers.agent_control.send_gmail_message",
                side_effect=AssertionError("legacy Gmail send must not run"),
                create=True,
            ),
            patch(
                "routers.agent_control.load_workspace_refresh_token_from_db",
                new_callable=AsyncMock,
                side_effect=AssertionError("legacy token loader must not run"),
                create=True,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            response = client.post(
                "/api/v1/agent-control/workspace/gmail/send",
                json={
                    "request_id": str(request_id),
                    "to": ["client@example.com"],
                    "subject": "Durable send",
                    "body_text": "Route through the durable origin state machine.",
                    "confirmed_by_brandon": True,
                },
                headers={"Authorization": "Bearer agent-secret"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["request_id"], str(request_id))
        self.assertEqual(payload["message_id"], "provider-message")
        self.assertEqual(payload["thread_id"], "provider-thread")
        self.assertEqual(payload["delivery_state"], "succeeded")
        self.assertTrue(payload["replayed"])
        durable_send.assert_awaited_once()
        call = durable_send.await_args.kwargs
        self.assertIs(call["db"], db)
        self.assertEqual(call["payload"].request_id, request_id)
        self.assertEqual(call["actor"], "hermes")

    async def test_status_returns_workspace_action_capabilities_and_audits(self):
        db = _FakeDB()
        result = await agent_control.agent_status(
            request=_FakeRequest(),
            db=db,
            agent={"actor": "hermes"},
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.risk_tier, "workspace_action_foundation")
        self.assertIn("leads.recent.read", result.capabilities)
        self.assertIn("workspace.gmail.draft.create", result.capabilities)
        self.assertIn("workspace.gmail.send", result.capabilities)
        self.assertIn("workspace.gmail.thread.read", result.capabilities)
        self.assertIn("workspace.calendar.event.create", result.capabilities)
        self.assertIn("workspace.contacts.search", result.capabilities)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].action_id, "status.read")

    async def test_actions_returns_read_and_workspace_actions(self):
        db = _FakeDB()
        result = await agent_control.list_agent_actions(
            request=_FakeRequest(),
            db=db,
            agent={"actor": "hermes"},
        )

        action_ids = {action.id for action in result.actions}
        self.assertIn("status.read", action_ids)
        self.assertIn("workspace.drive.search", action_ids)
        self.assertIn("workspace.gmail.draft.create", action_ids)
        self.assertIn("workspace.gmail.send", action_ids)
        self.assertIn("workspace.gmail.search", action_ids)
        self.assertIn("workspace.gmail.thread.read", action_ids)
        self.assertIn("workspace.drive.file.read", action_ids)
        self.assertIn("workspace.calendar.events.read", action_ids)
        self.assertIn("workspace.calendar.event.create", action_ids)
        self.assertIn("workspace.contacts.search", action_ids)
        send_action = next(action for action in result.actions if action.id == "workspace.gmail.send")
        self.assertTrue(send_action.side_effects)
        self.assertEqual(send_action.risk_tier, "human_confirm")
        calendar_create_action = next(
            action for action in result.actions if action.id == "workspace.calendar.event.create"
        )
        self.assertTrue(calendar_create_action.side_effects)
        self.assertEqual(calendar_create_action.risk_tier, "human_confirm")
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].action_id, "actions.read")

    async def test_recent_leads_masks_email_phone_and_caps_limit(self):
        lead = Lead(
            id=123,
            name="Jane Client",
            email="jane@example.com",
            phone="978-987-2806",
            source="sell_page",
            lead_type="seller",
            routing_status="new",
            notes="Interested in valuation meeting.",
            metadata_json=json.dumps({"intent": "valuation"}),
            created_at=datetime(2026, 6, 1, 12, 34, 56, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, 12, 34, 56, tzinfo=timezone.utc),
        )
        db = _FakeDB(rows=[lead])

        result = await agent_control.recent_leads(
            request=_FakeRequest(),
            limit=99,
            lead_type=None,
            routing_status=None,
            db=db,
            agent={"actor": "hermes"},
        )

        self.assertEqual(len(result.leads), 1)
        self.assertEqual(result.leads[0].email, "***@example.com")
        self.assertEqual(result.leads[0].phone, "***-***-2806")
        self.assertEqual(result.leads[0].metadata, {"intent": "valuation"})
        self.assertEqual(db.last_statement._limit_clause.value, 25)
        self.assertEqual(db.added[0].action_id, "leads.recent.read")

    async def test_recent_bookings_omits_google_event_id_and_exposes_boolean(self):
        booking = Booking(
            id=456,
            lead_id=123,
            name="Jane Client",
            email="jane@example.com",
            phone="978-987-2806",
            meeting_type="phone",
            context="seller",
            location="",
            scheduled_at=datetime(2026, 6, 2, 15, 0, tzinfo=timezone.utc),
            google_event_id="evt_123",
            notes="Valuation call.",
            created_at=datetime(2026, 6, 1, 12, 40, tzinfo=timezone.utc),
        )
        db = _FakeDB(rows=[booking])

        result = await agent_control.recent_bookings(
            request=_FakeRequest(),
            limit=10,
            meeting_type=None,
            context=None,
            db=db,
            agent={"actor": "hermes"},
        )

        self.assertEqual(len(result.bookings), 1)
        item = result.bookings[0]
        self.assertTrue(item.has_google_event)
        self.assertFalse(hasattr(item, "google_event_id"))
        self.assertEqual(item.email, "***@example.com")
        self.assertEqual(item.phone, "***-***-2806")
        self.assertEqual(db.added[0].action_id, "bookings.recent.read")


if __name__ == "__main__":
    unittest.main()
