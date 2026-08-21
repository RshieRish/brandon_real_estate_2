"""Durable, cursor-safe Gmail History intake and receipt processing."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from models.gmail_task_intake import (
    GmailBackfillRequest,
    GmailMessageOrigin,
    GmailMessageReceipt,
    GmailMissingMessageIncident,
    GmailSyncAccount,
    GmailSyncPageCheckpoint,
    GmailSyncRun,
)
from models.admin_user import AdminUser
from models.agent_action_audit import AgentActionAudit
from services.gmail_history_adapter import (
    GmailProviderFailure,
    parse_gmail_history_id,
    parse_gmail_page_token,
    parse_gmail_provider_id,
)
from services.gmail_history_database import _read_backend_pid
from services.gmail_message_sanitizer import (
    SanitizedGmailMessage,
    sanitize_gmail_message,
)
from services.gmail_origin_service import GmailSendConflict
from services.integration_advisory_locks import (
    account_advisory_key,
    release_session_advisory_lock,
    try_session_advisory_lock,
)


logger = logging.getLogger(__name__)
UTC = timezone.utc

_SAFE_PROVIDER_MESSAGES = {
    "oauth_revoked": "Google Workspace authorization must be reconnected.",
    "rate_limited": "Gmail provider rate limit reached.",
    "provider_timeout": "Gmail provider request timed out.",
    "transient_provider": "Provider request failed temporarily.",
    "malformed_provider": "Gmail provider returned an invalid response.",
    "history_cursor_expired": "Gmail History cursor expired.",
    "message_not_found": "Gmail message requires manual recovery.",
    "session_affinity_lost": "Gmail History session affinity was lost.",
    "max_pages": "Gmail History pagination requires manual recovery.",
    "repeated_token": "Gmail History pagination requires manual recovery.",
    "gmail_account_identity_mismatch": "Gmail account identity does not match.",
    "cursor_conflict": "Gmail History cursor requires manual recovery.",
    "receipt_content_mismatch": "Gmail receipt content identity did not match.",
    "receipt_content_invalid": "Gmail receipt content was invalid.",
    "stale_credential_result": "Gmail credential changed; retry is required.",
}
_TERMINAL_BACKFILL_PROVIDER_CATEGORIES = frozenset(
    {"message_not_found", "malformed_provider", "oauth_revoked"}
)
_RETRYABLE_POLL_PROVIDER_CATEGORIES = frozenset(
    {"rate_limited", "transient_provider", "provider_timeout"}
)
_ALERTABLE_ACCOUNT_BLOCK_CATEGORIES = frozenset(
    {
        "gmail_account_identity_mismatch",
        "cursor_conflict",
        "malformed_provider",
        "max_pages",
        "message_not_found",
        "repeated_token",
        "receipt_content_invalid",
        "receipt_content_mismatch",
    }
)
_WORKSPACE_GMAIL_BINDING_LOCK_KEY = 5_921_914_720_764_681_105


class GmailAccountBlocked(RuntimeError):
    pass


class GmailCursorConflict(RuntimeError):
    pass


class GmailPagePersistenceError(RuntimeError):
    pass


class GmailSessionAffinityLost(RuntimeError):
    pass


class GmailPaginationGuard(RuntimeError):
    pass


class GmailBackfillValidationError(RuntimeError):
    pass


class GmailBackfillExecutionBusy(RuntimeError):
    pass


class GmailBackfillNotComplete(RuntimeError):
    pass


class GmailReceiptProcessingError(RuntimeError):
    pass


class GmailMissingMessageDetected(GmailProviderFailure):
    """Body-free identity for a list/get deletion race."""

    def __init__(self, *, message_id: str, thread_id: str) -> None:
        super().__init__("message_not_found")
        self.message_id = message_id
        self.thread_id = thread_id


class GmailMissingMessageAcknowledgementError(RuntimeError):
    def __init__(self, category: str, *, status_code: int = 409) -> None:
        self.category = category
        self.status_code = status_code
        super().__init__(category)


class _DeterministicReceiptFailure(RuntimeError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class _TransientReceiptConsumerFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class GmailHistorySyncResult:
    lock_acquired: bool
    start_history_id: str | None
    committed_history_id: str | None
    pages_committed: int = 0
    page_backend_pids: tuple[int, ...] = ()
    seeded: bool = False


@dataclass(frozen=True)
class GmailReceiptProcessingResult:
    receipt_id: UUID
    processing_state: str
    classification: str | None
    claimed: bool


@dataclass(frozen=True)
class _PreparedMessage:
    """Page-buffered durable evidence with no raw or sanitized body text."""

    receipt: GmailMessageReceipt
    sent_observation: Any | None = None


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _safe_message(category: str) -> str:
    return _SAFE_PROVIDER_MESSAGES.get(category, "Gmail provider request failed.")


def _alert_pending_category(event: str) -> str:
    return f"{event}_alert_pending"


def _validated_history_id(value: object) -> str:
    """Validate provider and persisted cursors without retaining raw values."""

    try:
        return parse_gmail_history_id(value)
    except (TypeError, ValueError):
        raise GmailProviderFailure("malformed_provider") from None


def _validated_poll_page(
    page: Any,
    *,
    start_history_id: str,
) -> tuple[str, str | None, str | None]:
    """Validate the page cursor envelope before fetching any message metadata."""

    start = _validated_history_id(start_history_id)
    terminal = _validated_history_id(getattr(page, "history_id", None))
    if int(terminal) < int(start):
        raise GmailProviderFailure("malformed_provider") from None

    discovered_min_raw = getattr(page, "discovered_history_id_min", None)
    discovered_max_raw = getattr(page, "discovered_history_id_max", None)
    if (discovered_min_raw is None) != (discovered_max_raw is None):
        raise GmailProviderFailure("malformed_provider") from None
    if discovered_min_raw is None:
        return terminal, None, None

    discovered_min = _validated_history_id(discovered_min_raw)
    discovered_max = _validated_history_id(discovered_max_raw)
    start_int = int(start)
    terminal_int = int(terminal)
    min_int = int(discovered_min)
    max_int = int(discovered_max)
    if not (start_int < min_int <= max_int <= terminal_int):
        raise GmailProviderFailure("malformed_provider") from None
    return terminal, discovered_min, discovered_max


async def _invoke(callback: Callable[..., Any] | None, *args: Any) -> None:
    if callback is None:
        return
    value = callback(*args)
    if inspect.isawaitable(value):
        await value


async def _post_lock_affinity_probe(
    connection: AsyncConnection,
    account_id: UUID,
) -> tuple[int, bool]:
    """Atomically identify the backend and retain xact serialization if needed."""

    row = (
        await connection.execute(
            text(
                "SELECT pg_backend_pid(), "
                "pg_try_advisory_xact_lock(:account_key)"
            ),
            {"account_key": account_advisory_key(account_id)},
        )
    ).one()
    return int(row[0]), bool(row[1])


class GmailHistoryService:
    def __init__(
        self,
        *,
        engine: AsyncEngine,
        adapter: Any,
        participant_hash_key: bytes | str,
        alert_sink: Callable[..., Awaitable[None]] | None = None,
        max_pages_per_run: int = 100,
        backend_pid_reader: Callable[[AsyncConnection], Awaitable[int]] = _read_backend_pid,
        post_lock_probe: (
            Callable[[AsyncConnection, UUID], Awaitable[tuple[int, bool]]] | None
        ) = None,
        after_terminal_page_commit: Callable[..., Any] | None = None,
        before_backfill_admission: Callable[..., Any] | None = None,
        before_receipt_claim_flush: Callable[..., Any] | None = None,
        before_receipt_finalize: Callable[..., Any] | None = None,
        after_receipt_lookup: Callable[..., Any] | None = None,
        after_receipt_lock: Callable[..., Any] | None = None,
        before_release_affinity_persist: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] = _now,
        receipt_processing_deadline_seconds: float = 30.0,
        receipt_processing_stale_after_seconds: float = 120.0,
        origin_observer: Any | None = None,
        credential_is_current: (
            Callable[[AsyncSession], Awaitable[bool]] | None
        ) = None,
    ) -> None:
        if not isinstance(max_pages_per_run, int) or max_pages_per_run < 1:
            raise ValueError("gmail_history_max_pages_invalid")
        if (
            receipt_processing_deadline_seconds <= 0
            or receipt_processing_stale_after_seconds
            <= receipt_processing_deadline_seconds
        ):
            raise ValueError("gmail_receipt_stale_threshold_invalid")
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._adapter = adapter
        self._participant_hash_key = participant_hash_key
        self._alert_sink = alert_sink
        self._max_pages = max_pages_per_run
        self._backend_pid_reader = backend_pid_reader
        if post_lock_probe is not None:
            self._post_lock_probe = post_lock_probe
        elif backend_pid_reader is _read_backend_pid:
            self._post_lock_probe = _post_lock_affinity_probe
        else:

            async def compatibility_probe(
                connection: AsyncConnection,
                probe_account_id: UUID,
            ) -> tuple[int, bool]:
                pid = await backend_pid_reader(connection)
                owns_serialization = bool(
                    await connection.scalar(
                        text("SELECT pg_try_advisory_xact_lock(:account_key)"),
                        {
                            "account_key": account_advisory_key(
                                probe_account_id
                            )
                        },
                    )
                )
                return pid, owns_serialization

            self._post_lock_probe = compatibility_probe
        self._after_terminal_page_commit = after_terminal_page_commit
        self._before_backfill_admission = before_backfill_admission
        self._before_receipt_claim_flush = before_receipt_claim_flush
        self._before_receipt_finalize = before_receipt_finalize
        self._after_receipt_lookup = after_receipt_lookup
        self._after_receipt_lock = after_receipt_lock
        self._before_release_affinity_persist = before_release_affinity_persist
        self._clock = clock
        self._receipt_deadline = receipt_processing_deadline_seconds
        self._receipt_stale_after = receipt_processing_stale_after_seconds
        self._origin_observer = origin_observer
        self._credential_is_current = credential_is_current

    @staticmethod
    def _bound_session(connection: AsyncConnection) -> AsyncSession:
        # The retained AsyncConnection owns the physical session advisory lock.
        # `control_fully` makes each ORM commit/rollback operate on that outer
        # connection transaction instead of merely flushing into it.
        return AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="control_fully",
        )

    async def _account(self, session: AsyncSession, account_id: UUID) -> GmailSyncAccount:
        account = await session.get(GmailSyncAccount, account_id)
        if account is None:
            raise GmailAccountBlocked("gmail_account_not_found")
        return account

    async def _origin_kind(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        message_id: str,
    ) -> str | None:
        return await session.scalar(
            select(GmailMessageOrigin.origin_kind).where(
                GmailMessageOrigin.account_id == account_id,
                GmailMessageOrigin.gmail_message_id == message_id,
            )
        )

    def _sanitize_metadata(
        self,
        metadata: Any,
        *,
        mailbox_email: str,
        origin_kind: str | None,
    ) -> SanitizedGmailMessage:
        content = SimpleNamespace(
            message_id=metadata.message_id,
            thread_id=metadata.thread_id,
            label_ids=metadata.label_ids,
            message_at=metadata.message_at,
            headers=metadata.headers,
            body_text="",
            body_truncated=False,
            body_media_type="text/plain",
        )
        return sanitize_gmail_message(
            content,
            mailbox_email=mailbox_email,
            participant_hash_key=self._participant_hash_key,
            origin_kind=origin_kind,
        )

    @staticmethod
    def _receipt(account_id: UUID, message: SanitizedGmailMessage) -> GmailMessageReceipt:
        return GmailMessageReceipt(
            account_id=account_id,
            gmail_message_id=message.message_id,
            gmail_thread_id=message.thread_id,
            direction=message.direction,
            message_at=message.message_at,
            sender_hmac=message.sender_hmac,
            recipient_hmacs_json=json.dumps(list(message.recipient_hmacs)),
            subject_preview=message.subject_preview,
            body_hash=message.body_hash,
            labels_json=json.dumps(list(message.labels)),
            processing_state=message.processing_state,
            classification=message.classification,
        )

    async def _prepare_metadata(
        self,
        *,
        account_id: UUID,
        refs: tuple[Any, ...],
        run_id: UUID | None = None,
        start_history_id: str | None = None,
        page_number: int | None = None,
        request_page_token: str | None = None,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> list[_PreparedMessage]:
        ids: set[str] = set()
        prepared: list[_PreparedMessage] = []
        ref_ids = [ref.message_id for ref in refs]
        async with self._sessions() as session:
            account = await self._account(session, account_id)
            existing_rows = list(
                (
                    await session.scalars(
                        select(GmailMessageReceipt).where(
                            GmailMessageReceipt.account_id == account_id,
                            GmailMessageReceipt.gmail_message_id.in_(
                                ref_ids
                            ),
                        )
                    )
                ).all()
            ) if refs else []
            origin_rows = list(
                (
                    await session.scalars(
                        select(GmailMessageOrigin).where(
                            GmailMessageOrigin.account_id == account_id,
                            GmailMessageOrigin.gmail_message_id.in_(ref_ids),
                        )
                    )
                ).all()
            ) if refs else []
            acknowledged_incidents = list(
                (
                    await session.scalars(
                        select(GmailMissingMessageIncident).where(
                            GmailMissingMessageIncident.account_id == account_id,
                            GmailMissingMessageIncident.run_id == run_id,
                            GmailMissingMessageIncident.state == "acknowledged",
                            GmailMissingMessageIncident.start_history_id
                            == start_history_id,
                            GmailMissingMessageIncident.page_number == page_number,
                            GmailMissingMessageIncident.request_page_token
                            .is_not_distinct_from(request_page_token),
                        )
                    )
                ).all()
            ) if run_id is not None else []
        existing = {row.gmail_message_id: row for row in existing_rows}
        origins = {
            row.gmail_message_id: row
            for row in origin_rows
            if row.gmail_message_id is not None
        }
        origin_kinds = {
            row.gmail_message_id: row.origin_kind
            for row in origin_rows
            if row.gmail_message_id is not None
        }
        for ref in refs:
            prior_receipt = existing.get(ref.message_id)
            prior_origin = origins.get(ref.message_id)
            if (
                prior_receipt is not None
                and prior_receipt.gmail_thread_id != ref.thread_id
            ) or (
                prior_origin is not None
                and prior_origin.gmail_thread_id != ref.thread_id
            ):
                raise GmailProviderFailure("malformed_provider") from None
        acknowledged_refs = {
            (row.gmail_message_id, row.gmail_thread_id)
            for row in acknowledged_incidents
        }
        for ref in refs:
            if (ref.message_id, ref.thread_id) in acknowledged_refs:
                continue
            prior_receipt = existing.get(ref.message_id)
            needs_receipt_enrichment = (
                prior_receipt is not None
                and (
                    ref.message_id in origin_kinds
                    or prior_receipt.processing_state in {"pending", "failed"}
                )
                and prior_receipt.sender_hmac is None
                and prior_receipt.recipient_hmacs_json.strip() == "[]"
            )
            if (
                ref.message_id in ids
                or (prior_receipt is not None and not needs_receipt_enrichment)
            ):
                continue
            ids.add(ref.message_id)
            try:
                metadata = await self._adapter.get_message_metadata(
                    account_key=str(account_id),
                    message_id=ref.message_id,
                )
            except GmailProviderFailure as error:
                if error.category == "message_not_found" and run_id is not None:
                    raise GmailMissingMessageDetected(
                        message_id=ref.message_id,
                        thread_id=ref.thread_id,
                    ) from None
                raise GmailProviderFailure(error.category) from None
            if (
                metadata.message_id != ref.message_id
                or metadata.thread_id != ref.thread_id
            ):
                raise GmailProviderFailure("malformed_provider") from None
            if window_start is not None and window_end is not None and not (
                window_start <= metadata.message_at < window_end
            ):
                continue
            origin_kind = origin_kinds.get(metadata.message_id)
            sanitized = self._sanitize_metadata(
                metadata,
                mailbox_email=account.workspace_email,
                origin_kind=origin_kind,
            )
            sent_eligible = (
                self._origin_observer is not None
                and sanitized.classification == "eligible"
                and sanitized.direction in {"sent", "self_copy"}
                and "SENT" in {label.upper() for label in metadata.label_ids}
            )
            if sent_eligible:
                try:
                    content = await self._adapter.get_message_content(
                        account_key=str(account_id),
                        message_id=ref.message_id,
                    )
                except GmailProviderFailure as error:
                    if error.category == "message_not_found" and run_id is not None:
                        raise GmailMissingMessageDetected(
                            message_id=ref.message_id,
                            thread_id=ref.thread_id,
                        ) from None
                    raise GmailProviderFailure(error.category) from None
                if (
                    content.message_id != ref.message_id
                    or content.thread_id != ref.thread_id
                ):
                    del content
                    raise GmailProviderFailure("malformed_provider") from None
                sanitized_content = None
                observation = None
                receipt = None
                preparation_failed = False
                try:
                    sanitized_content = sanitize_gmail_message(
                        content,
                        mailbox_email=account.workspace_email,
                        participant_hash_key=self._participant_hash_key,
                        origin_kind=origin_kind,
                    )
                    if (
                        sanitized_content.classification == "eligible"
                        and sanitized_content.direction in {"sent", "self_copy"}
                    ):
                        observation = (
                            self._origin_observer.prepare_history_sent_observation(
                                account_email=account.workspace_email,
                                message=content,
                            )
                        )
                    receipt = self._receipt(account_id, sanitized_content)
                except BaseException:
                    preparation_failed = True
                if preparation_failed:
                    del content
                    if sanitized_content is not None:
                        del sanitized_content
                    raise GmailProviderFailure("malformed_provider") from None
                # Neither the raw provider body nor the sanitized transient text
                # may survive into the page buffer or the next provider fetch.
                del content
                assert receipt is not None
                assert sanitized_content is not None
                del sanitized_content
                prepared.append(
                    _PreparedMessage(
                        receipt=receipt,
                        sent_observation=observation,
                    )
                )
                del sanitized
                continue
            prepared.append(
                _PreparedMessage(receipt=self._receipt(account_id, sanitized))
            )
            del sanitized
        return prepared

    @staticmethod
    def _merge_receipt_evidence(
        stored: GmailMessageReceipt,
        evidence: GmailMessageReceipt,
    ) -> None:
        if (
            stored.gmail_message_id != evidence.gmail_message_id
            or stored.gmail_thread_id != evidence.gmail_thread_id
        ):
            raise GmailProviderFailure("malformed_provider") from None
        stored.direction = evidence.direction
        stored.message_at = evidence.message_at
        stored.sender_hmac = evidence.sender_hmac
        stored.recipient_hmacs_json = evidence.recipient_hmacs_json
        stored.subject_preview = evidence.subject_preview
        stored.body_hash = evidence.body_hash
        stored.labels_json = evidence.labels_json
        if (
            evidence.processing_state == "ignored"
            and stored.processing_state in {"pending", "failed"}
        ):
            stored.processing_state = "ignored"
            stored.classification = evidence.classification
            stored.processing_started_at = None
            stored.failure_category = None
            stored.failure_message = None
        elif stored.processing_state == "pending":
            stored.processing_state = evidence.processing_state
            stored.classification = evidence.classification
            stored.failure_category = None
            stored.failure_message = None

    async def _persist_page(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        run_id: UUID,
        page_number: int,
        request_page_token: str | None,
        next_page_token: str | None,
        terminal_history_id: str | None,
        discovered_history_id_min: str | None,
        discovered_history_id_max: str | None,
        metadata_rows: list[_PreparedMessage],
        terminal_run_state: str = "discovered",
    ) -> None:
        session = self._bound_session(connection)
        try:
            await self._account(session, account_id)
            run = await session.get(GmailSyncRun, run_id)
            if run is None:
                raise GmailPagePersistenceError(
                    "gmail_history_page_persistence_failed"
                )
            existing = list(
                (
                    await session.scalars(
                        select(GmailMessageReceipt).where(
                            GmailMessageReceipt.account_id == account_id,
                            GmailMessageReceipt.gmail_message_id.in_(
                                [item.receipt.gmail_message_id for item in metadata_rows]
                            ),
                        )
                    )
                ).all()
            ) if metadata_rows else []
            existing_by_message = {
                row.gmail_message_id: row for row in existing
            }
            await _invoke(self._after_receipt_lookup)
            receipt_count = 0
            for prepared in metadata_rows:
                evidence = prepared.receipt
                stored_receipt = existing_by_message.get(
                    evidence.gmail_message_id
                )
                if prepared.sent_observation is not None:
                    await self._origin_observer.observe_history_sent_in_session(
                        session,
                        account_id=account_id,
                        message=prepared.sent_observation,
                        receipt_evidence=evidence,
                    )
                    if stored_receipt is None:
                        receipt_count += 1
                    continue
                if stored_receipt is None:
                    session.add(evidence)
                    existing_by_message[evidence.gmail_message_id] = evidence
                    receipt_count += 1
                else:
                    locked_receipt = await session.scalar(
                        select(GmailMessageReceipt)
                        .where(GmailMessageReceipt.id == stored_receipt.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if locked_receipt is None:
                        raise GmailPagePersistenceError(
                            "gmail_history_page_persistence_failed"
                        )
                    await _invoke(self._after_receipt_lock)
                    self._merge_receipt_evidence(locked_receipt, evidence)
            session.add(
                GmailSyncPageCheckpoint(
                    run_id=run_id,
                    page_number=page_number,
                    request_page_token=request_page_token,
                    next_page_token=next_page_token,
                    discovered_history_id_min=discovered_history_id_min,
                    discovered_history_id_max=discovered_history_id_max,
                    receipt_count=receipt_count,
                )
            )
            run.next_page_token = next_page_token
            if next_page_token is None:
                run.state = terminal_run_state
                run.terminal_history_id = terminal_history_id
                if terminal_run_state == "completed":
                    run.completed_at = self._clock()
                else:
                    run.discovered_at = self._clock()
            await session.commit()
        except GmailPagePersistenceError:
            await session.rollback()
            raise
        except GmailSendConflict:
            await session.rollback()
            raise GmailProviderFailure("malformed_provider") from None
        except GmailProviderFailure:
            await session.rollback()
            raise
        except (SQLAlchemyError, ValueError):
            await session.rollback()
            raise GmailPagePersistenceError(
                "gmail_history_page_persistence_failed"
            ) from None
        finally:
            await session.close()

    async def _persist_provider_failure(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        run_id: UUID | None,
        category: str,
        block: bool | None = None,
        backfill_request_id: UUID | None = None,
        fail_run: bool = True,
        alert_pending: bool = False,
    ) -> bool:
        session = self._bound_session(connection)
        try:
            if category == "oauth_revoked":
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _WORKSPACE_GMAIL_BINDING_LOCK_KEY},
                )
                if not await self._is_current_credential(session):
                    await session.rollback()
                    return False
            account = await self._account(session, account_id)
            message = _safe_message(category)
            if alert_pending:
                account.last_error_category = _alert_pending_category(category)
                account.last_error_message = "Gmail recovery alert could not be queued."
            else:
                account.last_error_category = category
                account.last_error_message = message
            if block is True or (block is None and category == "oauth_revoked"):
                account.blocked_reason = category
            if run_id is not None:
                run = await session.get(GmailSyncRun, run_id)
                if run is not None:
                    if fail_run:
                        run.state = "failed"
                    run.failure_category = category
                    run.failure_message = message
            if backfill_request_id is not None:
                request = await session.get(
                    GmailBackfillRequest,
                    backfill_request_id,
                )
                if request is not None and request.account_id == account_id:
                    request.state = "failed"
                    request.result_category = category
                    request.result_message = message
            await session.commit()
            return True
        finally:
            await session.close()

    async def _is_current_credential(self, session: AsyncSession) -> bool:
        """Fail closed unless a bound job proves its credential was superseded."""

        if self._credential_is_current is None:
            return True
        try:
            return bool(await self._credential_is_current(session))
        except asyncio.CancelledError:
            raise
        except BaseException:
            logger.error("Gmail credential generation check failed")
            return True

    async def _persist_affinity_loss(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        run_id: UUID | None,
        backfill_request_id: UUID | None = None,
    ) -> None:
        await self._persist_provider_failure(
            connection,
            account_id=account_id,
            run_id=run_id,
            category="session_affinity_lost",
            block=True,
            backfill_request_id=backfill_request_id,
        )

    async def _persist_initial_affinity_loss(
        self,
        *,
        account_id: UUID,
        backfill_request_id: UUID | None = None,
        connection: AsyncConnection | None = None,
    ) -> bool:
        """Persist pre-work affinity failure while serialization is retained."""

        async def persist(session: AsyncSession) -> bool:
            pending_incident = await session.scalar(
                select(GmailMissingMessageIncident.id)
                .where(
                    GmailMissingMessageIncident.account_id == account_id,
                    GmailMissingMessageIncident.state == "pending",
                )
                .order_by(
                    GmailMissingMessageIncident.created_at,
                    GmailMissingMessageIncident.id,
                )
                .with_for_update()
            )
            if pending_incident is not None:
                # A History worker that won the account serialization after
                # our optimistic preflight created a recoverable incident.
                # Never overwrite or terminalize the exact context required
                # by its authenticated acknowledgement protocol.
                await session.rollback()
                return True
            account = await self._account(session, account_id)
            message = _safe_message("session_affinity_lost")
            account.blocked_reason = "session_affinity_lost"
            account.last_error_category = "session_affinity_lost"
            account.last_error_message = message
            if backfill_request_id is not None:
                request = await session.get(
                    GmailBackfillRequest,
                    backfill_request_id,
                )
                if request is not None and request.account_id == account_id:
                    request.state = "failed"
                    request.result_category = "session_affinity_lost"
                    request.result_message = message
                    if request.run_id is not None:
                        run = await session.get(GmailSyncRun, request.run_id)
                        if run is not None and run.account_id == account_id:
                            run.state = "failed"
                            run.failure_category = "session_affinity_lost"
                            run.failure_message = message
            await session.commit()
            return False

        if connection is not None:
            session = self._bound_session(connection)
            try:
                return await persist(session)
            finally:
                await session.close()
        async with self._sessions() as session:
            return await persist(session)

    async def _persist_release_affinity_loss(
        self,
        *,
        account_id: UUID,
        run_id: UUID | None,
        backfill_request_id: UUID | None,
        connection: AsyncConnection | None = None,
        acquire_serialization: bool = False,
    ) -> None:
        """Block unsafe future work without rewriting terminal evidence."""

        async def persist(session: AsyncSession) -> None:
            if acquire_serialization:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": account_advisory_key(account_id)},
                )
                await _invoke(self._before_release_affinity_persist)
            account = await self._account(session, account_id)
            pending_incident = await session.scalar(
                select(GmailMissingMessageIncident.id).where(
                    GmailMissingMessageIncident.account_id == account_id,
                    GmailMissingMessageIncident.state == "pending",
                )
            )
            if pending_incident is None:
                message = _safe_message("session_affinity_lost")
                account.blocked_reason = "session_affinity_lost"
                account.last_error_category = "session_affinity_lost"
                account.last_error_message = message
                if run_id is not None:
                    run = await session.get(GmailSyncRun, run_id)
                    if run is not None and run.state in {"running", "discovered"}:
                        run.state = "failed"
                        run.failure_category = "session_affinity_lost"
                        run.failure_message = message
                if backfill_request_id is not None:
                    request = await session.get(
                        GmailBackfillRequest,
                        backfill_request_id,
                    )
                    if (
                        request is not None
                        and request.account_id == account_id
                        and request.state in {"requested", "running"}
                    ):
                        request.state = "failed"
                        request.result_category = "session_affinity_lost"
                        request.result_message = message
            await session.commit()

        if connection is not None:
            session = self._bound_session(connection)
            try:
                await persist(session)
            finally:
                await session.close()
            return
        async with self._sessions() as session:
            await persist(session)

    @staticmethod
    async def _invalidate_lock_connection(connection: AsyncConnection) -> None:
        """Discard an owner whose session-lock release cannot be proven."""

        try:
            await connection.invalidate()
        except BaseException:
            pass

    async def _persist_release_loss_after_connection_error(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        run_id: UUID | None,
        backfill_request_id: UUID | None,
    ) -> None:
        """Keep a barrier through release-failure persistence when possible."""

        persisted_on_owner = False
        if not connection.invalidated:
            try:
                await connection.rollback()
                await self._persist_release_affinity_loss(
                    account_id=account_id,
                    run_id=run_id,
                    backfill_request_id=backfill_request_id,
                    connection=connection,
                )
                persisted_on_owner = True
            except BaseException:
                pass
        await self._invalidate_lock_connection(connection)
        if not persisted_on_owner:
            # The physical owner is already gone. The first statement on the
            # trusted replacement connection takes the account transaction
            # lock, so no later History worker can pass its own post-lock
            # serialization probe while the durable block is written.
            await self._persist_release_affinity_loss(
                account_id=account_id,
                run_id=run_id,
                backfill_request_id=backfill_request_id,
                acquire_serialization=True,
            )

    async def _release_session_lock_affinity(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        expected_pid: int,
        run_id: UUID | None,
        backfill_request_id: UUID | None = None,
    ) -> None:
        """Prove ownership and release the retained account lock exactly once."""

        try:
            observed_pid, transaction_lock_acquired = await self._post_lock_probe(
                connection,
                account_id,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._persist_release_loss_after_connection_error(
                    connection,
                    account_id=account_id,
                    run_id=run_id,
                    backfill_request_id=backfill_request_id,
                )
            )
            raise
        except BaseException:
            await self._persist_release_loss_after_connection_error(
                connection,
                account_id=account_id,
                run_id=run_id,
                backfill_request_id=backfill_request_id,
            )
            raise GmailSessionAffinityLost(
                "gmail_history_session_affinity_lost"
            ) from None

        if observed_pid != expected_pid or not transaction_lock_acquired:
            await self._persist_release_affinity_loss(
                account_id=account_id,
                run_id=run_id,
                backfill_request_id=backfill_request_id,
                connection=(connection if transaction_lock_acquired else None),
            )
            await self._invalidate_lock_connection(connection)
            raise GmailSessionAffinityLost(
                "gmail_history_session_affinity_lost"
            ) from None
        try:
            released = await release_session_advisory_lock(
                connection,
                account_id,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._persist_release_loss_after_connection_error(
                    connection,
                    account_id=account_id,
                    run_id=run_id,
                    backfill_request_id=backfill_request_id,
                )
            )
            raise
        except BaseException:
            await self._persist_release_loss_after_connection_error(
                connection,
                account_id=account_id,
                run_id=run_id,
                backfill_request_id=backfill_request_id,
            )
            raise GmailSessionAffinityLost(
                "gmail_history_session_affinity_lost"
            ) from None
        if not released:
            await self._persist_release_affinity_loss(
                account_id=account_id,
                run_id=run_id,
                backfill_request_id=backfill_request_id,
                connection=connection,
            )
            await self._invalidate_lock_connection(connection)
            raise GmailSessionAffinityLost(
                "gmail_history_session_affinity_lost"
            ) from None
        await connection.commit()

    async def _establish_session_lock_affinity(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        backfill_request_id: UUID | None = None,
    ) -> tuple[bool, int | None]:
        before_pid = await self._backend_pid_reader(connection)
        acquired = await try_session_advisory_lock(connection, account_id)
        await connection.commit()
        if not acquired:
            return False, None
        after_pid, transaction_lock_acquired = await self._post_lock_probe(
            connection,
            account_id,
        )
        if after_pid != before_pid:
            if transaction_lock_acquired:
                pending_incident = await self._persist_initial_affinity_loss(
                    account_id=account_id,
                    backfill_request_id=backfill_request_id,
                    connection=connection,
                )
            else:
                # The prior backend's session lock still excludes another
                # account job while a trusted session commits the block.
                pending_incident = await self._persist_initial_affinity_loss(
                    account_id=account_id,
                    backfill_request_id=backfill_request_id,
                )
            await self._invalidate_lock_connection(connection)
            if pending_incident:
                raise GmailAccountBlocked("message_not_found") from None
            raise GmailSessionAffinityLost(
                "gmail_history_session_affinity_lost"
            ) from None
        if not transaction_lock_acquired:
            pending_incident = await self._persist_initial_affinity_loss(
                account_id=account_id,
                backfill_request_id=backfill_request_id,
            )
            await self._invalidate_lock_connection(connection)
            if pending_incident:
                raise GmailAccountBlocked("message_not_found") from None
            raise GmailSessionAffinityLost(
                "gmail_history_session_affinity_lost"
            ) from None
        return True, after_pid

    async def _verify_runtime_pid(
        self,
        connection: AsyncConnection,
        *,
        expected_pid: int,
        account_id: UUID,
        run_id: UUID | None,
        backfill_request_id: UUID | None = None,
    ) -> int:
        observed = await self._backend_pid_reader(connection)
        if observed != expected_pid:
            await self._persist_affinity_loss(
                connection,
                account_id=account_id,
                run_id=run_id,
                backfill_request_id=backfill_request_id,
            )
            raise GmailSessionAffinityLost(
                "gmail_history_session_affinity_lost"
            ) from None
        return observed

    async def _seed_first_cursor(
        self,
        connection: AsyncConnection,
        *,
        account: GmailSyncAccount,
    ) -> GmailHistorySyncResult:
        try:
            profile = await self._adapter.get_profile(account_key=str(account.id))
        except GmailProviderFailure as error:
            if error.category == "malformed_provider":
                await self._block_poll_provider_failure(
                    connection,
                    account_id=account.id,
                    run_id=None,
                    category=error.category,
                )
            else:
                await self._persist_provider_failure(
                    connection,
                    account_id=account.id,
                    run_id=None,
                    category=error.category,
                )
            raise GmailProviderFailure(error.category) from None
        session = self._bound_session(connection)
        try:
            stored = await self._account(session, account.id)
            if profile.email_address.strip().lower() != stored.workspace_email:
                stored.blocked_reason = "gmail_account_identity_mismatch"
                stored.last_error_category = _alert_pending_category(
                    "gmail_account_identity_mismatch"
                )
                stored.last_error_message = "Gmail recovery alert could not be queued."
                await session.commit()
                await session.close()
                await self._enqueue_expiry_alert(
                    connection,
                    account_id=account.id,
                    event="gmail_account_identity_mismatch",
                )
                raise GmailAccountBlocked("gmail_account_identity_mismatch")
            try:
                profile_history_id = _validated_history_id(profile.history_id)
            except GmailProviderFailure:
                await session.rollback()
                await session.close()
                await self._block_poll_provider_failure(
                    connection,
                    account_id=account.id,
                    run_id=None,
                    category="malformed_provider",
                )
                raise GmailProviderFailure("malformed_provider") from None
            if stored.committed_history_id is not None:
                raise GmailCursorConflict("gmail_cursor_compare_and_set_failed")
            stored.committed_history_id = profile_history_id
            stored.last_succeeded_at = self._clock()
            stored.blocked_reason = None
            stored.last_error_category = None
            stored.last_error_message = None
            await session.commit()
            return GmailHistorySyncResult(
                lock_acquired=True,
                start_history_id=None,
                committed_history_id=profile_history_id,
                seeded=True,
            )
        finally:
            await session.close()

    def _alert_event(
        self,
        *,
        account: GmailSyncAccount,
        event: str,
        incident_id: UUID | None = None,
        dedupe_discriminator: UUID | None = None,
    ) -> dict[str, str]:
        cursor = account.committed_history_id or "none"
        suffix = hashlib.sha256(cursor.encode("utf-8")).hexdigest()[:16]
        incident_suffix = f":{incident_id}" if incident_id is not None else ""
        discriminator_suffix = (
            f":{dedupe_discriminator}"
            if dedupe_discriminator is not None
            else ""
        )
        payload = {
            "provider": "gmail_task_intake",
            "account_id": str(account.id),
            "event": event,
            "dedupe_key": (
                f"gmail-task-intake:{account.id}:{event.replace('_', '-')}:{suffix}"
                f"{incident_suffix}{discriminator_suffix}"
            ),
        }
        if incident_id is not None:
            payload["incident_id"] = str(incident_id)
            payload["detail_path"] = (
                "/api/v1/agent-control/gmail/missing-message/incidents/"
                f"{incident_id}"
            )
        return payload

    async def _enqueue_expiry_alert(
        self,
        _connection: AsyncConnection | None,
        *,
        account_id: UUID,
        event: str,
        incident_id: UUID | None = None,
        dedupe_discriminator: UUID | None = None,
    ) -> None:
        async with self._sessions() as session:
            account = await self._account(session, account_id)
            payload = self._alert_event(
                account=account,
                event=event,
                incident_id=incident_id,
                dedupe_discriminator=dedupe_discriminator,
            )
        if self._alert_sink is None:
            async with self._sessions() as session:
                account = await self._account(session, account_id)
                account.last_error_category = _alert_pending_category(event)
                account.last_error_message = "Gmail recovery alert could not be queued."
                await session.commit()
            logger.error("Gmail recovery alert sink is unavailable")
            raise RuntimeError("gmail_history_alert_enqueue_failed") from None
        try:
            await self._alert_sink(**payload)
        except asyncio.CancelledError:
            raise
        except BaseException:
            async with self._sessions() as session:
                account = await self._account(session, account_id)
                account.last_error_category = _alert_pending_category(event)
                account.last_error_message = "Gmail recovery alert could not be queued."
                await session.commit()
            logger.error("Gmail recovery alert enqueue failed")
            raise RuntimeError("gmail_history_alert_enqueue_failed") from None
        async with self._sessions() as session:
            account = await self._account(session, account_id)
            if incident_id is not None:
                incident = await session.get(
                    GmailMissingMessageIncident,
                    incident_id,
                    with_for_update=True,
                )
                if incident is None or incident.account_id != account_id:
                    raise RuntimeError("gmail_missing_message_incident_not_found")
                incident.alert_state = "sent"
                incident.alerted_at = self._clock()
            account.last_error_category = event
            account.last_error_message = _safe_message(event)
            await session.commit()

    async def _block_on_pending_incident_before_history(
        self,
        *,
        account_id: UUID,
        run_id: UUID | None = None,
    ) -> None:
        async with self._sessions() as session:
            conditions = [
                GmailMissingMessageIncident.account_id == account_id,
                GmailMissingMessageIncident.state == "pending",
            ]
            if run_id is not None:
                conditions.append(GmailMissingMessageIncident.run_id == run_id)
            incident = await session.scalar(
                select(GmailMissingMessageIncident)
                .where(*conditions)
                .order_by(
                    GmailMissingMessageIncident.created_at,
                    GmailMissingMessageIncident.id,
                )
            )
        if incident is None:
            return
        if incident.alert_state == "pending":
            await self._enqueue_expiry_alert(
                None,
                account_id=account_id,
                event="message_not_found",
                incident_id=incident.id,
            )
        raise GmailAccountBlocked("message_not_found")

    async def _ensure_pending_receipt_alert_before_history(
        self,
        *,
        account_id: UUID,
        receipt_id: UUID | None = None,
    ) -> None:
        async with self._sessions() as session:
            conditions = [
                GmailMessageReceipt.account_id == account_id,
                GmailMessageReceipt.processing_state == "ignored",
                GmailMessageReceipt.failure_category
                == "message_not_found_alert_pending",
            ]
            if receipt_id is not None:
                conditions.append(GmailMessageReceipt.id == receipt_id)
            pending_receipt_id = await session.scalar(
                select(GmailMessageReceipt.id)
                .where(*conditions)
                .order_by(
                    GmailMessageReceipt.created_at,
                    GmailMessageReceipt.id,
                )
                .limit(1)
            )
        if pending_receipt_id is None:
            return
        await self._enqueue_expiry_alert(
            None,
            account_id=account_id,
            event="message_not_found",
            dedupe_discriminator=pending_receipt_id,
        )
        async with self._sessions() as session:
            await session.execute(
                update(GmailMessageReceipt)
                .where(
                    GmailMessageReceipt.id == pending_receipt_id,
                    GmailMessageReceipt.account_id == account_id,
                    GmailMessageReceipt.processing_state == "ignored",
                    GmailMessageReceipt.failure_category
                    == "message_not_found_alert_pending",
                )
                .values(
                    failure_category="message_not_found",
                    failure_message=_safe_message("message_not_found"),
                )
            )
            await session.commit()

    async def _recover_expired_cursor(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        run_id: UUID | None,
    ) -> None:
        session = self._bound_session(connection)
        try:
            account = await self._account(session, account_id)
            account.blocked_reason = "history_cursor_expired"
            if run_id is not None:
                run = await session.get(GmailSyncRun, run_id)
                if run is not None:
                    run.state = "blocked_expired_cursor"
                    run.failure_category = "history_cursor_expired"
                    run.failure_message = _safe_message("history_cursor_expired")
            await session.commit()
            needs_profile = account.reseed_history_id is None
            alert_pending = account.last_error_category != "history_cursor_expired"
            workspace_email = account.workspace_email
            committed_history_id = _validated_history_id(
                account.committed_history_id
            )
        finally:
            await session.close()

        if needs_profile:
            try:
                profile = await self._adapter.get_profile(account_key=str(account_id))
            except GmailProviderFailure as error:
                failure_persisted = await self._persist_provider_failure(
                    connection,
                    account_id=account_id,
                    run_id=run_id,
                    category=error.category,
                    block=(None if error.category == "oauth_revoked" else False),
                )
                if error.category != "oauth_revoked" or not failure_persisted:
                    # Preserve cursor recovery for retryable dependencies and
                    # for a revoked result from a superseded credential.
                    session = self._bound_session(connection)
                    try:
                        account = await self._account(session, account_id)
                        account.blocked_reason = "history_cursor_expired"
                        await session.commit()
                    finally:
                        await session.close()
                logger.error("Gmail cursor recovery dependency failed: %s", error.category)
                raise GmailProviderFailure(error.category) from None
            if profile.email_address.strip().lower() != workspace_email:
                session = self._bound_session(connection)
                try:
                    account = await self._account(session, account_id)
                    account.blocked_reason = "gmail_account_identity_mismatch"
                    account.last_error_category = _alert_pending_category(
                        "gmail_account_identity_mismatch"
                    )
                    account.last_error_message = "Gmail recovery alert could not be queued."
                    if run_id is not None:
                        run = await session.get(GmailSyncRun, run_id)
                        if run is not None:
                            run.state = "failed"
                            run.failure_category = "gmail_account_identity_mismatch"
                            run.failure_message = "Gmail account identity does not match."
                    await session.commit()
                finally:
                    await session.close()
                await self._enqueue_expiry_alert(
                    connection,
                    account_id=account_id,
                    event="gmail_account_identity_mismatch",
                )
                raise GmailAccountBlocked("gmail_account_identity_mismatch")
            try:
                profile_history_id = _validated_history_id(profile.history_id)
                if int(profile_history_id) < int(committed_history_id):
                    raise GmailProviderFailure("malformed_provider") from None
            except GmailProviderFailure:
                await self._persist_provider_failure(
                    connection,
                    account_id=account_id,
                    run_id=run_id,
                    category="malformed_provider",
                    block=False,
                )
                session = self._bound_session(connection)
                try:
                    account = await self._account(session, account_id)
                    account.blocked_reason = "history_cursor_expired"
                    await session.commit()
                finally:
                    await session.close()
                raise GmailProviderFailure("malformed_provider") from None
            session = self._bound_session(connection)
            try:
                account = await self._account(session, account_id)
                account.reseed_history_id = profile_history_id
                account.blocked_reason = "history_cursor_expired"
                await session.commit()
            finally:
                await session.close()
            alert_pending = True

        if alert_pending:
            await self._enqueue_expiry_alert(
                connection,
                account_id=account_id,
                event="history_cursor_expired",
            )
        raise GmailAccountBlocked("history_cursor_expired")

    async def _block_poll_pagination_guard(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        run_id: UUID,
        category: str,
    ) -> None:
        await self._persist_provider_failure(
            connection,
            account_id=account_id,
            run_id=run_id,
            category=category,
            block=True,
            alert_pending=True,
        )
        await self._enqueue_expiry_alert(
            connection,
            account_id=account_id,
            event=category,
        )

    async def _block_poll_provider_failure(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        run_id: UUID | None,
        category: str,
    ) -> None:
        await self._persist_provider_failure(
            connection,
            account_id=account_id,
            run_id=run_id,
            category=category,
            block=True,
            alert_pending=True,
        )
        await self._enqueue_expiry_alert(
            connection,
            account_id=account_id,
            event=category,
        )

    async def _block_missing_message(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        run_id: UUID,
        missing: GmailMissingMessageDetected,
        start_history_id: str,
        page_number: int,
        request_page_token: str | None,
        backfill_request_id: UUID | None = None,
    ) -> GmailMissingMessageIncident:
        try:
            message_id = parse_gmail_provider_id(missing.message_id)
            thread_id = parse_gmail_provider_id(missing.thread_id)
            canonical_page_token = parse_gmail_page_token(request_page_token)
        except ValueError:
            if backfill_request_id is None:
                await self._block_poll_provider_failure(
                    connection,
                    account_id=account_id,
                    run_id=run_id,
                    category="malformed_provider",
                )
            else:
                await self._mark_backfill_provider_failure(
                    connection,
                    request_id=backfill_request_id,
                    run_id=run_id,
                    category="malformed_provider",
                )
            raise GmailProviderFailure("malformed_provider") from None
        session = self._bound_session(connection)
        try:
            account = await self._account(session, account_id)
            run = await session.get(GmailSyncRun, run_id)
            if (
                run is None
                or run.account_id != account_id
                or run.state != "running"
                or run.start_history_id != start_history_id
                or run.next_page_token != canonical_page_token
                or run.run_kind
                != ("backfill" if backfill_request_id is not None else "poll")
            ):
                raise GmailCursorConflict(
                    "gmail_cursor_compare_and_set_failed"
                )
            incident = await session.scalar(
                select(GmailMissingMessageIncident)
                .where(
                    GmailMissingMessageIncident.account_id == account_id,
                    GmailMissingMessageIncident.run_id == run_id,
                    GmailMissingMessageIncident.gmail_message_id
                    == message_id,
                    GmailMissingMessageIncident.gmail_thread_id
                    == thread_id,
                    GmailMissingMessageIncident.page_number == page_number,
                )
                .with_for_update()
            )
            if incident is None:
                incident = GmailMissingMessageIncident(
                    account_id=account_id,
                    run_id=run_id,
                    gmail_message_id=message_id,
                    gmail_thread_id=thread_id,
                    start_history_id=start_history_id,
                    page_number=page_number,
                    request_page_token=canonical_page_token,
                )
                session.add(incident)
            elif (
                incident.gmail_thread_id != thread_id
                or incident.start_history_id != start_history_id
                or incident.request_page_token != canonical_page_token
            ):
                raise GmailCursorConflict(
                    "gmail_cursor_compare_and_set_failed"
                )
            if backfill_request_id is None:
                account.blocked_reason = "message_not_found"
            elif account.blocked_reason != "history_cursor_expired":
                raise GmailCursorConflict(
                    "gmail_cursor_compare_and_set_failed"
                )
            account.last_error_category = _alert_pending_category(
                "message_not_found"
            )
            account.last_error_message = "Gmail recovery alert could not be queued."
            run.failure_category = "message_not_found"
            run.failure_message = _safe_message("message_not_found")
            if backfill_request_id is not None:
                request = await session.get(
                    GmailBackfillRequest,
                    backfill_request_id,
                )
                if (
                    request is None
                    or request.account_id != account_id
                    or request.run_id != run_id
                    or request.state != "running"
                ):
                    raise GmailCursorConflict(
                        "gmail_cursor_compare_and_set_failed"
                    )
                request.result_category = "message_not_found"
                request.result_message = _safe_message("message_not_found")
            await session.commit()
        except (GmailCursorConflict, GmailProviderFailure):
            await session.rollback()
            raise
        except (SQLAlchemyError, ValueError):
            await session.rollback()
            raise GmailPagePersistenceError(
                "gmail_missing_message_incident_persistence_failed"
            ) from None
        finally:
            await session.close()
        await self._enqueue_expiry_alert(
            connection,
            account_id=account_id,
            event="message_not_found",
            incident_id=incident.id,
        )
        return incident

    async def _finalize_poll_cursor(
        self,
        connection: AsyncConnection,
        *,
        account_id: UUID,
        run_id: UUID,
        start_history_id: str,
        terminal_history_id: str,
    ) -> str:
        start_history_id = _validated_history_id(start_history_id)
        terminal_history_id = _validated_history_id(terminal_history_id)
        if int(terminal_history_id) < int(start_history_id):
            raise GmailProviderFailure("malformed_provider") from None
        session = self._bound_session(connection)
        try:
            changed = await session.execute(
                update(GmailSyncAccount)
                .where(
                    GmailSyncAccount.id == account_id,
                    GmailSyncAccount.committed_history_id == start_history_id,
                )
                .values(
                    committed_history_id=terminal_history_id,
                    last_succeeded_at=self._clock(),
                    last_error_category=None,
                    last_error_message=None,
                )
            )
            if changed.rowcount != 1:
                await session.rollback()
                raise GmailCursorConflict(
                    "gmail_cursor_compare_and_set_failed"
                )
            run = await session.get(GmailSyncRun, run_id)
            if (
                run is None
                or run.state != "discovered"
                or run.terminal_history_id != terminal_history_id
            ):
                await session.rollback()
                raise GmailCursorConflict(
                    "gmail_cursor_compare_and_set_failed"
                )
            run.state = "completed"
            run.completed_at = self._clock()
            run.failure_category = None
            run.failure_message = None
            await session.commit()
            return terminal_history_id
        finally:
            await session.close()

    async def sync_account(self, account_id: UUID) -> GmailHistorySyncResult:
        await self._ensure_pending_receipt_alert_before_history(
            account_id=account_id,
        )
        await self._block_on_pending_incident_before_history(
            account_id=account_id,
        )
        connection = await self._engine.connect()
        locked = False
        expected_pid: int | None = None
        run_id: UUID | None = None
        try:
            locked, expected_pid = await self._establish_session_lock_affinity(
                connection,
                account_id=account_id,
            )
            if not locked:
                return GmailHistorySyncResult(
                    lock_acquired=False,
                    start_history_id=None,
                    committed_history_id=None,
                )
            assert expected_pid is not None

            session = self._bound_session(connection)
            try:
                account = await self._account(session, account_id)
                pending_incident = await session.scalar(
                    select(GmailMissingMessageIncident)
                    .where(
                        GmailMissingMessageIncident.account_id == account_id,
                        GmailMissingMessageIncident.state == "pending",
                    )
                    .order_by(
                        GmailMissingMessageIncident.created_at,
                        GmailMissingMessageIncident.id,
                    )
                )
                if pending_incident is not None:
                    incident_id = pending_incident.id
                    incident_alert_pending = (
                        pending_incident.alert_state == "pending"
                    )
                    await session.close()
                    if incident_alert_pending:
                        await self._enqueue_expiry_alert(
                            connection,
                            account_id=account_id,
                            event="message_not_found",
                            incident_id=incident_id,
                        )
                    raise GmailAccountBlocked("message_not_found")
                if account.blocked_reason == "history_cursor_expired":
                    await session.close()
                    await self._recover_expired_cursor(
                        connection,
                        account_id=account_id,
                        run_id=None,
                    )
                if account.blocked_reason is not None:
                    blocked_reason = account.blocked_reason
                    alert_pending = (
                        account.last_error_category
                        == _alert_pending_category(blocked_reason)
                        and blocked_reason in _ALERTABLE_ACCOUNT_BLOCK_CATEGORIES
                    )
                    if alert_pending:
                        pending_incident_id = None
                        if blocked_reason == "message_not_found":
                            pending_incident_id = await session.scalar(
                                select(GmailMissingMessageIncident.id)
                                .where(
                                    GmailMissingMessageIncident.account_id
                                    == account_id,
                                    GmailMissingMessageIncident.state == "pending",
                                )
                                .order_by(
                                    GmailMissingMessageIncident.created_at,
                                    GmailMissingMessageIncident.id,
                                )
                            )
                        await session.close()
                        await self._enqueue_expiry_alert(
                            connection,
                            account_id=account_id,
                            event=blocked_reason,
                            incident_id=pending_incident_id,
                        )
                    raise GmailAccountBlocked(blocked_reason)
                if account.committed_history_id is None:
                    await session.close()
                    return await self._seed_first_cursor(connection, account=account)
                try:
                    current_history_id = _validated_history_id(
                        account.committed_history_id
                    )
                except GmailProviderFailure:
                    account.blocked_reason = "malformed_provider"
                    account.last_error_category = _alert_pending_category(
                        "malformed_provider"
                    )
                    account.last_error_message = "Gmail recovery alert could not be queued."
                    await session.commit()
                    await session.close()
                    await self._enqueue_expiry_alert(
                        connection,
                        account_id=account_id,
                        event="malformed_provider",
                    )
                    raise GmailProviderFailure("malformed_provider") from None
                run = await session.scalar(
                    select(GmailSyncRun)
                    .where(
                        GmailSyncRun.account_id == account_id,
                        GmailSyncRun.run_kind == "poll",
                        GmailSyncRun.state.in_(("running", "discovered")),
                    )
                    .order_by(GmailSyncRun.started_at.desc())
                )
                if run is None:
                    run = GmailSyncRun(
                        account_id=account_id,
                        start_history_id=current_history_id,
                        next_page_token=None,
                        run_kind="poll",
                        state="running",
                    )
                    session.add(run)
                    await session.commit()
                else:
                    try:
                        run_start_history_id = _validated_history_id(
                            run.start_history_id
                        )
                        if run.terminal_history_id is not None:
                            run_terminal_history_id = _validated_history_id(
                                run.terminal_history_id
                            )
                            if int(run_terminal_history_id) < int(
                                run_start_history_id
                            ):
                                raise GmailProviderFailure(
                                    "malformed_provider"
                                ) from None
                    except GmailProviderFailure:
                        account.blocked_reason = "malformed_provider"
                        account.last_error_category = _alert_pending_category(
                            "malformed_provider"
                        )
                        account.last_error_message = (
                            "Gmail recovery alert could not be queued."
                        )
                        run.state = "failed"
                        run.failure_category = "malformed_provider"
                        run.failure_message = _safe_message("malformed_provider")
                        await session.commit()
                        await session.close()
                        await self._enqueue_expiry_alert(
                            connection,
                            account_id=account_id,
                            event="malformed_provider",
                        )
                        raise GmailProviderFailure("malformed_provider") from None
                    if run_start_history_id != current_history_id:
                        account.blocked_reason = "cursor_conflict"
                        account.last_error_category = _alert_pending_category(
                            "cursor_conflict"
                        )
                        account.last_error_message = (
                            "Gmail recovery alert could not be queued."
                        )
                        run.state = "failed"
                        run.failure_category = "cursor_conflict"
                        run.failure_message = _safe_message("cursor_conflict")
                        await session.commit()
                        await session.close()
                        await self._enqueue_expiry_alert(
                            connection,
                            account_id=account_id,
                            event="cursor_conflict",
                        )
                        raise GmailCursorConflict(
                            "gmail_cursor_compare_and_set_failed"
                        )
                start_history_id = _validated_history_id(run.start_history_id)
                run_id = run.id
                request_token = run.next_page_token
                terminal_id = run.terminal_history_id
                run_state = run.state
                checkpoint_rows = list(
                    (
                        await session.scalars(
                            select(GmailSyncPageCheckpoint)
                            .where(GmailSyncPageCheckpoint.run_id == run.id)
                            .order_by(GmailSyncPageCheckpoint.page_number)
                        )
                    ).all()
                )
            finally:
                if session.is_active:
                    await session.close()

            if run_state == "discovered" and terminal_id is not None:
                try:
                    committed = await self._finalize_poll_cursor(
                        connection,
                        account_id=account_id,
                        run_id=run_id,
                        start_history_id=start_history_id,
                        terminal_history_id=terminal_id,
                    )
                except GmailCursorConflict:
                    await self._block_poll_provider_failure(
                        connection,
                        account_id=account_id,
                        run_id=run_id,
                        category="cursor_conflict",
                    )
                    raise GmailCursorConflict(
                        "gmail_cursor_compare_and_set_failed"
                    ) from None
                return GmailHistorySyncResult(
                    lock_acquired=True,
                    start_history_id=start_history_id,
                    committed_history_id=committed,
                )

            page_number = len(checkpoint_rows) + 1
            seen_tokens = {
                value
                for checkpoint in checkpoint_rows
                for value in (
                    checkpoint.request_page_token,
                    checkpoint.next_page_token,
                )
                if value is not None
            }
            persisted_page_count = len(checkpoint_rows)
            pages_committed = 0
            page_pids: list[int] = []
            while True:
                if persisted_page_count + pages_committed >= self._max_pages:
                    await self._block_poll_pagination_guard(
                        connection,
                        account_id=account_id,
                        run_id=run_id,
                        category="max_pages",
                    )
                    raise GmailPaginationGuard("gmail_history_max_pages")
                try:
                    page = await self._adapter.list_history(
                        account_key=str(account_id),
                        start_history_id=start_history_id,
                        page_token=request_token,
                    )
                except GmailProviderFailure as error:
                    if error.category == "history_cursor_expired":
                        await self._recover_expired_cursor(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                        )
                    if error.category == "malformed_provider":
                        await self._block_poll_provider_failure(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            category=error.category,
                        )
                    else:
                        await self._persist_provider_failure(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            category=error.category,
                            fail_run=(
                                error.category
                                not in _RETRYABLE_POLL_PROVIDER_CATEGORIES
                            ),
                        )
                    logger.error("Gmail history provider failure: %s", error.category)
                    raise GmailProviderFailure(error.category) from None
                try:
                    (
                        terminal_history_id,
                        discovered_history_id_min,
                        discovered_history_id_max,
                    ) = _validated_poll_page(
                        page,
                        start_history_id=start_history_id,
                    )
                except GmailProviderFailure:
                    await self._block_poll_provider_failure(
                        connection,
                        account_id=account_id,
                        run_id=run_id,
                        category="malformed_provider",
                    )
                    raise GmailProviderFailure("malformed_provider") from None
                next_token = page.next_page_token
                if next_token is not None and (
                    next_token == request_token or next_token in seen_tokens
                ):
                    await self._block_poll_pagination_guard(
                        connection,
                        account_id=account_id,
                        run_id=run_id,
                        category="repeated_token",
                    )
                    raise GmailPaginationGuard("gmail_history_repeated_token")
                try:
                    metadata_rows = await self._prepare_metadata(
                        account_id=account_id,
                        refs=page.messages,
                        run_id=run_id,
                        start_history_id=start_history_id,
                        page_number=page_number,
                        request_page_token=request_token,
                    )
                except GmailMissingMessageDetected as missing:
                    await self._block_missing_message(
                        connection,
                        account_id=account_id,
                        run_id=run_id,
                        missing=missing,
                        start_history_id=start_history_id,
                        page_number=page_number,
                        request_page_token=request_token,
                    )
                    raise GmailAccountBlocked("message_not_found") from None
                except GmailProviderFailure as error:
                    if error.category == "message_not_found":
                        # Backfill and non-poll metadata failures cannot be
                        # acknowledged as a poll-page tombstone.
                        await self._block_poll_provider_failure(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            category="message_not_found",
                        )
                        raise GmailAccountBlocked("message_not_found") from None
                    if error.category == "malformed_provider":
                        await self._block_poll_provider_failure(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            category=error.category,
                        )
                    else:
                        await self._persist_provider_failure(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            category=error.category,
                            fail_run=(
                                error.category
                                not in _RETRYABLE_POLL_PROVIDER_CATEGORIES
                            ),
                        )
                    raise GmailProviderFailure(error.category) from None
                try:
                    await self._persist_page(
                        connection,
                        account_id=account_id,
                        run_id=run_id,
                        page_number=page_number,
                        request_page_token=request_token,
                        next_page_token=next_token,
                        terminal_history_id=terminal_history_id,
                        discovered_history_id_min=discovered_history_id_min,
                        discovered_history_id_max=discovered_history_id_max,
                        metadata_rows=metadata_rows,
                    )
                except GmailProviderFailure as error:
                    if error.category == "malformed_provider":
                        await self._block_poll_provider_failure(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            category=error.category,
                        )
                    else:
                        await self._persist_provider_failure(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            category=error.category,
                            fail_run=True,
                        )
                    raise GmailProviderFailure(error.category) from None
                pages_committed += 1
                observed_pid = await self._verify_runtime_pid(
                    connection,
                    expected_pid=expected_pid,
                    account_id=account_id,
                    run_id=run_id,
                )
                page_pids.append(observed_pid)
                if next_token is None:
                    await _invoke(self._after_terminal_page_commit)
                    try:
                        committed = await self._finalize_poll_cursor(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            start_history_id=start_history_id,
                            terminal_history_id=terminal_history_id,
                        )
                    except GmailCursorConflict:
                        await self._block_poll_provider_failure(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            category="cursor_conflict",
                        )
                        raise GmailCursorConflict(
                            "gmail_cursor_compare_and_set_failed"
                        ) from None
                    return GmailHistorySyncResult(
                        lock_acquired=True,
                        start_history_id=start_history_id,
                        committed_history_id=committed,
                        pages_committed=pages_committed,
                        page_backend_pids=tuple(page_pids),
                    )
                seen_tokens.add(next_token)
                request_token = next_token
                page_number += 1
        finally:
            if locked:
                assert expected_pid is not None
                try:
                    await self._release_session_lock_affinity(
                        connection,
                        account_id=account_id,
                        expected_pid=expected_pid,
                        run_id=run_id,
                    )
                finally:
                    await connection.close()
            else:
                await connection.close()

    async def create_backfill_request(
        self,
        *,
        account_id: UUID,
        administrator_id: int | None,
        reason: str,
        window_start: datetime,
        window_end: datetime,
        audit_id: int,
    ) -> GmailBackfillRequest:
        cleaned_reason = reason.strip() if isinstance(reason, str) else ""
        if (
            administrator_id is None
            or not cleaned_reason
            or len(cleaned_reason) > 500
            or window_start.tzinfo is None
            or window_end.tzinfo is None
            or window_end <= window_start
            or window_end - window_start > timedelta(days=7)
        ):
            raise GmailBackfillValidationError("gmail_backfill_request_invalid")
        session = self._sessions()
        try:
            # Pause/test before the shared serialization point, then acquire
            # the lock before reading any account or active-request state.
            await _invoke(self._before_backfill_admission)
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": account_advisory_key(account_id)},
            )
            account = await session.scalar(
                select(GmailSyncAccount)
                .where(GmailSyncAccount.id == account_id)
                .with_for_update()
            )
            if account is None:
                raise GmailBackfillValidationError("gmail_backfill_not_available")
            if (
                account.blocked_reason != "history_cursor_expired"
                or account.committed_history_id is None
                or account.reseed_history_id is None
            ):
                raise GmailBackfillValidationError("gmail_backfill_not_available")
            try:
                expired_history_id = _validated_history_id(
                    account.committed_history_id
                )
                reseed_history_id = _validated_history_id(
                    account.reseed_history_id
                )
                if int(reseed_history_id) < int(expired_history_id):
                    raise GmailProviderFailure("malformed_provider") from None
            except GmailProviderFailure:
                raise GmailBackfillValidationError(
                    "gmail_backfill_snapshot_invalid"
                ) from None
            active = await session.scalar(
                select(GmailBackfillRequest.id).where(
                    GmailBackfillRequest.account_id == account_id,
                    GmailBackfillRequest.state.in_(("requested", "running")),
                )
            )
            if active is not None:
                raise GmailBackfillValidationError("active_backfill_exists")
            request = GmailBackfillRequest(
                account_id=account_id,
                administrator_id=administrator_id,
                reason=cleaned_reason,
                window_start=window_start,
                window_end=window_end,
                expired_history_id=expired_history_id,
                reseed_history_id=reseed_history_id,
                audit_id=audit_id,
                state="requested",
            )
            session.add(request)
            await session.commit()
            await session.refresh(request)
            return request
        except GmailBackfillValidationError:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def _mark_backfill_guard(
        self,
        connection: AsyncConnection,
        *,
        request_id: UUID,
        run_id: UUID,
        category: str,
    ) -> None:
        session = self._bound_session(connection)
        try:
            request = await session.get(GmailBackfillRequest, request_id)
            run = await session.get(GmailSyncRun, run_id)
            if request is not None:
                request.state = "failed"
                request.result_category = category
                request.result_message = "Gmail backfill pagination guard stopped the run."
            if run is not None:
                run.state = "failed"
                run.failure_category = category
                run.failure_message = "Gmail backfill pagination guard stopped the run."
            await session.commit()
        finally:
            await session.close()

    async def _mark_backfill_provider_failure(
        self,
        connection: AsyncConnection,
        *,
        request_id: UUID,
        run_id: UUID,
        category: str,
    ) -> bool:
        """Terminalize a definite backfill failure without moving its cursor."""

        session = self._bound_session(connection)
        try:
            if category == "oauth_revoked":
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _WORKSPACE_GMAIL_BINDING_LOCK_KEY},
                )
                if not await self._is_current_credential(session):
                    await session.rollback()
                    return False
            request = await session.get(GmailBackfillRequest, request_id)
            run = await session.get(GmailSyncRun, run_id)
            message = _safe_message(category)
            if category == "oauth_revoked" and request is not None:
                account = await self._account(session, request.account_id)
                account.blocked_reason = category
                account.last_error_category = category
                account.last_error_message = message
            if request is not None:
                request.state = "failed"
                request.result_category = category
                request.result_message = message
            if run is not None:
                run.state = "failed"
                run.failure_category = category
                run.failure_message = message
            await session.commit()
            return True
        finally:
            await session.close()

    async def run_backfill(self, request_id: UUID) -> GmailHistorySyncResult:
        async with self._sessions() as lookup:
            request = await lookup.get(GmailBackfillRequest, request_id)
            if request is None:
                raise GmailBackfillValidationError("gmail_backfill_request_not_found")
            account_id = request.account_id
            bound_run_id = request.run_id
        await self._ensure_pending_receipt_alert_before_history(
            account_id=account_id,
        )
        await self._block_on_pending_incident_before_history(
            account_id=account_id,
            run_id=bound_run_id,
        )
        connection = await self._engine.connect()
        locked = False
        expected_pid: int | None = None
        run_id: UUID | None = None
        try:
            locked, expected_pid = await self._establish_session_lock_affinity(
                connection,
                account_id=account_id,
                backfill_request_id=request_id,
            )
            if not locked:
                raise GmailBackfillExecutionBusy("gmail_backfill_already_running")
            assert expected_pid is not None
            session = self._bound_session(connection)
            try:
                request = await session.get(GmailBackfillRequest, request_id)
                if request is None or request.account_id != account_id:
                    raise GmailBackfillValidationError("gmail_backfill_request_not_found")
                account = await self._account(session, account_id)
                if (
                    account.blocked_reason != "history_cursor_expired"
                    or account.committed_history_id != request.expired_history_id
                    or account.reseed_history_id != request.reseed_history_id
                    or request.state not in {"requested", "running"}
                ):
                    raise GmailBackfillValidationError("gmail_backfill_snapshot_changed")
                try:
                    expired_history_id = _validated_history_id(
                        request.expired_history_id
                    )
                    reseed_history_id = _validated_history_id(
                        request.reseed_history_id
                    )
                    if int(reseed_history_id) < int(expired_history_id):
                        raise GmailProviderFailure("malformed_provider") from None
                except GmailProviderFailure:
                    raise GmailBackfillValidationError(
                        "gmail_backfill_snapshot_changed"
                    ) from None
                run = (
                    await session.get(GmailSyncRun, request.run_id)
                    if request.run_id is not None
                    else None
                )
                if run is None:
                    run = GmailSyncRun(
                        account_id=account_id,
                        start_history_id=expired_history_id,
                        next_page_token=None,
                        run_kind="backfill",
                        state="running",
                    )
                    session.add(run)
                    await session.flush()
                    request.run_id = run.id
                    request.state = "running"
                    request.started_at = self._clock()
                    await session.commit()
                else:
                    try:
                        run_start_history_id = _validated_history_id(
                            run.start_history_id
                        )
                    except GmailProviderFailure:
                        raise GmailBackfillValidationError(
                            "gmail_backfill_snapshot_changed"
                        ) from None
                    if run_start_history_id != expired_history_id:
                        raise GmailBackfillValidationError(
                            "gmail_backfill_snapshot_changed"
                        )
                run_id = run.id
                page_token = run.next_page_token
                run_state = run.state
                checkpoints = list(
                    (
                        await session.scalars(
                            select(GmailSyncPageCheckpoint)
                            .where(GmailSyncPageCheckpoint.run_id == run.id)
                            .order_by(GmailSyncPageCheckpoint.page_number)
                        )
                    ).all()
                )
                window_start = request.window_start
                window_end = request.window_end
                pending_incident = await session.scalar(
                    select(GmailMissingMessageIncident).where(
                        GmailMissingMessageIncident.account_id == account_id,
                        GmailMissingMessageIncident.run_id == run.id,
                        GmailMissingMessageIncident.state == "pending",
                    )
                )
                missing_alert_pending = (
                    pending_incident is not None
                    and pending_incident.alert_state == "pending"
                )
            finally:
                await session.close()

            if pending_incident is not None:
                if missing_alert_pending:
                    await self._enqueue_expiry_alert(
                        connection,
                        account_id=account_id,
                        event="message_not_found",
                        incident_id=pending_incident.id,
                    )
                raise GmailAccountBlocked("message_not_found")
            if run_state == "completed":
                return GmailHistorySyncResult(
                    lock_acquired=True,
                    start_history_id=None,
                    committed_history_id=None,
                )
            page_number = len(checkpoints) + 1
            seen_tokens = {
                value
                for checkpoint in checkpoints
                for value in (
                    checkpoint.request_page_token,
                    checkpoint.next_page_token,
                )
                if value is not None
            }
            persisted_page_count = len(checkpoints)
            pages_committed = 0
            page_pids: list[int] = []
            while True:
                if persisted_page_count + pages_committed >= self._max_pages:
                    await self._mark_backfill_guard(
                        connection,
                        request_id=request_id,
                        run_id=run_id,
                        category="max_pages",
                    )
                    raise GmailPaginationGuard("gmail_backfill_max_pages")
                try:
                    page = await self._adapter.list_messages_for_backfill(
                        account_key=str(account_id),
                        window_start=window_start,
                        window_end=window_end,
                        page_token=page_token,
                    )
                except GmailProviderFailure as error:
                    if error.category in _TERMINAL_BACKFILL_PROVIDER_CATEGORIES:
                        await self._mark_backfill_provider_failure(
                            connection,
                            request_id=request_id,
                            run_id=run_id,
                            category=error.category,
                        )
                    raise GmailProviderFailure(error.category) from None
                next_token = page.next_page_token
                if next_token is not None and (
                    next_token == page_token or next_token in seen_tokens
                ):
                    await self._mark_backfill_guard(
                        connection,
                        request_id=request_id,
                        run_id=run_id,
                        category="repeated_token",
                    )
                    raise GmailPaginationGuard("gmail_backfill_repeated_token")
                try:
                    metadata_rows = await self._prepare_metadata(
                        account_id=account_id,
                        refs=page.messages,
                        run_id=run_id,
                        start_history_id=expired_history_id,
                        page_number=page_number,
                        request_page_token=page_token,
                        window_start=window_start,
                        window_end=window_end,
                    )
                except GmailMissingMessageDetected as missing:
                    await self._block_missing_message(
                        connection,
                        account_id=account_id,
                        run_id=run_id,
                        missing=missing,
                        start_history_id=expired_history_id,
                        page_number=page_number,
                        request_page_token=page_token,
                        backfill_request_id=request_id,
                    )
                    raise GmailAccountBlocked("message_not_found") from None
                except GmailProviderFailure as error:
                    if error.category in _TERMINAL_BACKFILL_PROVIDER_CATEGORIES:
                        await self._mark_backfill_provider_failure(
                            connection,
                            request_id=request_id,
                            run_id=run_id,
                            category=error.category,
                        )
                    raise GmailProviderFailure(error.category) from None
                try:
                    await self._persist_page(
                        connection,
                        account_id=account_id,
                        run_id=run_id,
                        page_number=page_number,
                        request_page_token=page_token,
                        next_page_token=next_token,
                        terminal_history_id=(
                            reseed_history_id if next_token is None else None
                        ),
                        discovered_history_id_min=None,
                        discovered_history_id_max=None,
                        metadata_rows=metadata_rows,
                        terminal_run_state="completed",
                    )
                except GmailProviderFailure as error:
                    if error.category in _TERMINAL_BACKFILL_PROVIDER_CATEGORIES:
                        await self._mark_backfill_provider_failure(
                            connection,
                            request_id=request_id,
                            run_id=run_id,
                            category=error.category,
                        )
                    raise GmailProviderFailure(error.category) from None
                if next_token is None:
                    await _invoke(self._after_terminal_page_commit)
                pages_committed += 1
                observed = await self._verify_runtime_pid(
                    connection,
                    expected_pid=expected_pid,
                    account_id=account_id,
                    run_id=run_id,
                    backfill_request_id=request_id,
                )
                page_pids.append(observed)
                if next_token is None:
                    return GmailHistorySyncResult(
                        lock_acquired=True,
                        start_history_id=None,
                        committed_history_id=None,
                        pages_committed=pages_committed,
                        page_backend_pids=tuple(page_pids),
                    )
                seen_tokens.add(next_token)
                page_token = next_token
                page_number += 1
        finally:
            if locked:
                assert expected_pid is not None
                try:
                    await self._release_session_lock_affinity(
                        connection,
                        account_id=account_id,
                        expected_pid=expected_pid,
                        run_id=run_id,
                        backfill_request_id=request_id,
                    )
                finally:
                    await connection.close()
            else:
                await connection.close()

    async def promote_reseed_after_backfill(
        self,
        request_id: UUID,
    ) -> GmailSyncAccount:
        async with self._sessions() as lookup:
            account_id = await lookup.scalar(
                select(GmailBackfillRequest.account_id).where(
                    GmailBackfillRequest.id == request_id
                )
            )
        if account_id is None:
            raise GmailBackfillNotComplete("gmail_backfill_request_not_found")
        session = self._sessions()
        try:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": account_advisory_key(account_id)},
            )
            account = await session.scalar(
                select(GmailSyncAccount)
                .where(GmailSyncAccount.id == account_id)
                .with_for_update()
            )
            request = await session.scalar(
                select(GmailBackfillRequest)
                .where(
                    GmailBackfillRequest.id == request_id,
                    GmailBackfillRequest.account_id == account_id,
                )
                .with_for_update()
            )
            if request is None:
                raise GmailBackfillNotComplete("gmail_backfill_request_not_found")
            run = (
                await session.get(GmailSyncRun, request.run_id)
                if request.run_id is not None
                else None
            )
            if run is not None and run.run_kind != "backfill":
                raise GmailBackfillNotComplete("backfill_run_kind_required")
            final_checkpoint = None
            if run is not None:
                final_checkpoint = await session.scalar(
                    select(GmailSyncPageCheckpoint)
                    .where(GmailSyncPageCheckpoint.run_id == run.id)
                    .order_by(GmailSyncPageCheckpoint.page_number.desc())
                    .limit(1)
                )
            history_ids_valid = False
            try:
                request_expired_id = _validated_history_id(
                    request.expired_history_id
                )
                request_reseed_id = _validated_history_id(
                    request.reseed_history_id
                )
                account_expired_id = _validated_history_id(
                    account.committed_history_id if account is not None else None
                )
                account_reseed_id = _validated_history_id(
                    account.reseed_history_id if account is not None else None
                )
                run_start_id = _validated_history_id(
                    run.start_history_id if run is not None else None
                )
                run_terminal_id = _validated_history_id(
                    run.terminal_history_id if run is not None else None
                )
                history_ids_valid = (
                    int(request_reseed_id) >= int(request_expired_id)
                    and request_expired_id == account_expired_id == run_start_id
                    and request_reseed_id == account_reseed_id == run_terminal_id
                )
            except GmailProviderFailure:
                history_ids_valid = False
            valid = (
                history_ids_valid
                and account is not None
                and request.state == "running"
                and account.committed_history_id == request.expired_history_id
                and account.reseed_history_id == request.reseed_history_id
                and account.blocked_reason == "history_cursor_expired"
                and run is not None
                and run.account_id == request.account_id
                and run.start_history_id == request.expired_history_id
                and run.state == "completed"
                and run.terminal_history_id == request.reseed_history_id
                and run.next_page_token is None
                and final_checkpoint is not None
                and final_checkpoint.next_page_token is None
            )
            if not valid:
                raise GmailBackfillNotComplete("backfill_final_page_required")
            account.committed_history_id = request_reseed_id
            account.reseed_history_id = None
            account.blocked_reason = None
            account.last_error_category = None
            account.last_error_message = None
            account.last_succeeded_at = self._clock()
            request.state = "completed"
            request.result_category = "completed"
            request.result_message = "Gmail backfill completed."
            request.completed_at = self._clock()
            await session.commit()
            return account
        except GmailBackfillNotComplete:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def _persist_deterministic_receipt_failure(
        self,
        *,
        receipt_id: UUID,
        account_id: UUID,
        claimed_at: datetime,
        category: str,
    ) -> str:
        """Finalize non-retryable receipt evidence without retaining content."""

        async with self._sessions() as session:
            if category == "oauth_revoked":
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _WORKSPACE_GMAIL_BINDING_LOCK_KEY},
                )
                if not await self._is_current_credential(session):
                    receipt = await session.scalar(
                        select(GmailMessageReceipt)
                        .where(
                            GmailMessageReceipt.id == receipt_id,
                            GmailMessageReceipt.account_id == account_id,
                        )
                        .with_for_update()
                    )
                    if (
                        receipt is None
                        or receipt.processing_state != "processing"
                        or receipt.processing_started_at != claimed_at
                    ):
                        raise GmailReceiptProcessingError(
                            "gmail_receipt_claim_lost"
                        ) from None
                    receipt.processing_state = "failed"
                    receipt.processing_started_at = None
                    receipt.failure_category = "stale_credential_result"
                    receipt.failure_message = _safe_message(
                        "stale_credential_result"
                    )
                    await session.commit()
                    return "stale_credential_result"

            receipt = await session.scalar(
                select(GmailMessageReceipt)
                .where(
                    GmailMessageReceipt.id == receipt_id,
                    GmailMessageReceipt.account_id == account_id,
                )
                .with_for_update()
            )
            if (
                receipt is None
                or receipt.processing_state != "processing"
                or receipt.processing_started_at != claimed_at
            ):
                raise GmailReceiptProcessingError(
                    "gmail_receipt_claim_lost"
                ) from None
            account = await self._account(session, account_id)
            if category == "oauth_revoked":
                account.blocked_reason = category
                account.last_error_category = category
                account.last_error_message = _safe_message(category)
                receipt.processing_state = "failed"
                receipt.classification = None
                receipt.processed_at = None
            else:
                receipt.processing_state = "ignored"
                receipt.classification = f"ignored_{category}"
                receipt.processed_at = self._clock()
                if category == "message_not_found":
                    receipt.failure_category = (
                        "message_not_found_alert_pending"
                    )
                elif category in {
                    "malformed_provider",
                    "receipt_content_invalid",
                    "receipt_content_mismatch",
                }:
                    account.blocked_reason = category
                    account.last_error_category = _alert_pending_category(
                        category
                    )
                    account.last_error_message = (
                        "Gmail recovery alert could not be queued."
                    )
            receipt.processing_started_at = None
            if category != "message_not_found":
                receipt.failure_category = category
            receipt.failure_message = _safe_message(category)
            await session.commit()
            return category

    async def process_receipt(
        self,
        receipt_id: UUID,
        *,
        consumer: Callable[[SanitizedGmailMessage], Awaitable[Any]] | None,
    ) -> GmailReceiptProcessingResult:
        async with self._sessions() as lookup:
            receipt = await lookup.get(GmailMessageReceipt, receipt_id)
            if receipt is None:
                raise GmailReceiptProcessingError("gmail_receipt_not_found")
            initial = GmailReceiptProcessingResult(
                receipt_id=receipt.id,
                processing_state=receipt.processing_state,
                classification=receipt.classification,
                claimed=False,
            )
            if consumer is None or receipt.processing_state in {"processed", "ignored"}:
                return initial
            account_block = await lookup.scalar(
                select(GmailSyncAccount.blocked_reason).where(
                    GmailSyncAccount.id == receipt.account_id
                )
            )
            if account_block == "oauth_revoked":
                return initial
            now = self._clock()
            stale_before = now - timedelta(seconds=self._receipt_stale_after)
            eligible = receipt.processing_state in {"pending", "failed"} or (
                receipt.processing_state == "processing"
                and receipt.processing_started_at is not None
                and receipt.processing_started_at <= stale_before
            )
            if not eligible:
                return initial
        await _invoke(self._before_receipt_claim_flush)
        async with self._sessions() as claim_session:
            changed = await claim_session.execute(
                update(GmailMessageReceipt)
                .where(
                    GmailMessageReceipt.id == receipt_id,
                    (
                        GmailMessageReceipt.processing_state.in_(("pending", "failed"))
                        | (
                            (GmailMessageReceipt.processing_state == "processing")
                            & (GmailMessageReceipt.processing_started_at <= stale_before)
                        )
                    ),
                )
                .values(
                    processing_state="processing",
                    processing_started_at=now,
                    failure_category=None,
                    failure_message=None,
                )
            )
            if changed.rowcount != 1:
                await claim_session.rollback()
                current = await claim_session.get(GmailMessageReceipt, receipt_id)
                return GmailReceiptProcessingResult(
                    receipt_id=receipt_id,
                    processing_state=(current.processing_state if current else "failed"),
                    classification=(current.classification if current else None),
                    claimed=False,
                )
            await claim_session.commit()

        async def consume_once() -> tuple[str, str]:
            async with self._sessions() as session:
                receipt = await session.get(GmailMessageReceipt, receipt_id)
                if receipt is None:
                    raise GmailReceiptProcessingError("gmail_receipt_not_found")
                account = await self._account(session, receipt.account_id)
                origin_kind = await self._origin_kind(
                    session,
                    account_id=receipt.account_id,
                    message_id=receipt.gmail_message_id,
                )
                account_id = receipt.account_id
                message_id = receipt.gmail_message_id
                thread_id = receipt.gmail_thread_id
                mailbox_email = account.workspace_email
            content = await self._adapter.get_message_content(
                account_key=str(account_id),
                message_id=message_id,
            )
            if content.message_id != message_id or content.thread_id != thread_id:
                del content
                raise _DeterministicReceiptFailure(
                    "receipt_content_mismatch"
                ) from None
            transient = None
            sanitization_failed = False
            try:
                transient = sanitize_gmail_message(
                    content,
                    mailbox_email=mailbox_email,
                    participant_hash_key=self._participant_hash_key,
                    origin_kind=origin_kind,
                )
            except BaseException:
                sanitization_failed = True
            if sanitization_failed:
                del content
                raise _DeterministicReceiptFailure(
                    "receipt_content_invalid"
                ) from None
            del content
            assert transient is not None
            final_state = transient.processing_state
            classification = transient.classification
            direction = transient.direction
            message_at = transient.message_at
            sender_hmac = transient.sender_hmac
            recipient_hmacs_json = json.dumps(list(transient.recipient_hmacs))
            subject_preview = transient.subject_preview
            body_hash = transient.body_hash
            labels_json = json.dumps(list(transient.labels))
            if final_state != "ignored":
                try:
                    await consumer(transient)
                    final_state = "processed"
                except asyncio.CancelledError:
                    raise
                except BaseException:
                    raise _TransientReceiptConsumerFailure(
                        "gmail_receipt_consumer_failed"
                    ) from None
                finally:
                    del transient
            else:
                del transient
            await _invoke(self._before_receipt_finalize)
            async with self._sessions() as finalize:
                changed = await finalize.execute(
                    update(GmailMessageReceipt)
                    .where(
                        GmailMessageReceipt.id == receipt_id,
                        GmailMessageReceipt.processing_state == "processing",
                        GmailMessageReceipt.processing_started_at == now,
                    )
                    .values(
                        direction=direction,
                        message_at=message_at,
                        sender_hmac=sender_hmac,
                        recipient_hmacs_json=recipient_hmacs_json,
                        subject_preview=subject_preview,
                        body_hash=body_hash,
                        labels_json=labels_json,
                        processing_state=final_state,
                        classification=classification,
                        processed_at=self._clock(),
                        failure_category=None,
                        failure_message=None,
                    )
                )
                if changed.rowcount != 1:
                    await finalize.rollback()
                    raise GmailReceiptProcessingError("gmail_receipt_claim_lost")
                await finalize.commit()
            return classification, final_state

        try:
            classification, final_state = await asyncio.wait_for(
                consume_once(),
                timeout=self._receipt_deadline,
            )
        except TimeoutError:
            await self._fail_receipt(receipt_id, now, "processing_timeout")
            raise GmailReceiptProcessingError(
                "gmail_receipt_processing_timeout"
            ) from None
        except GmailProviderFailure as error:
            if error.category in {
                "message_not_found",
                "malformed_provider",
                "oauth_revoked",
            }:
                persisted_category = (
                    await self._persist_deterministic_receipt_failure(
                        receipt_id=receipt_id,
                        account_id=receipt.account_id,
                        claimed_at=now,
                        category=error.category,
                    )
                )
                if persisted_category == "message_not_found":
                    await self._ensure_pending_receipt_alert_before_history(
                        account_id=receipt.account_id,
                        receipt_id=receipt_id,
                    )
                elif persisted_category == "malformed_provider":
                    await self._enqueue_expiry_alert(
                        None,
                        account_id=receipt.account_id,
                        event=persisted_category,
                    )
                raise GmailReceiptProcessingError(
                    f"gmail_receipt_{persisted_category}"
                ) from None
            await self._fail_receipt(receipt_id, now, "transient_processing")
            logger.error("Gmail receipt provider request failed")
            raise GmailReceiptProcessingError(
                "gmail_receipt_processing_failed"
            ) from None
        except _DeterministicReceiptFailure as error:
            await self._persist_deterministic_receipt_failure(
                receipt_id=receipt_id,
                account_id=receipt.account_id,
                claimed_at=now,
                category=error.category,
            )
            await self._enqueue_expiry_alert(
                None,
                account_id=receipt.account_id,
                event=error.category,
            )
            raise GmailReceiptProcessingError(
                f"gmail_{error.category}"
            ) from None
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                await self._fail_receipt(receipt_id, now, "transient_processing")
                raise
            await self._fail_receipt(receipt_id, now, "transient_processing")
            logger.error("Gmail receipt processing failed")
            raise GmailReceiptProcessingError(
                "gmail_receipt_processing_failed"
            ) from None
        return GmailReceiptProcessingResult(
            receipt_id=receipt_id,
            processing_state=final_state,
            classification=classification,
            claimed=True,
        )

    async def _fail_receipt(
        self,
        receipt_id: UUID,
        claimed_at: datetime,
        category: str,
    ) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(GmailMessageReceipt)
                .where(
                    GmailMessageReceipt.id == receipt_id,
                    GmailMessageReceipt.processing_state == "processing",
                    GmailMessageReceipt.processing_started_at == claimed_at,
                )
                .values(
                    processing_state="failed",
                    processing_started_at=None,
                    failure_category=category,
                    failure_message=(
                        "Gmail receipt processing timed out."
                        if category == "processing_timeout"
                        else "Gmail receipt processing failed."
                    ),
                )
            )
            await session.commit()


async def acknowledge_missing_message_incident(
    db: AsyncSession,
    *,
    request: Any,
    administrator_id: int,
    incident_id: UUID,
    account_id: UUID,
    run_id: UUID,
    gmail_message_id: str,
    gmail_thread_id: str,
    expected_start_history_id: str,
    expected_page_number: int,
    expected_request_page_token: str | None,
    expected_version: int,
    reason: str,
    backfill_request_id: UUID | None = None,
    expected_reseed_history_id: str | None = None,
    audit_writer: Callable[..., Awaitable[Any]] | None = None,
) -> GmailMissingMessageIncident:
    """Acknowledge one exact deletion tombstone and resume only its bound run."""

    from services.agent_control_audit import write_agent_audit_transactional

    normalized_reason = reason.strip() if isinstance(reason, str) else ""
    if (
        not isinstance(administrator_id, int)
        or administrator_id < 1
        or not 1 <= len(normalized_reason) <= 500
        or not isinstance(expected_page_number, int)
        or expected_page_number < 1
        or not isinstance(expected_version, int)
        or expected_version < 1
    ):
        raise GmailMissingMessageAcknowledgementError(
            "gmail_missing_message_ack_invalid",
            status_code=422,
        ) from None
    try:
        gmail_message_id = parse_gmail_provider_id(gmail_message_id)
        gmail_thread_id = parse_gmail_provider_id(gmail_thread_id)
        expected_request_page_token = parse_gmail_page_token(
            expected_request_page_token
        )
        expected_start_history_id = _validated_history_id(
            expected_start_history_id
        )
        if expected_reseed_history_id is not None:
            expected_reseed_history_id = _validated_history_id(
                expected_reseed_history_id
            )
    except (GmailProviderFailure, ValueError):
        raise GmailMissingMessageAcknowledgementError(
            "gmail_missing_message_ack_invalid",
            status_code=422,
        ) from None

    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": account_advisory_key(account_id)},
    )
    account = await db.scalar(
        select(GmailSyncAccount)
        .where(GmailSyncAccount.id == account_id)
        .with_for_update()
    )
    run = await db.scalar(
        select(GmailSyncRun)
        .where(
            GmailSyncRun.id == run_id,
            GmailSyncRun.account_id == account_id,
        )
        .with_for_update()
    )
    incident = await db.scalar(
        select(GmailMissingMessageIncident)
        .where(
            GmailMissingMessageIncident.id == incident_id,
            GmailMissingMessageIncident.account_id == account_id,
            GmailMissingMessageIncident.run_id == run_id,
        )
        .with_for_update()
    )
    backfill_request = await db.scalar(
        select(GmailBackfillRequest)
        .where(
            GmailBackfillRequest.account_id == account_id,
            GmailBackfillRequest.run_id == run_id,
        )
        .with_for_update()
    )
    admin = await db.get(AdminUser, administrator_id)
    if admin is None:
        raise GmailMissingMessageAcknowledgementError(
            "gmail_missing_message_admin_required",
            status_code=403,
        )
    if incident is None:
        raise GmailMissingMessageAcknowledgementError(
            "gmail_missing_message_incident_not_found",
            status_code=404,
        )
    run_context_valid = False
    if account is not None and run is not None:
        if run.run_kind == "poll":
            run_context_valid = (
                account.blocked_reason == "message_not_found"
                and backfill_request is None
                and backfill_request_id is None
                and expected_reseed_history_id is None
            )
        elif run.run_kind == "backfill":
            run_context_valid = (
                account.blocked_reason == "history_cursor_expired"
                and backfill_request is not None
                and backfill_request.state == "running"
                and backfill_request.id == backfill_request_id
                and backfill_request.expired_history_id
                == expected_start_history_id
                and backfill_request.reseed_history_id
                == expected_reseed_history_id
                and account.reseed_history_id == expected_reseed_history_id
            )
    if (
        account is None
        or run is None
        or not run_context_valid
        or account.committed_history_id != expected_start_history_id
        or run.state != "running"
        or run.start_history_id != expected_start_history_id
        or run.next_page_token != expected_request_page_token
        or incident.state != "pending"
        or incident.version != expected_version
        or incident.gmail_message_id != gmail_message_id
        or incident.gmail_thread_id != gmail_thread_id
        or incident.start_history_id != expected_start_history_id
        or incident.page_number != expected_page_number
        or incident.request_page_token != expected_request_page_token
        or incident.alert_state != "sent"
        or incident.alerted_at is None
    ):
        raise GmailMissingMessageAcknowledgementError(
            "gmail_missing_message_ack_conflict"
        ) from None

    writer = audit_writer or write_agent_audit_transactional
    audit = await writer(
        db,
        request=request,
        actor=f"admin:{administrator_id}",
        action_id="gmail.missing_message.acknowledge",
        status_code=200,
        allowed=True,
        request_meta={
            "incident_id": str(incident_id),
            "account_id": str(account_id),
            "run_id": str(run_id),
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": gmail_thread_id,
            "expected_start_history_id": expected_start_history_id,
            "expected_page_number": expected_page_number,
            "expected_version": expected_version,
            "backfill_request_id": (
                str(backfill_request_id)
                if backfill_request_id is not None
                else None
            ),
            "reason_length": len(normalized_reason),
        },
        response_meta={"state": "acknowledged"},
    )
    if not isinstance(audit, AgentActionAudit) or audit.id is None:
        raise GmailMissingMessageAcknowledgementError(
            "gmail_missing_message_audit_required",
            status_code=500,
        ) from None

    incident.state = "acknowledged"
    incident.version += 1
    incident.acknowledged_by_admin_id = administrator_id
    incident.acknowledgement_reason = normalized_reason
    incident.action_audit_id = audit.id
    incident.acknowledged_at = datetime.now(tz=UTC)
    if run.run_kind == "poll":
        account.blocked_reason = None
        account.last_error_category = None
        account.last_error_message = None
    else:
        account.last_error_category = "history_cursor_expired"
        account.last_error_message = _safe_message("history_cursor_expired")
        assert backfill_request is not None
        backfill_request.result_category = None
        backfill_request.result_message = None
    run.failure_category = None
    run.failure_message = None
    await db.flush()
    return incident


__all__ = [
    "GmailAccountBlocked",
    "GmailBackfillExecutionBusy",
    "GmailBackfillNotComplete",
    "GmailBackfillValidationError",
    "GmailCursorConflict",
    "GmailHistoryService",
    "GmailHistorySyncResult",
    "GmailMissingMessageAcknowledgementError",
    "GmailMissingMessageIncident",
    "GmailPagePersistenceError",
    "GmailPaginationGuard",
    "GmailReceiptProcessingError",
    "GmailReceiptProcessingResult",
    "GmailSessionAffinityLost",
    "acknowledge_missing_message_incident",
]
