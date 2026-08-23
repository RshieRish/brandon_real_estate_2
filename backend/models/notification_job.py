import json
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, and_, column, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class NotificationJob(Base):
    __tablename__ = "notification_jobs"
    __table_args__ = (
        Index(
            "uq_notification_jobs_provider_dedupe",
            "provider_key",
            "dedupe_key",
            unique=True,
            postgresql_where=and_(
                column("provider_key").is_not(None),
                column("dedupe_key").is_not(None),
            ),
        ),
        Index(
            "ix_notification_jobs_claimable",
            "status",
            "next_attempt_at",
            "lease_expires_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    recipient: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    payload_json: Mapped[str] = mapped_column("payload", Text, default="{}")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def payload_dict(self) -> dict:
        return json.loads(self.payload_json or "{}")
