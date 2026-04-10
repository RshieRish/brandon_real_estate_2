"""Google Calendar integration for reading events and creating bookings."""

import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow

from config import settings
from services.maps_service import get_travel_time

logger = logging.getLogger(__name__)

# Brandon's working hours (Eastern Time)
EASTERN_TZ = ZoneInfo("America/New_York")
WORK_START_HOUR = 9
WORK_END_HOUR = 18
SLOT_DURATION_MINUTES = 60
DAYS_AHEAD = 14
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


class CalendarIntegrationError(RuntimeError):
    """Raised when Google Calendar cannot be queried or written."""


class BookingValidationError(ValueError):
    """Raised when a requested booking time cannot be honored."""


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


def calendar_integration_ready() -> bool:
    return bool(
        settings.GOOGLE_CALENDAR_CLIENT_ID
        and settings.GOOGLE_CALENDAR_CLIENT_SECRET
        and settings.GOOGLE_CALENDAR_REFRESH_TOKEN
    )


def _calendar_client_config() -> dict:
    if not settings.GOOGLE_CALENDAR_CLIENT_ID or not settings.GOOGLE_CALENDAR_CLIENT_SECRET:
        raise CalendarIntegrationError(
            "Google Calendar OAuth client credentials are not configured."
        )

    return {
        "web": {
            "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID,
            "client_secret": settings.GOOGLE_CALENDAR_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _build_oauth_flow(state: str | None = None) -> Flow:
    flow = Flow.from_client_config(
        _calendar_client_config(),
        scopes=CALENDAR_SCOPES,
        state=state,
    )
    flow.redirect_uri = settings.GOOGLE_CALENDAR_REDIRECT_URI
    return flow


def get_auth_url(state: str) -> tuple[str, str]:
    """Return the Google OAuth consent URL for connecting Calendar."""
    flow = _build_oauth_flow(state=state)
    return flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )


def persist_refresh_token(refresh_token: str, env_path: Path | None = None) -> None:
    """Persist the Calendar refresh token in the backend .env file."""
    target_path = env_path or ENV_PATH
    if target_path.exists():
        lines = target_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    persisted = False
    for index, line in enumerate(lines):
        if line.startswith("GOOGLE_CALENDAR_REFRESH_TOKEN="):
            lines[index] = f"GOOGLE_CALENDAR_REFRESH_TOKEN={refresh_token}"
            persisted = True
            break

    if not persisted:
        lines.append(f"GOOGLE_CALENDAR_REFRESH_TOKEN={refresh_token}")

    target_path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def exchange_code(code: str, state: str) -> str:
    """Exchange a Google OAuth code for a refresh token and persist it."""
    flow = _build_oauth_flow(state=state)
    flow.fetch_token(code=code)
    refresh_token = flow.credentials.refresh_token
    if not refresh_token:
        raise CalendarIntegrationError(
            "Google did not return a refresh token. Disconnect the app in Google and try again."
        )

    persist_refresh_token(refresh_token)
    settings.GOOGLE_CALENDAR_REFRESH_TOKEN = refresh_token
    return refresh_token


def get_calendar_connection_status() -> dict[str, str | bool]:
    """Return the current Google Calendar integration state for the admin UI."""
    if not settings.GOOGLE_CALENDAR_CLIENT_ID or not settings.GOOGLE_CALENDAR_CLIENT_SECRET:
        return {
            "configured": False,
            "connected": False,
            "can_connect": False,
            "detail": "Google Calendar client credentials are missing.",
        }

    if not settings.GOOGLE_CALENDAR_REFRESH_TOKEN:
        return {
            "configured": True,
            "connected": False,
            "can_connect": True,
            "detail": "Google Calendar needs one-time authorization before Brandon can accept bookings.",
        }

    try:
        service = _get_calendar_service()
        service.calendars().get(calendarId="primary").execute()
    except Exception:
        logger.exception("Google Calendar connection check failed")
        return {
            "configured": True,
            "connected": False,
            "can_connect": True,
            "detail": "Google Calendar credentials are present, but the connection check failed. Reconnect Brandon's calendar.",
        }

    return {
        "configured": True,
        "connected": True,
        "can_connect": True,
        "detail": "Google Calendar is connected. Live availability and booking are enabled.",
    }


def _as_eastern(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=EASTERN_TZ)
    return dt.astimezone(EASTERN_TZ)


def _normalize_requested_day(target_date: datetime) -> datetime:
    if (
        target_date.tzinfo is not None
        and target_date.utcoffset() == timedelta(0)
        and target_date.hour == 0
        and target_date.minute == 0
        and target_date.second == 0
        and target_date.microsecond == 0
    ):
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            tzinfo=EASTERN_TZ,
        )
    return _as_eastern(target_date)


