"""Leased Sydney clarification enqueue, dispatch, reminder, and release job."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from models.gmail_task_intake import CRMTaskSuggestion
from models.sydney_tasks import CRMTaskClarification, SydneyQuestionOutbox
from services.sydney_clarification_service import (
    SydneyClarificationError,
    SydneyClarificationService,
)
from services.sydney_telegram_dispatcher import (
    SydneyTelegramDispatcher,
    TelegramDispatchError,
)


class SydneyQuestionsJob:
    """Advance a bounded clarification batch through durable row claims."""

    def __init__(
        self,
        *,
        enabled: bool,
        sessionmaker,
        clarification_service: SydneyClarificationService,
        dispatcher: SydneyTelegramDispatcher,
        batch_size: int = 20,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
            raise ValueError("sydney_question_batch_size_invalid")
        self._enabled = enabled
        self._sessionmaker = sessionmaker
        self._clarifications = clarification_service
        self._dispatcher = dispatcher
        self._batch_size = batch_size
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def _suggestions_without_question(self) -> tuple[tuple[UUID, str], ...]:
        active_question = sa.exists(
            sa.select(CRMTaskClarification.id).where(
                CRMTaskClarification.suggestion_id == CRMTaskSuggestion.id,
                CRMTaskClarification.state == "pending",
            )
        )
        async with self._sessionmaker() as session:
            rows = await session.execute(
                sa.select(CRMTaskSuggestion.id, CRMTaskSuggestion.title)
                .where(
                    CRMTaskSuggestion.state.in_(
                        ("needs_clarification", "possible_duplicate")
                    ),
                    ~active_question,
                )
                .order_by(CRMTaskSuggestion.created_at, CRMTaskSuggestion.id)
                .limit(self._batch_size)
            )
            return tuple((row.id, row.title) for row in rows)

    async def _pending_clarification_ids(self) -> tuple[UUID, ...]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                sa.select(CRMTaskClarification.id)
                .where(CRMTaskClarification.state == "pending")
                .order_by(
                    CRMTaskClarification.created_at,
                    CRMTaskClarification.id,
                )
                .limit(self._batch_size)
            )
            return tuple(rows.all())

    async def _pending_attempt_ids(self) -> tuple[UUID, ...]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                sa.select(SydneyQuestionOutbox.id)
                .where(SydneyQuestionOutbox.state == "pending")
                .order_by(
                    SydneyQuestionOutbox.created_at,
                    SydneyQuestionOutbox.id,
                )
                .limit(self._batch_size)
            )
            return tuple(rows.all())

    async def run(self) -> None:
        if not self._enabled:
            return
        now = self._clock().astimezone(timezone.utc)
        clarification_ids = await self._pending_clarification_ids()
        for clarification_id in clarification_ids:
            await self._dispatcher.release_expired_clarification(clarification_id)

        for suggestion_id, title in await self._suggestions_without_question():
            try:
                await self._clarifications.enqueue_next(
                    suggestion_id=suggestion_id,
                    party_label="Client",
                    subject_preview=title[:255],
                    now=now,
                )
            except SydneyClarificationError:
                continue

        for clarification_id in await self._pending_clarification_ids():
            try:
                await self._dispatcher.enqueue_due_reminder(clarification_id)
            except TelegramDispatchError:
                continue

        for attempt_id in await self._pending_attempt_ids():
            try:
                await self._dispatcher.dispatch_attempt(attempt_id)
            except TelegramDispatchError:
                continue


def run_sydney_questions_job(**kwargs: Any) -> Callable[[], Awaitable[None]]:
    return SydneyQuestionsJob(**kwargs).run


__all__ = ["SydneyQuestionsJob", "run_sydney_questions_job"]
