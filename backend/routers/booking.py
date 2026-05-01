"""Booking router — travel-time-aware scheduling via Google Calendar + Maps."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth import require_admin
from models.booking import Booking
from models.lead import Lead
from models.setting import Setting
from schemas.booking import BookingCreate, BookingOut
from services.calendar_service import (
    EASTERN_TZ,
    BookingValidationError,
    CalendarIntegrationError,
    create_event,
    delete_event,
    exchange_code,
    ensure_booking_slot_available,
    get_auth_url,
    get_available_slots,
    get_calendar_connection_status,
)
from services.notification_service import (
    enqueue_notification,
    enqueue_notification_in_new_session,
    run_notification_retry_pass,
)

logger = logging.getLogger(__name__)
router = APIRouter()
CALENDAR_OAUTH_STATE_TTL_MINUTES = 10
CALENDAR_REFRESH_TOKEN_KEY = "google_calendar_refresh_token"


async def load_calendar_refresh_token_from_db(db: AsyncSession) -> str:
    if settings.GOOGLE_CALENDAR_REFRESH_TOKEN:
        return settings.GOOGLE_CALENDAR_REFRESH_TOKEN

    result = await db.execute(select(Setting).where(Setting.key == CALENDAR_REFRESH_TOKEN_KEY))
    token_setting = result.scalar_one_or_none()
    if token_setting and token_setting.value:
        settings.GOOGLE_CALENDAR_REFRESH_TOKEN = token_setting.value
        return token_setting.value

    return ""


async def persist_calendar_refresh_token_to_db(db: AsyncSession, refresh_token: str) -> None:
    result = await db.execute(select(Setting).where(Setting.key == CALENDAR_REFRESH_TOKEN_KEY))
    token_setting = result.scalar_one_or_none()
    if token_setting:
        token_setting.value = refresh_token
        return

    db.add(Setting(key=CALENDAR_REFRESH_TOKEN_KEY, value=refresh_token))


def _build_calendar_oauth_state(admin_payload: dict) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=CALENDAR_OAUTH_STATE_TTL_MINUTES)
    return jwt.encode(
        {
            "sub": admin_payload.get("sub"),
            "purpose": "calendar_oauth",
            "exp": expires,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def _validate_calendar_oauth_state(state: str) -> None:
    try:
        payload = jwt.decode(
            state,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid calendar authorization state.") from exc

    if payload.get("purpose") != "calendar_oauth":
        raise HTTPException(status_code=401, detail="Invalid calendar authorization state.")


def _render_calendar_oauth_page(title: str, message: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>
      :root {{
        color-scheme: dark;
      }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #0a0a0a;
        color: #ffffff;
        font-family: Montserrat, Arial, sans-serif;
      }}
      main {{
        width: min(480px, calc(100vw - 32px));
        border: 1px solid rgba(234, 196, 105, 0.24);
        background: rgba(18, 18, 18, 0.92);
        padding: 32px;
        border-radius: 24px;
        box-shadow: 0 32px 80px rgba(0, 0, 0, 0.5);
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: 28px;
        color: #eac469;
      }}
      p {{
        margin: 0;
        line-height: 1.6;
        color: rgba(255, 255, 255, 0.76);
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{title}</h1>
      <p>{message}</p>
    </main>
  </body>
</html>"""


