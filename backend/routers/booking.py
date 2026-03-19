from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from database import get_db
from models.booking import Booking
from models.lead import Lead
from schemas.booking import BookingCreate, BookingOut

router = APIRouter()

@router.post("/", response_model=BookingOut)
async def create_booking(data: BookingCreate, db: AsyncSession = Depends(get_db)):
    # Upsert lead
    result = await db.execute(select(Lead).where(Lead.email == data.email))
    lead = result.scalar_one_or_none()
    if not lead:
        lead = Lead(name=data.name, email=data.email, phone=data.phone, source="booking", lead_type=data.context, metadata_json="{}")
        db.add(lead)
        await db.flush()
    else:
        lead.routing_status = "booked"

    booking = Booking(
        lead_id=lead.id,
        name=data.name, email=data.email, phone=data.phone,
        meeting_type=data.meeting_type, context=data.context,
        scheduled_at=data.scheduled_at, notes=data.notes or "",
    )
    db.add(booking)
    await db.flush()
    await db.refresh(booking)
    return booking

@router.get("/available-slots")
async def available_slots():
    """Placeholder — integrate with Google Calendar in a later phase."""
    from datetime import timedelta
    slots = []
    base = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    for i in range(14):
        day = base + timedelta(days=i + 1)
        if day.weekday() < 5:  # Mon-Fri
            for h in [9, 10, 11, 14, 15, 16]:
                slots.append((day.replace(hour=h)).isoformat())
    return {"slots": slots[:20]}
