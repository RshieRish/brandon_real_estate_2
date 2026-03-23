"""Booking router — travel-time-aware scheduling via Google Calendar + Maps."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.booking import Booking
from models.lead import Lead
from schemas.booking import BookingCreate, BookingOut
from services.calendar_service import get_available_slots, create_event
from services.email_service import notify_new_booking

logger = logging.getLogger(__name__)
router = APIRouter()


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
):
    """Return available booking slots for a specific date.

    For in-person meetings with a location, slots are filtered by
    travel time between Brandon's existing calendar events and the
    requested meeting location using the Google Maps Distance Matrix API.

    Phone and video meetings skip travel-time checks.
    """
    try:
        target_date = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    except ValueError:
        return {"error": "Invalid date format. Use ISO format, e.g. 2026-03-25"}

    slots = await get_available_slots(
        target_date=target_date,
        meeting_type=meeting_type,
        client_location=location,
    )

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
    meeting_end = data.scheduled_at + timedelta(hours=1)
    summary = f"Meeting with {data.name} — {data.context.title()}"
    description = (
        f"Meeting type: {data.meeting_type}\n"
        f"Context: {data.context}\n"
        f"Phone: {data.phone or 'N/A'}\n"
        f"Email: {data.email}\n"
    )
    if data.notes:
        description += f"Notes: {data.notes}\n"

    google_event_id = await create_event(
        summary=summary,
        start=data.scheduled_at,
        end=meeting_end,
        attendee_email=data.email,
        location=data.location or "",
        description=description,
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
        scheduled_at=data.scheduled_at,
        google_event_id=google_event_id,
        notes=data.notes or "",
    )
    db.add(booking)
    await db.flush()
    await db.refresh(booking)

    logger.info(
        "Booking created: %s with %s on %s (calendar: %s)",
        data.meeting_type, data.name, data.scheduled_at, google_event_id,
    )

    # Send email notification to Brandon (fire-and-forget)
    try:
        await notify_new_booking(
            name=data.name,
            email=data.email,
            phone=data.phone or "",
            meeting_type=data.meeting_type,
            scheduled_at=str(data.scheduled_at),
            location=data.location or "",
            context=data.context,
        )
    except Exception:
        logger.exception("Failed to send booking notification email")

    return booking
