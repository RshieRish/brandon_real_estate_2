import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import text

from database import AsyncSessionLocal
from models.notification_job import NotificationJob
from services.notification_service import (
    attempt_notification_delivery,
    calculate_next_attempt_at,
    enqueue_notification,
)


class NotificationQueueModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_notification_job_table_has_retry_fields(self):
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'notification_jobs'
                    ORDER BY ordinal_position
                    """
                )
            )
            columns = [row[0] for row in rows]

        self.assertIn("event_type", columns)
        self.assertIn("status", columns)
        self.assertIn("attempt_count", columns)
        self.assertIn("next_attempt_at", columns)
        self.assertIn("delivered_at", columns)


class _FakeDB:
    def __init__(self):
        self.added = []
        self.flush = AsyncMock()

    def add(self, item):
        self.added.append(item)


class NotificationQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_notification_creates_pending_job(self):
        db = _FakeDB()

        job = await enqueue_notification(
            db,
            event_type="lead_captured",
            payload={"name": "Jane Doe", "email": "jane@example.com"},
        )

        self.assertEqual(job.status, "pending")
        self.assertEqual(job.recipient, "info@soldwithsweeney.com")
        self.assertEqual(job.subject, "New Lead Captured — Lead")
        self.assertEqual(json.loads(job.payload_json)["email"], "jane@example.com")
        self.assertEqual(db.added, [job])

    async def test_send_job_marks_delivered_on_success(self):
        db = _FakeDB()
        job = NotificationJob(
            event_type="lead_captured",
            status="pending",
            recipient="info@soldwithsweeney.com",
            subject="New Lead Captured — Lead",
            payload_json=json.dumps({"name": "Jane Doe"}),
            attempt_count=0,
        )

        with patch("services.notification_service.send_internal_email", AsyncMock()):
            await attempt_notification_delivery(db, job)

        self.assertEqual(job.status, "delivered")
        self.assertEqual(job.attempt_count, 1)
        self.assertIsNotNone(job.delivered_at)
        self.assertIsNone(job.next_attempt_at)
        self.assertIsNone(job.last_error)

    async def test_send_job_schedules_retry_on_failure(self):
        db = _FakeDB()
        job = NotificationJob(
            event_type="lead_captured",
            status="pending",
            recipient="info@soldwithsweeney.com",
            subject="New Lead Captured — Lead",
            payload_json=json.dumps({"name": "Jane Doe"}),
            attempt_count=0,
        )

        with patch(
            "services.notification_service.send_internal_email",
            AsyncMock(side_effect=RuntimeError("smtp down")),
        ):
            await attempt_notification_delivery(db, job)

        self.assertEqual(job.status, "failed")
        self.assertEqual(job.attempt_count, 1)
        self.assertIn("smtp down", job.last_error or "")
        self.assertIsNotNone(job.next_attempt_at)

    def test_calculate_next_attempt_at_uses_backoff_schedule(self):
        now = datetime.now(timezone.utc)

        first_retry = calculate_next_attempt_at(1)
        later_retry = calculate_next_attempt_at(4)

        self.assertGreater(first_retry, now)
        self.assertGreater(later_retry, first_retry)


if __name__ == "__main__":
    unittest.main()
