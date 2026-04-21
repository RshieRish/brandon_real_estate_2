import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from routers.booking import create_booking
from schemas.booking import BookingCreate
from services import calendar_service


EASTERN = ZoneInfo("America/New_York")


class _FakeResult:
    def scalar_one_or_none(self):
        return None


class _FakeDB:
    def __init__(self):
        self.added = []
        self.commit = AsyncMock()
        self.execute = AsyncMock(return_value=_FakeResult())
        self._id_counter = 1
        self.flush = AsyncMock(side_effect=self._flush_impl)
        self.refresh = AsyncMock(side_effect=self._refresh_impl)

    def add(self, item):
        self.added.append(item)

    async def _flush_impl(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = self._id_counter
                self._id_counter += 1

    async def _refresh_impl(self, item):
        if getattr(item, "id", None) is None:
            item.id = self._id_counter
            self._id_counter += 1


class _FakeDBWithBookingFlushFailure(_FakeDB):
    def __init__(self):
        super().__init__()
        flush_count = {"count": 0}

        async def _flush():
            flush_count["count"] += 1
            if flush_count["count"] >= 2:
                raise RuntimeError("booking insert failed")

        self.flush = AsyncMock(side_effect=_flush)


class CalendarAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_available_slots_includes_five_pm_hour_and_skips_busy_events(self):
        busy_event = calendar_service.CalendarEvent(
            summary="Busy",
            start=datetime(2026, 4, 13, 10, 0, tzinfo=EASTERN),
            end=datetime(2026, 4, 13, 11, 0, tzinfo=EASTERN),
            location="Office",
        )
        target_date = datetime(2026, 4, 13, 12, 0, tzinfo=EASTERN)

        with patch.object(
            calendar_service,
            "get_events",
            AsyncMock(return_value=[busy_event]),
        ):
            slots = await calendar_service.get_available_slots(
                target_date=target_date,
                meeting_type="phone",
            )

        starts = {
            datetime.fromisoformat(slot["start"]).astimezone(EASTERN).strftime("%H:%M")
            for slot in slots
        }

        self.assertIn("09:00", starts)
        self.assertIn("17:00", starts)
        self.assertNotIn("10:00", starts)

    async def test_get_available_slots_treats_date_only_requests_as_eastern_business_day(self):
        target_date = datetime(2026, 4, 13, 0, 0, tzinfo=timezone.utc)

        with patch.object(
            calendar_service,
            "get_events",
            AsyncMock(return_value=[]),
        ):
            slots = await calendar_service.get_available_slots(
                target_date=target_date,
                meeting_type="phone",
            )

        starts = {
            datetime.fromisoformat(slot["start"]).astimezone(EASTERN).strftime("%Y-%m-%d %H:%M")
            for slot in slots
        }
        self.assertIn("2026-04-13 09:00", starts)

    async def test_get_available_slots_skips_same_day_slots_that_already_started(self):
        target_date = datetime(2026, 4, 13, 12, 0, tzinfo=EASTERN)
        mocked_now = datetime(2026, 4, 13, 14, 16, tzinfo=EASTERN)

        with patch.object(
            calendar_service,
            "_current_eastern_time",
            return_value=mocked_now,
        ), patch.object(
            calendar_service,
            "get_events",
            AsyncMock(return_value=[]),
        ):
            slots = await calendar_service.get_available_slots(
                target_date=target_date,
                meeting_type="phone",
            )

        starts = {
            datetime.fromisoformat(slot["start"]).astimezone(EASTERN).strftime("%H:%M")
            for slot in slots
        }
        self.assertNotIn("14:00", starts)
        self.assertIn("15:00", starts)

    async def test_get_events_raises_when_calendar_service_is_unavailable(self):
        start = datetime(2026, 4, 13, 9, 0, tzinfo=EASTERN)
        end = datetime(2026, 4, 13, 18, 0, tzinfo=EASTERN)

        with patch.object(
            calendar_service,
            "_get_calendar_service",
            side_effect=RuntimeError("calendar auth missing"),
        ):
            with self.assertRaises(RuntimeError):
                await calendar_service.get_events(start, end)


class CreateBookingTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_booking_slot_available_rejects_already_started_slot(self):
        scheduled_at = datetime(2026, 4, 13, 14, 0, tzinfo=EASTERN)
        mocked_now = datetime(2026, 4, 13, 14, 16, tzinfo=EASTERN)

        with patch.object(
            calendar_service,
            "_current_eastern_time",
            return_value=mocked_now,
        ):
            with self.assertRaises(calendar_service.BookingValidationError):
                await calendar_service.ensure_booking_slot_available(
                    scheduled_at=scheduled_at,
                    meeting_type="phone",
                )

    async def test_create_booking_raises_if_google_calendar_event_is_not_created(self):
        db = _FakeDB()
        payload = BookingCreate(
            name="Codex Test",
            email="codex-test@example.com",
            phone="9785550101",
            meeting_type="phone",
            context="general",
            scheduled_at=datetime(2026, 4, 13, 9, 0, tzinfo=EASTERN),
            location="",
            notes="calendar failure regression",
        )

        with patch(
            "routers.booking.ensure_booking_slot_available",
            AsyncMock(
                return_value=(
                    datetime(2026, 4, 13, 9, 0, tzinfo=EASTERN),
                    datetime(2026, 4, 13, 10, 0, tzinfo=EASTERN),
                )
            ),
        ), patch(
            "routers.booking.enqueue_notification_in_new_session",
            AsyncMock(),
        ) as attempt_enqueue_mock, patch(
            "routers.booking.create_event",
            AsyncMock(return_value=None),
        ), patch(
            "routers.booking.enqueue_notification",
            AsyncMock(),
        ) as confirmed_enqueue_mock, patch(
            "routers.booking.run_notification_retry_pass",
            AsyncMock(return_value=0),
        ):
            with self.assertRaises(HTTPException):
                await create_booking(payload, db)

        attempt_enqueue_mock.assert_awaited_once()
        confirmed_enqueue_mock.assert_not_awaited()

    async def test_create_booking_deletes_calendar_event_if_booking_insert_fails(self):
        db = _FakeDBWithBookingFlushFailure()
        payload = BookingCreate(
            name="Codex Test",
            email="codex-test@example.com",
            phone="9785550101",
            meeting_type="phone",
            context="general",
            scheduled_at=datetime(2026, 4, 13, 9, 0, tzinfo=EASTERN),
            location="",
            notes="db failure rollback regression",
        )

        with patch(
            "routers.booking.ensure_booking_slot_available",
            AsyncMock(
                return_value=(
                    datetime(2026, 4, 13, 9, 0, tzinfo=EASTERN),
                    datetime(2026, 4, 13, 10, 0, tzinfo=EASTERN),
                )
            ),
        ), patch(
            "routers.booking.enqueue_notification_in_new_session",
            AsyncMock(),
        ), patch("routers.booking.create_event", AsyncMock(return_value="google-event-123")), patch(
            "routers.booking.delete_event",
            AsyncMock(),
        ) as delete_event_mock, patch(
            "routers.booking.enqueue_notification",
            AsyncMock(),
        ), patch(
            "routers.booking.run_notification_retry_pass",
            AsyncMock(return_value=0),
        ):
            with self.assertRaises(RuntimeError):
                await create_booking(payload, db)

        delete_event_mock.assert_awaited_once_with("google-event-123")

    async def test_create_booking_enqueues_attempt_and_confirmation_notifications(self):
        db = _FakeDB()
        payload = BookingCreate(
            name="Codex Test",
            email="codex-test@example.com",
            phone="9785550101",
            meeting_type="phone",
            context="general",
            scheduled_at=datetime(2026, 4, 13, 9, 0, tzinfo=EASTERN),
            location="",
            notes="booking success regression",
        )

        with patch(
            "routers.booking.ensure_booking_slot_available",
            AsyncMock(
                return_value=(
                    datetime(2026, 4, 13, 9, 0, tzinfo=EASTERN),
                    datetime(2026, 4, 13, 10, 0, tzinfo=EASTERN),
                )
            ),
        ), patch(
            "routers.booking.enqueue_notification_in_new_session",
            AsyncMock(),
        ) as attempt_enqueue_mock, patch(
            "routers.booking.create_event",
            AsyncMock(return_value="google-event-123"),
        ), patch(
            "routers.booking.enqueue_notification",
            AsyncMock(),
        ) as confirmed_enqueue_mock, patch(
            "routers.booking.run_notification_retry_pass",
            AsyncMock(return_value=1),
        ) as retry_mock:
            booking = await create_booking(payload, db)

        attempt_enqueue_mock.assert_awaited_once()
        confirmed_enqueue_mock.assert_awaited_once()
        db.commit.assert_awaited_once()
        retry_mock.assert_awaited_once_with(limit=5)
        self.assertEqual(booking.google_event_id, "google-event-123")


if __name__ == "__main__":
    unittest.main()
