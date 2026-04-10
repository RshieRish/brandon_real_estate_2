import unittest
from unittest.mock import ANY, AsyncMock, patch

from fastapi import BackgroundTasks

from models.funnel import Funnel
from routers.chat import CaptureLeadRequest, capture_lead_from_chat
from routers.funnels import RegisterRequest, register_for_funnel
from routers.leads import create_lead
from schemas.lead import LeadCreate


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    def __init__(self, execute_results=None):
        self.added = []
        self._id_counter = 1
        self.commit = AsyncMock()
        self.execute = AsyncMock(side_effect=execute_results or [])

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = self._id_counter
                self._id_counter += 1

    async def refresh(self, item):
        if getattr(item, "id", None) is None:
            item.id = self._id_counter
            self._id_counter += 1


class LeadNotificationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_lead_enqueues_lead_notification(self):
        db = _FakeDB()
        payload = LeadCreate(
            name="Jane Doe",
            email="jane@example.com",
            phone="555-0100",
            source="website",
            lead_type="seller",
            metadata_={"address": "1 Main St"},
        )

        with patch("routers.leads.enqueue_notification", AsyncMock()) as enqueue_mock, patch(
            "routers.leads.run_notification_retry_pass",
            AsyncMock(return_value=1),
        ) as retry_mock:
            lead = await create_lead(payload, BackgroundTasks(), db)

        enqueue_mock.assert_awaited_once_with(
            db,
            event_type="lead_captured",
            payload={
                "lead_id": lead.id,
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "555-0100",
                "source": "website",
                "lead_type": "seller",
                "metadata": {"address": "1 Main St"},
            },
        )
        db.commit.assert_awaited_once()
        retry_mock.assert_awaited_once_with(limit=5)

    async def test_capture_chat_lead_enqueues_chat_notification(self):
        db = _FakeDB()
        payload = CaptureLeadRequest(
            name="Chat Lead",
            email="chat@example.com",
            phone="555-0101",
            lead_type="buyer",
            lead_context={"entry": "widget"},
        )

        with patch("routers.chat.enqueue_notification", AsyncMock()) as enqueue_mock, patch(
            "routers.chat.run_notification_retry_pass",
            AsyncMock(return_value=1),
        ) as retry_mock:
            response = await capture_lead_from_chat(payload, db)

        enqueue_mock.assert_awaited_once_with(
            db,
            event_type="chat_lead_captured",
            payload={
                "lead_id": response["id"],
                "name": "Chat Lead",
                "email": "chat@example.com",
                "phone": "555-0101",
                "lead_type": "buyer",
                "lead_context": {"entry": "widget"},
            },
        )
        db.commit.assert_awaited_once()
        retry_mock.assert_awaited_once_with(limit=5)

    async def test_funnel_register_enqueues_registration_notification(self):
        funnel = Funnel(
            id=99,
            title="Buyer Masterclass",
            slug="buyer-masterclass",
            audience="buyer",
            description="desc",
            cta_text="join",
            video_url="",
            lead_routing="calendar",
            generated_content="{}",
            status="published",
            registrations=0,
        )
        db = _FakeDB(execute_results=[_FakeResult(funnel)])
        payload = RegisterRequest(
            name="Funnel Lead",
            email="funnel@example.com",
            phone="555-0102",
        )

        with patch("routers.funnels.enqueue_notification", AsyncMock()) as enqueue_mock, patch(
            "routers.funnels.run_notification_retry_pass",
            AsyncMock(return_value=1),
        ) as retry_mock:
            await register_for_funnel("buyer-masterclass", payload, db)

        enqueue_mock.assert_awaited_once_with(
            db,
            event_type="funnel_registration",
            payload={
                "funnel_id": 99,
                "funnel_slug": "buyer-masterclass",
                "funnel_title": "Buyer Masterclass",
                "audience": "buyer",
                "name": "Funnel Lead",
                "email": "funnel@example.com",
                "phone": "555-0102",
            },
        )
        db.commit.assert_awaited_once()
        retry_mock.assert_awaited_once_with(limit=5)


if __name__ == "__main__":
    unittest.main()