def _parse_google_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _as_eastern(parsed)


def _get_calendar_service():
    """Build a Google Calendar API service using OAuth credentials.

    This uses a service-account-style refresh token stored in env vars.
    In production, you'd complete the OAuth flow once to obtain a refresh
    token for Brandon's account, then store it as an env var.
    """
    if not settings.GOOGLE_CALENDAR_CLIENT_ID or not settings.GOOGLE_CALENDAR_CLIENT_SECRET:
        raise CalendarIntegrationError(
            "Google Calendar OAuth client credentials are not configured."
        )

    if not settings.GOOGLE_CALENDAR_REFRESH_TOKEN:
        raise CalendarIntegrationError(
            "Google Calendar needs one-time authorization before Brandon can accept bookings."
        )

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
        start_et = _as_eastern(start)
        end_et = _as_eastern(end)
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start_et.isoformat(),
                timeMax=end_et.isoformat(),
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
                    start=_parse_google_datetime(event_start),
                    end=_parse_google_datetime(event_end),
                    location=item.get("location", ""),
                )
            )
        return events

    except CalendarIntegrationError:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch calendar events")
        raise CalendarIntegrationError("Unable to fetch Brandon's calendar events.") from exc


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
        start_et = _as_eastern(start)
        end_et = _as_eastern(end)
        event_body = {
            "summary": summary,
            "location": location,
            "description": description,
            "start": {"dateTime": start_et.isoformat(), "timeZone": "America/New_York"},
            "end": {"dateTime": end_et.isoformat(), "timeZone": "America/New_York"},
            "attendees": [{"email": attendee_email}],
            "reminders": {"useDefault": True},
        }
        created = service.events().insert(calendarId="primary", body=event_body, sendUpdates="all").execute()
        logger.info("Created calendar event: %s", created.get("id"))
        return created.get("id")

    except CalendarIntegrationError:
        raise
    except Exception as exc:
        logger.exception("Failed to create calendar event")
        raise CalendarIntegrationError("Unable to create a Google Calendar event.") from exc


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
    target_day = _normalize_requested_day(target_date)

    # Skip weekends
    if target_day.weekday() >= 5:
        return []

    day_start = target_day.replace(
        hour=WORK_START_HOUR, minute=0, second=0, microsecond=0
    )
    day_end = target_day.replace(
        hour=WORK_END_HOUR, minute=0, second=0, microsecond=0
    )

    # Fetch existing events for the day (with padding for travel)
    fetch_start = day_start - timedelta(hours=2)
    fetch_end = day_end + timedelta(hours=2)
    events = await get_events(fetch_start, fetch_end)

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


async def ensure_booking_slot_available(
    scheduled_at: datetime,
    meeting_type: str = "phone",
    client_location: str = "",
) -> tuple[datetime, datetime]:
    """Validate that a booking time is inside office hours and still free."""
    slot_start = _as_eastern(scheduled_at)
    slot_end = slot_start + timedelta(minutes=SLOT_DURATION_MINUTES)

    if slot_start.weekday() >= 5:
        raise BookingValidationError("Appointments are only available Monday through Friday.")

    if (
        slot_start.hour < WORK_START_HOUR
        or slot_start.minute != 0
        or slot_start.second != 0
        or slot_end.hour > WORK_END_HOUR
        or (slot_end.hour == WORK_END_HOUR and slot_end.minute > 0)
    ):
        raise BookingValidationError("Appointments must start on the hour between 9 AM and 6 PM Eastern.")

    if meeting_type == "in_person" and not client_location.strip():
        raise BookingValidationError("An address is required for in-person meetings.")

    events = await get_events(slot_start - timedelta(hours=2), slot_end + timedelta(hours=2))
    overlaps_existing = any(
        event.start < slot_end and event.end > slot_start
        for event in events
    )
    if overlaps_existing:
        raise BookingValidationError("That time is no longer available on Brandon's calendar.")

    if meeting_type == "in_person":
        travel_ok = await _check_travel_feasibility(
            slot_start,
            slot_end,
            events,
            client_location,
        )
        if not travel_ok:
            raise BookingValidationError(
                "That in-person time no longer works with Brandon's travel schedule."
            )

    return slot_start, slot_end


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
