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
        self.execute = AsyncMock(return_value=_FakeResult())
        self.flush = AsyncMock()
        self.refresh = AsyncMock()

    def add(self, item):
        self.added.append(item)


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
        ), patch("routers.booking.create_event", AsyncMock(return_value=None)), patch(
            "routers.booking.notify_new_booking",
            AsyncMock(),
        ):
            with self.assertRaises(HTTPException):
                await create_booking(payload, db)


if __name__ == "__main__":
    unittest.main()
