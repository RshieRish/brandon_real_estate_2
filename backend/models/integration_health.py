"""Shared operational health state for dedicated integration workers."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class IntegrationHealthState(Base):
    __tablename__ = "integration_health_states"
    __table_args__ = (
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_integration_health_consecutive_failures_nonnegative",
        ),
        CheckConstraint(
            "transition_epoch > 0",
            name="ck_integration_health_transition_epoch_positive",
        ),
    )

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    last_error_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    transition_epoch: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    last_alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IntegrationWorkerHeartbeat(Base):
    __tablename__ = "integration_worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    booted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    current_job: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    last_completed_job: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )


__all__ = ["IntegrationHealthState", "IntegrationWorkerHeartbeat"]
