"""Leased Gmail receipt extraction and suggestion reconciliation job."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

from models.gmail_task_intake import GmailMessageReceipt
from services.gmail_obligation_reconciliation import (
    GmailExtractionAttemptLimitReached,
    GmailObligationReconciliationService,
    GmailReconciliationCandidateLimitReached,
)
from services.gmail_task_extractor import (
    GMAIL_TASK_SCHEMA_VERSION,
    GmailTaskExtractionError,
    GmailTaskExtractor,
)


_FAILURE_CATEGORY_BY_EXTRACTOR_ERROR = {
    "gmail_extraction_invalid_output": "invalid_model_output",
    "gmail_extraction_body_truncated": "body_truncated",
    "gmail_extraction_timeout": "provider_timeout",
    "gmail_extraction_already_running": "provider_timeout",
    "gmail_extraction_provider_saturated": "provider_timeout",
    "gmail_extraction_provider_failed": "provider_failed",
    "gmail_extraction_invalid_source": "provider_failed",
}


def build_gmail_model_call(
    *,
    api_key: str,
    socket_timeout_seconds: float,
) -> Callable[[Any], object]:
    """Build one synchronous structured-output Gemini boundary."""

    if (
        isinstance(socket_timeout_seconds, bool)
        or not isinstance(socket_timeout_seconds, (int, float))
        or not math.isfinite(float(socket_timeout_seconds))
        or socket_timeout_seconds <= 0
    ):
        raise ValueError("gmail_model_socket_timeout_invalid")
    # google-genai HttpOptions.timeout is an integer number of milliseconds.
    # Floor to the provider's supported precision so this inner timeout never
    # exceeds the already-validated outer worker deadline.
    socket_timeout_milliseconds = int(float(socket_timeout_seconds) * 1000)
    if socket_timeout_milliseconds < 1:
        raise ValueError("gmail_model_socket_timeout_invalid")

    def call(request: Any) -> object:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=socket_timeout_milliseconds),
        )
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=request.prompt,
            config=types.GenerateContentConfig(
                system_instruction=request.system_instruction,
                response_mime_type="application/json",
                response_schema=request.response_model,
                temperature=0,
            ),
        )
        # GmailTaskExtractor owns the bounded, strict parse and releases this
        # transient provider value before any durable reconciliation write.
        return response.text

    return call


class GmailReceiptJob:
    """Process a bounded receipt batch through the canonical services."""

    def __init__(
        self,
        *,
        enabled: bool,
        sessionmaker,
        history_service=None,
        history_service_provider: Callable[[], Awaitable[Any]] | None = None,
        extractor: GmailTaskExtractor,
        reconciliation_service: GmailObligationReconciliationService,
        batch_size: int = 20,
        stale_after_seconds: float = 120.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
            raise ValueError("gmail_receipt_batch_size_invalid")
        if stale_after_seconds <= 0:
            raise ValueError("gmail_receipt_stale_threshold_invalid")
        if (history_service is None) == (history_service_provider is None):
            raise ValueError("gmail_receipt_history_service_invalid")
        self._enabled = enabled
        self._sessionmaker = sessionmaker
        self._history_service = history_service
        self._history_service_provider = history_service_provider
        self._extractor = extractor
        self._reconciliation = reconciliation_service
        self._batch_size = batch_size
        self._stale_after_seconds = stale_after_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def _due_receipt_ids(
        self,
        *,
        account_id: UUID | None = None,
    ) -> tuple[UUID, ...]:
        stale_before = self._clock().astimezone(timezone.utc) - timedelta(
            seconds=self._stale_after_seconds
        )
        statement = (
            select(GmailMessageReceipt.id)
            .where(
                or_(
                    GmailMessageReceipt.processing_state.in_(("pending", "failed")),
                    (
                        (GmailMessageReceipt.processing_state == "processing")
                        & GmailMessageReceipt.processing_started_at.is_not(None)
                        & (GmailMessageReceipt.processing_started_at <= stale_before)
                    ),
                )
            )
            .order_by(GmailMessageReceipt.created_at, GmailMessageReceipt.id)
            .limit(self._batch_size)
        )
        if account_id is not None:
            statement = statement.where(GmailMessageReceipt.account_id == account_id)
        async with self._sessionmaker() as session:
            rows = await session.scalars(statement)
            return tuple(rows.all())

    async def _consume(self, receipt_id: UUID, account_id: UUID, message) -> None:
        try:
            claim = await self._reconciliation.claim_attempt(
                receipt_id=receipt_id,
                schema_version=GMAIL_TASK_SCHEMA_VERSION,
            )
        except (
            GmailExtractionAttemptLimitReached,
            GmailReconciliationCandidateLimitReached,
        ):
            # The durable attempt ledger is terminal. Returning lets the
            # receipt lease close without an N+1 provider call.
            return
        if claim.replayed and claim.state == "succeeded":
            return
        try:
            extraction = await self._extractor.extract(
                account_id=account_id,
                message=message,
            )
        except GmailTaskExtractionError as error:
            category = _FAILURE_CATEGORY_BY_EXTRACTOR_ERROR.get(str(error))
            if category is None:
                category = "provider_failed"
            await self._reconciliation.fail_attempt(
                claim=claim,
                category=category,
            )
            raise
        await self._reconciliation.reconcile_attempt(
            claim=claim,
            extraction=extraction,
        )

    async def _account_id(self, receipt_id: UUID) -> UUID:
        async with self._sessionmaker() as session:
            account_id = await session.scalar(
                select(GmailMessageReceipt.account_id).where(
                    GmailMessageReceipt.id == receipt_id
                )
            )
        if not isinstance(account_id, UUID):
            raise RuntimeError("gmail_receipt_not_found")
        return account_id

    async def run(self) -> None:
        if not self._enabled:
            return
        from services.gmail_history_service import GmailReceiptProcessingError

        history_service = self._history_service
        bound_account_id = None
        if history_service is None:
            provided = await self._history_service_provider()
            if isinstance(provided, tuple):
                bound_account_id, history_service = provided
                if not isinstance(bound_account_id, UUID):
                    raise RuntimeError("gmail_receipt_account_binding_invalid")
            else:
                history_service = provided
        for receipt_id in await self._due_receipt_ids(account_id=bound_account_id):
            account_id = await self._account_id(receipt_id)

            async def consumer(message, *, selected_account_id=account_id) -> None:
                await self._consume(receipt_id, selected_account_id, message)

            try:
                await history_service.process_receipt(
                    receipt_id,
                    consumer=consumer,
                )
            except GmailReceiptProcessingError:
                continue


def run_gmail_receipts_job(**kwargs: Any) -> Callable[[], Awaitable[None]]:
    return GmailReceiptJob(**kwargs).run


__all__ = [
    "GmailReceiptJob",
    "build_gmail_model_call",
    "run_gmail_receipts_job",
]