@router.get("/calendar/status")
async def calendar_status(
    _: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await load_calendar_refresh_token_from_db(db)
    return get_calendar_connection_status()


@router.get("/calendar/auth-url")
async def calendar_auth_url(admin_payload: dict = Depends(require_admin)):
    auth_url, _ = get_auth_url(_build_calendar_oauth_state(admin_payload))
    return {"auth_url": auth_url}


@router.get("/calendar/callback", response_class=HTMLResponse)
async def calendar_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if error:
        return HTMLResponse(
            _render_calendar_oauth_page(
                "Calendar Not Connected",
                f"Google returned an error: {error}. Please close this tab and try again from Settings.",
            ),
            status_code=400,
        )

    if not code or not state:
        return HTMLResponse(
            _render_calendar_oauth_page(
                "Calendar Not Connected",
                "Google did not return the authorization details we expected. Please close this tab and try again.",
            ),
            status_code=400,
        )

    try:
        _validate_calendar_oauth_state(state)
        refresh_token = exchange_code(code, state)
        await persist_calendar_refresh_token_to_db(db, refresh_token)
    except HTTPException as exc:
        return HTMLResponse(
            _render_calendar_oauth_page("Calendar Not Connected", exc.detail),
            status_code=exc.status_code,
        )
    except CalendarIntegrationError as exc:
        return HTMLResponse(
            _render_calendar_oauth_page("Calendar Not Connected", str(exc)),
            status_code=503,
        )

    return HTMLResponse(
        _render_calendar_oauth_page(
            "Calendar Connected",
            "Brandon's Google Calendar is now connected. You can close this tab and refresh the Settings page.",
        )
    )


@router.get("/available-slots")
async def available_slots(
    date: str = Query(
        ..., description="ISO date string, e.g. 2026-03-25"
    ),
    meeting_type: str = Query(
        "phone", description="phone | video | in_person"
    ),
    location: str = Query(
        "", description="Client address for in-person meetings"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Return available booking slots for a specific date.

    For in-person meetings with a location, slots are filtered by
    travel time between Brandon's existing calendar events and the
    requested meeting location using the Google Maps Distance Matrix API.

    Phone and video meetings skip travel-time checks.
    """
    try:
        target_date = datetime.fromisoformat(date).replace(tzinfo=EASTERN_TZ)
    except ValueError:
        return {"error": "Invalid date format. Use ISO format, e.g. 2026-03-25"}

    try:
        await load_calendar_refresh_token_from_db(db)
        slots = await get_available_slots(
            target_date=target_date,
            meeting_type=meeting_type,
            client_location=location,
        )
    except BookingValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CalendarIntegrationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "date": date,
        "meeting_type": meeting_type,
        "location": location,
        "slots": slots,
        "count": len(slots),
    }


@router.post("/", response_model=BookingOut)
async def create_booking(data: BookingCreate, db: AsyncSession = Depends(get_db)):
    """Create a booking, upsert the lead, and create a Google Calendar event."""
    try:
        await load_calendar_refresh_token_from_db(db)
        slot_start, meeting_end = await ensure_booking_slot_available(
            scheduled_at=data.scheduled_at,
            meeting_type=data.meeting_type,
            client_location=data.location or "",
        )
    except BookingValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CalendarIntegrationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await enqueue_notification_in_new_session(
        event_type="booking_attempted",
        payload={
            "name": data.name,
            "email": data.email,
            "phone": data.phone,
            "meeting_type": data.meeting_type,
            "context": data.context,
            "requested_at": data.scheduled_at.isoformat(),
            "location": data.location or "",
        },
    )

    # Upsert lead
    result = await db.execute(select(Lead).where(Lead.email == data.email))
    lead = result.scalar_one_or_none()
    if not lead:
        lead = Lead(
            name=data.name,
            email=data.email,
            phone=data.phone,
            source="booking",
            lead_type=data.context,
            metadata_json="{}",
        )
        db.add(lead)
        await db.flush()
    else:
        lead.routing_status = "booked"

    # Create Google Calendar event
    summary = f"Meeting with {data.name} — {data.context.title()}"
    description = (
        f"Meeting type: {data.meeting_type}\n"
        f"Context: {data.context}\n"
        f"Phone: {data.phone or 'N/A'}\n"
        f"Email: {data.email}\n"
    )
    if data.notes:
        description += f"Notes: {data.notes}\n"

    try:
        google_event_id = await create_event(
            summary=summary,
            start=slot_start,
            end=meeting_end,
            attendee_email=data.email,
            location=data.location or "",
            description=description,
        )
    except CalendarIntegrationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not google_event_id:
        raise HTTPException(
            status_code=503,
            detail="Booking could not be saved to Brandon's Google Calendar.",
        )

    # Create booking record
    booking = Booking(
        lead_id=lead.id,
        name=data.name,
        email=data.email,
        phone=data.phone,
        meeting_type=data.meeting_type,
        context=data.context,
        location=data.location or "",
        scheduled_at=slot_start,
        google_event_id=google_event_id,
        notes=data.notes or "",
    )
    db.add(booking)
    try:
        await db.flush()
    except Exception:
        try:
            await delete_event(google_event_id)
        except CalendarIntegrationError:
            logger.exception(
                "Booking database save failed and cleanup of calendar event %s also failed",
                google_event_id,
            )
        raise
    await db.refresh(booking)

    logger.info(
        "Booking created: %s with %s on %s (calendar: %s)",
        data.meeting_type, data.name, slot_start, google_event_id,
    )
    await enqueue_notification(
        db,
        event_type="booking_confirmed",
        payload={
            "booking_id": booking.id,
            "name": data.name,
            "email": data.email,
            "phone": data.phone,
            "meeting_type": data.meeting_type,
            "context": data.context,
            "scheduled_at": slot_start.isoformat(),
            "location": data.location or "",
            "google_event_id": google_event_id,
        },
    )
    await db.commit()
    asyncio.create_task(run_notification_retry_pass(limit=5))

    return booking
