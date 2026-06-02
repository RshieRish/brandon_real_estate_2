import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from models.agent_action_audit import AgentActionAudit
from models.booking import Booking
from models.lead import Lead
from routers import agent_control
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
