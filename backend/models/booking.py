from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, event, func
from sqlalchemy.orm import Mapped, mapped_column, validates

from database import Base
from models._utc import normalize_database_datetime
from services.command_contact_identity import canonical_email


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index(
            "ix_bookings_timeline_lead_order",
            "lead_id",
            "scheduled_at",
            "id",
        ),
        Index(
            "ix_bookings_timeline_email_order",
            "normalized_email",
            "lead_id",
            "scheduled_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    normalized_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(String(50))
    meeting_type: Mapped[str] = mapped_column(String(50), default="phone")
    context: Mapped[str] = mapped_column(String(50), default="general")
    location: Mapped[str | None] = mapped_column(String(500), default="")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    google_event_id: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @validates("email")
    def _sync_normalized_email(self, _key: str, value: str) -> str:
        self.normalized_email = canonical_email(value)
        return value

    @validates("scheduled_at")
    def _normalize_scheduled_at(self, _key: str, value: datetime) -> datetime:
        normalized = normalize_database_datetime(value)
        assert normalized is not None
        return normalized


@event.listens_for(Booking, "before_insert")
@event.listens_for(Booking, "before_update")
def _recompute_booking_normalized_email(
    _mapper, _connection, target: Booking
) -> None:
    target.normalized_email = canonical_email(target.email)
