"""Google Calendar integration for reading events and creating bookings."""

import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import settings
from services.maps_service import get_travel_time

logger = logging.getLogger(__name__)

# Brandon's working hours (Eastern Time)
WORK_START_HOUR = 9
WORK_END_HOUR = 17
SLOT_DURATION_MINUTES = 60
DAYS_AHEAD = 14


@dataclass
class CalendarEvent:
    """A simplified calendar event with location data."""
    summary: str
    start: datetime
    end: datetime
    location: str = ""


@dataclass
class TimeSlot:
    """An available booking slot."""
    start: datetime
    end: datetime
    available: bool = True
    conflict_reason: str = ""


def _get_calendar_service():
    """Build a Google Calendar API service using OAuth credentials.

    This uses a service-account-style refresh token stored in env vars.
    In production, you'd complete the OAuth flow once to obtain a refresh
    token for Brandon's account, then store it as an env var.
    """
    creds = Credentials(
        token=None,
        refresh_token=settings.GOOGLE_CALENDAR_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CALENDAR_CLIENT_ID,
        client_secret=settings.GOOGLE_CALENDAR_CLIENT_SECRET,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


async def get_events(start: datetime, end: datetime) -> list[CalendarEvent]:
    """Fetch Brandon's calendar events between start and end."""
    try:
        service = _get_calendar_service()
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = []
        for item in events_result.get("items", []):
            event_start = item["start"].get("dateTime", item["start"].get("date"))
            event_end = item["end"].get("dateTime", item["end"].get("date"))

            events.append(
                CalendarEvent(
                    summary=item.get("summary", "Busy"),
                    start=datetime.fromisoformat(event_start),
                    end=datetime.fromisoformat(event_end),
                    location=item.get("location", ""),
                )
            )
        return events

    except Exception:
        logger.exception("Failed to fetch calendar events")
        return []


async def create_event(
    summary: str,
    start: datetime,
    end: datetime,
    attendee_email: str,
    location: str = "",
    description: str = "",
) -> str | None:
    """Create a Google Calendar event and return the event ID."""
    try:
        service = _get_calendar_service()
        event_body = {
            "summary": summary,
            "location": location,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": "America/New_York"},
            "end": {"dateTime": end.isoformat(), "timeZone": "America/New_York"},
            "attendees": [{"email": attendee_email}],
            "reminders": {"useDefault": True},
        }
        created = service.events().insert(calendarId="primary", body=event_body, sendUpdates="all").execute()
        logger.info("Created calendar event: %s", created.get("id"))
        return created.get("id")

    except Exception:
        logger.exception("Failed to create calendar event")
        return None


async def get_available_slots(
    target_date: datetime,
    meeting_type: str = "phone",
    client_location: str = "",
) -> list[dict]:
    """Get available time slots for a specific date, filtered by travel time.

    Args:
        target_date: The date to check availability for.
        meeting_type: "phone", "video", or "in_person".
        client_location: Address for in-person meetings.

    Returns:
        List of slot dicts with start, end, and availability info.
    """
    # Define the day's boundaries in Eastern Time
    day_start = target_date.replace(
        hour=WORK_START_HOUR, minute=0, second=0, microsecond=0
    )
    day_end = target_date.replace(
        hour=WORK_END_HOUR, minute=0, second=0, microsecond=0
    )

    # Fetch existing events for the day (with padding for travel)
    fetch_start = day_start - timedelta(hours=2)
    fetch_end = day_end + timedelta(hours=2)
    events = await get_events(fetch_start, fetch_end)

    # Skip weekends
    if target_date.weekday() >= 5:
        return []

    # Generate all possible slots for the day
    slots: list[dict] = []
    current = day_start
    while current + timedelta(minutes=SLOT_DURATION_MINUTES) <= day_end:
        slot_end = current + timedelta(minutes=SLOT_DURATION_MINUTES)

        # Check if this slot overlaps with any existing event
        is_busy = any(
            event.start < slot_end and event.end > current
            for event in events
        )

        if is_busy:
            current = slot_end
            continue

        # For phone/video, no travel check needed
        if meeting_type in ("phone", "video"):
            slots.append({
                "start": current.isoformat(),
                "end": slot_end.isoformat(),
                "available": True,
            })
            current = slot_end
            continue

        # For in-person meetings, check travel time constraints
        if meeting_type == "in_person" and client_location:
            travel_ok = await _check_travel_feasibility(
                current, slot_end, events, client_location
            )
            if not travel_ok:
                current = slot_end
                continue

        slots.append({
            "start": current.isoformat(),
            "end": slot_end.isoformat(),
            "available": True,
        })
        current = slot_end

    return slots


async def _check_travel_feasibility(
    slot_start: datetime,
    slot_end: datetime,
    events: list[CalendarEvent],
    client_location: str,
) -> bool:
    """Check if Brandon can physically travel to/from a slot.

    Finds the nearest events before and after the proposed slot,
    calculates travel time using the Maps API, and returns True
    only if there's enough time including the configured buffer.
    """
    buffer = settings.TRAVEL_BUFFER_MINUTES
    brandon_home = settings.BRANDON_DEFAULT_LOCATION

    # Find the event immediately before this slot
    prev_event = None
    for event in events:
        if event.end <= slot_start:
            prev_event = event

    # Find the event immediately after this slot
    next_event = None
    for event in events:
        if event.start >= slot_end:
            next_event = event
            break

    # Check travel FROM previous appointment TO client
    if prev_event:
        origin = prev_event.location or brandon_home
        travel_mins = await get_travel_time(origin, client_location)
        earliest_arrival = prev_event.end + timedelta(minutes=travel_mins + buffer)
        if earliest_arrival > slot_start:
            logger.info(
                "Travel conflict: prev event ends %s, need %d+%d min to reach %s, slot starts %s",
                prev_event.end, travel_mins, buffer, client_location, slot_start,
            )
            return False

    # Check travel FROM client location TO next appointment
    if next_event:
        destination = next_event.location or brandon_home
        travel_mins = await get_travel_time(client_location, destination)
        latest_departure = next_event.start - timedelta(minutes=travel_mins + buffer)
        if slot_end > latest_departure:
            logger.info(
                "Travel conflict: slot ends %s, need %d+%d min to reach %s, next event starts %s",
                slot_end, travel_mins, buffer, destination, next_event.start,
            )
            return False

    return True
