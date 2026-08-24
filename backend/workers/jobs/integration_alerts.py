"""Durable integration health alert enqueue job."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa

from models.integration_health import IntegrationHealthState
from services.integration_health_service import integration_alert_dedupe_key
from services.notification_service import enqueue_notification


_REMINDER_INTERVAL = timedelta(hours=24)


class IntegrationAlertsJob:
    """Translate bounded health transitions into deduplicated notifications."""

    def __init__(
        self,
        *,
        sessionmaker,
        batch_size: int = 20,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
            raise ValueError("integration_alert_batch_size_invalid")
        self._sessionmaker = sessionmaker
        self._batch_size = batch_size
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _payload(row: IntegrationHealthState, *, event: str) -> dict[str, object]:
        return {
            "provider": row.provider,
            "event": event,
            "state": row.state,
            "transition_epoch": row.transition_epoch,
        }

    async def run(self) -> None:
        now = self._clock().astimezone(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                rows = list(
                    (
                        await session.scalars(
                            sa.select(IntegrationHealthState)
                            .order_by(IntegrationHealthState.provider)
                            .limit(self._batch_size)
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                for row in rows:
                    if row.state == "healthy":
                        if row.recovered_at is None or (
                            row.last_alerted_at is not None
                            and row.last_alerted_at >= row.recovered_at
                        ):
                            continue
                        event = "recovered"
                        row.next_reminder_at = None
                    elif row.last_alerted_at is None or row.next_reminder_at is None:
                        event = "opened"
                        row.next_reminder_at = now + _REMINDER_INTERVAL
                    elif (
                        row.next_reminder_at is not None and row.next_reminder_at <= now
                    ):
                        event = "reminder"
                        row.next_reminder_at = now + _REMINDER_INTERVAL
                    else:
                        continue
                    await enqueue_notification(
                        session,
                        event_type="integration_alert",
                        payload=self._payload(row, event=event),
                        provider_key=row.provider,
                        dedupe_key=integration_alert_dedupe_key(
                            provider=row.provider,
                            transition_epoch=row.transition_epoch,
                            event=event,
                        ),
                    )
                    row.last_alerted_at = now


def run_integration_alerts_job(**kwargs: Any) -> Callable[[], Awaitable[None]]:
    return IntegrationAlertsJob(**kwargs).run


__all__ = ["IntegrationAlertsJob", "run_integration_alerts_job"]
