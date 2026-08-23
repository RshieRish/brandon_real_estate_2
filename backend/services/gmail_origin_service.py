"""Durable, fail-closed Gmail send intents and sent-message origins."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from config import settings
from models.agent_action_audit import AgentActionAudit
from models.gmail_task_intake import (
    GmailMessageOrigin,
    GmailMessageReceipt,
    GmailSyncAccount,
)
from models.setting import Setting
from services.agent_control_audit import write_agent_audit_transactional
from services.gmail_history_adapter import (
    GmailMessageContent,
    GmailProfile,
    GmailProviderFailure,
    build_gmail_service,
    parse_gmail_provider_id,
)
from services.gmail_message_sanitizer import (
    gmail_message_classification,
    sanitize_gmail_message,
)
from services.integration_health_service import (
    BoundedProviderExecutor,
    ProviderCallTimedOut,
    ProviderExecutorSaturated,
    ProviderJobStillRunning,
)


UTC = timezone.utc
GMAIL_SEND_EVIDENCE_TOLERANCE = timedelta(minutes=5)
_BINDING_KEY = "google_workspace_gmail_account_id"
_TOKEN_KEY = "google_workspace_refresh_token"
_SAFE_FAILURE_MESSAGES = {
    "provider_timeout": "Gmail delivery could not be verified.",
    "provider_cancelled": "Gmail delivery could not be verified.",
    "transient_provider": "Gmail delivery could not be verified.",
    "malformed_provider": "Gmail provider returned an invalid response.",
    "post_provider_persistence": "Gmail delivery could not be verified.",
    "provider_identity_conflict": "Gmail provider identity requires manual review.",
    "stale_sending": "Gmail delivery could not be verified.",
}


def _now() -> datetime:
    return datetime.now(tz=UTC)


class GmailSendConflict(RuntimeError):
    def __init__(self, category: str, *, status_code: int = 409) -> None:
        super().__init__(category)
        self.category = category
        self.status_code = status_code


@dataclass(frozen=True)
class CanonicalGmailSend:
    canonical_send_hash: str
    canonical_envelope_hash: str
    canonical_body_hash: str
    canonical_envelope_bytes: bytes = field(repr=False)


@dataclass(frozen=True)
class GmailSentObservation:
    """Body-free canonical evidence derived from one transient Gmail message."""

    message_id: str
    thread_id: str
    label_ids: tuple[str, ...]
    message_at: datetime
    subject_preview: str | None = field(repr=False)
    canonical_send_hash_without_thread: str
    canonical_send_hash_with_thread: str
    canonical_body_hash: str
    body_transport_compatible: bool
    body_truncated: bool

    def canonical_send_hash_for(self, intended_thread_id: str | None) -> str | None:
        if intended_thread_id is None:
            return self.canonical_send_hash_without_thread
        if intended_thread_id.strip() != self.thread_id:
            return None
        return self.canonical_send_hash_with_thread

    def canonical_send_hashes_for(
        self,
        intended_thread_id: str | None,
    ) -> tuple[str, ...]:
        selected = self.canonical_send_hash_for(intended_thread_id)
        if selected is None:
            return ()
        if intended_thread_id is None:
            return (selected,)
        # Preserve compatibility with an intent whose thread binding was
        # authenticated after its canonical payload was first claimed.
        return (selected, self.canonical_send_hash_without_thread)


@dataclass(frozen=True)
class GmailOriginResult:
    origin_id: UUID
    request_id: UUID | None
    message_id: str | None
    thread_id: str | None
    delivery_state: str
    origin_kind: str
    version: int
    replayed: bool = False
    reconciled_outcome: str | None = None
    failure_category: str | None = None
    quarantine_category: str | None = None


@dataclass(frozen=True)
class _IntentClaim:
    origin: GmailMessageOrigin
    refresh_token: str = field(repr=False)
    account_email: str
    replay: GmailOriginResult | None = None


def _canonical_email(value: str) -> str:
    return value.strip().casefold()


def _canonical_recipients(values: Any) -> tuple[str, ...]:
    return tuple(sorted(_canonical_email(str(value)) for value in values))


def _canonical_body(value: str) -> bytes:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    # `EmailMessage.set_content()` preserves existing trailing newlines and
    # appends one when absent. Hash that wire-visible text so a Gmail fetch can
    # reconcile the exact message sent by the Workspace transport.
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized.encode("utf-8")


def canonicalize_gmail_send(
    *,
    account_email: str,
    payload: Any,
    intended_thread_id: str | None,
) -> CanonicalGmailSend:
    envelope = {
        "v": 1,
        "from": _canonical_email(account_email),
        "to": _canonical_recipients(payload.to),
        "cc": _canonical_recipients(payload.cc),
        "bcc": _canonical_recipients(payload.bcc),
        "subject": payload.subject,
        "intended_thread_id": (
            intended_thread_id.strip() if intended_thread_id else None
        ),
    }
    envelope_bytes = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    body_bytes = _canonical_body(payload.body_text)
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    return CanonicalGmailSend(
        canonical_send_hash=hashlib.sha256(
            envelope_bytes + b"\x00" + body_bytes
        ).hexdigest(),
        canonical_envelope_hash=hashlib.sha256(envelope_bytes).hexdigest(),
        canonical_body_hash=body_hash,
        canonical_envelope_bytes=envelope_bytes,
    )


def _result(origin: GmailMessageOrigin, *, replayed: bool = False) -> GmailOriginResult:
    return GmailOriginResult(
        origin_id=origin.id,
        request_id=origin.request_id,
        message_id=origin.gmail_message_id,
        thread_id=origin.gmail_thread_id,
        delivery_state=origin.delivery_state,
        origin_kind=origin.origin_kind,
        version=origin.version,
        replayed=replayed,
        reconciled_outcome=origin.reconciled_outcome,
        failure_category=origin.failure_category,
        quarantine_category=origin.quarantine_category,
    )


def _safe_reason(reason: str) -> str:
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise GmailSendConflict("gmail_reconciliation_reason_invalid", status_code=422)
    return reason.strip()


def _failure_message(category: str) -> str:
    return _SAFE_FAILURE_MESSAGES.get(
        category,
        "Gmail delivery could not be verified.",
    )


def _message_time_matches_origin(
    origin: GmailMessageOrigin,
    message_at: datetime,
) -> bool:
    created_at = origin.created_at
    if created_at.tzinfo is None or message_at.tzinfo is None:
        return False
    return (
        created_at <= message_at <= created_at + GMAIL_SEND_EVIDENCE_TOLERANCE
    )


def _origin_matches_history_observation(
    origin: GmailMessageOrigin,
    observation: GmailSentObservation,
) -> bool:
    if (
        origin.delivery_state not in {"sending", "delivery_uncertain"}
        or origin.reconciled_outcome is not None
        or not observation.body_transport_compatible
        or observation.body_truncated
        or not _message_time_matches_origin(origin, observation.message_at)
    ):
        return False
    if (
        origin.intended_thread_id is not None
        and origin.intended_thread_id != observation.thread_id
    ):
        return False
    return origin.canonical_send_hash in observation.canonical_send_hashes_for(
        origin.intended_thread_id
    )


def _header(message: GmailMessageContent, name: str) -> str:
    wanted = name.casefold()
    for key, value in message.headers.items():
        if str(key).casefold() == wanted:
            return str(value)
    return ""


def _header_addresses(message: GmailMessageContent, name: str) -> list[str]:
    raw = _header(message, name)
    if not raw:
        return []
    return [address for _display, address in getaddresses([raw]) if address]


def _canonical_from_message(
    *,
    account_email: str,
    message: GmailMessageContent,
    intended_thread_id: str | None,
) -> CanonicalGmailSend:
    sender = _header_addresses(message, "from")
    payload = SimpleNamespace(
        to=_header_addresses(message, "to"),
        cc=_header_addresses(message, "cc"),
        bcc=_header_addresses(message, "bcc"),
        subject=_header(message, "subject"),
        body_text=message.body_text,
    )
    # Never synthesize a missing or ambiguous provider From header from the
    # configured account. Doing so could turn incomplete evidence into a match.
    from_email = sender[0] if len(sender) == 1 else ""
    return canonicalize_gmail_send(
        account_email=from_email,
        payload=payload,
        intended_thread_id=intended_thread_id,
    )


def prepare_gmail_sent_observation(
    *,
    account_email: str,
    message: GmailMessageContent,
) -> GmailSentObservation:
    """Consume transient content into hashes and bounded, body-free metadata."""

    labels = tuple(message.label_ids)
    if "SENT" not in {label.upper() for label in labels}:
        raise GmailSendConflict("gmail_history_message_not_sent")
    without_thread = _canonical_from_message(
        account_email=account_email,
        message=message,
        intended_thread_id=None,
    )
    with_thread = _canonical_from_message(
        account_email=account_email,
        message=message,
        intended_thread_id=message.thread_id,
    )
    subject = _header(message, "subject").strip()
    return GmailSentObservation(
        message_id=message.message_id,
        thread_id=message.thread_id,
        label_ids=labels,
        message_at=message.message_at,
        subject_preview=subject[:255] if subject else None,
        canonical_send_hash_without_thread=without_thread.canonical_send_hash,
        canonical_send_hash_with_thread=with_thread.canonical_send_hash,
        canonical_body_hash=without_thread.canonical_body_hash,
        body_transport_compatible=message.body_transport_compatible,
        body_truncated=message.body_truncated,
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


_agent_provider_executor: BoundedProviderExecutor | None = None


def get_agent_gmail_provider_executor() -> BoundedProviderExecutor:
    global _agent_provider_executor
    if _agent_provider_executor is None:
        _agent_provider_executor = BoundedProviderExecutor(
            max_workers=settings.INTEGRATION_PROVIDER_MAX_WORKERS
        )
    return _agent_provider_executor


class GmailOriginService:
    def __init__(
        self,
        *,
        engine: AsyncEngine,
        provider_executor: BoundedProviderExecutor,
        transport: Callable[..., Any],
        deadline_seconds: float,
        transactional_audit_writer: Callable[..., Awaitable[Any]] = (
            write_agent_audit_transactional
        ),
        before_intent_flush: Callable[[], Any] | None = None,
        before_history_flush: Callable[[], Any] | None = None,
        before_finalize_flush: Callable[[], Any] | None = None,
        before_finalize_commit: Callable[[], Any] | None = None,
        participant_hash_key: bytes | str | None = None,
        clock: Callable[[], datetime] = _now,
        sending_stale_after_seconds: float = 120.0,
    ) -> None:
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._executor = provider_executor
        self._transport = transport
        self._deadline = deadline_seconds
        self._audit_writer = transactional_audit_writer
        self._before_intent_flush = before_intent_flush
        self._before_history_flush = before_history_flush
        self._before_finalize_flush = before_finalize_flush
        self._before_finalize_commit = before_finalize_commit
        self._participant_hash_key = participant_hash_key
        self._clock = clock
        self._sending_stale_after = sending_stale_after_seconds

    def canonical_for_account(
        self,
        account_email: str,
        payload: Any,
        intended_thread_id: str | None = None,
    ) -> CanonicalGmailSend:
        return canonicalize_gmail_send(
            account_email=account_email,
            payload=payload,
            intended_thread_id=intended_thread_id,
        )

    @staticmethod
    def prepare_history_sent_observation(
        *,
        account_email: str,
        message: GmailMessageContent,
    ) -> GmailSentObservation:
        return prepare_gmail_sent_observation(
            account_email=account_email,
            message=message,
        )

    async def _bound_account(
        self,
        session: AsyncSession,
    ) -> tuple[GmailSyncAccount, str]:
        binding = await session.scalar(
            select(Setting).where(Setting.key == _BINDING_KEY)
        )
        if binding is None or not binding.value.strip():
            raise GmailSendConflict("gmail_account_not_bound", status_code=503)
        try:
            account_id = UUID(binding.value.strip())
        except (TypeError, ValueError):
            raise GmailSendConflict(
                "gmail_account_binding_ambiguous",
                status_code=409,
            ) from None
        account = await session.get(GmailSyncAccount, account_id)
        if account is None:
            raise GmailSendConflict("gmail_account_binding_dangling", status_code=503)
        token = await session.scalar(select(Setting).where(Setting.key == _TOKEN_KEY))
        if token is None or not token.value.strip():
            raise GmailSendConflict("gmail_database_token_missing", status_code=503)
        return account, token.value.strip()

    @staticmethod
    def _intent_meta(payload: Any) -> dict[str, Any]:
        return {
            "to_count": len(payload.to),
            "cc_count": len(payload.cc),
            "bcc_count": len(payload.bcc),
            "subject_length": len(payload.subject),
            "body_length": len(payload.body_text),
            "confirmed_by_brandon": payload.confirmed_by_brandon,
            "confirmation_note_length": len(payload.confirmation_note),
            "request_id": str(payload.request_id),
            "retry_of_request_id": (
                str(payload.retry_of_request_id)
                if payload.retry_of_request_id is not None
                else None
            ),
        }

    async def _claim(
        self,
        *,
        payload: Any,
        request: Any,
        actor: str,
        origin_kind: str,
    ) -> _IntentClaim:
        if not payload.confirmed_by_brandon:
            raise GmailSendConflict(
                "gmail_send_confirmation_required",
                status_code=422,
            )
        if origin_kind not in {"sydney_client_send", "system_automation"}:
            raise GmailSendConflict("gmail_send_origin_invalid", status_code=422)

        session = self._sessions()
        try:
            account, refresh_token = await self._bound_account(session)
            canonical = self.canonical_for_account(account.workspace_email, payload)
            existing = await session.scalar(
                select(GmailMessageOrigin)
                .where(
                    GmailMessageOrigin.account_id == account.id,
                    GmailMessageOrigin.request_id == payload.request_id,
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.canonical_send_hash != canonical.canonical_send_hash:
                    raise GmailSendConflict("gmail_send_idempotency_mismatch")
                if existing.quarantine_category is not None:
                    raise GmailSendConflict("gmail_send_quarantined")
                if existing.delivery_state == "succeeded":
                    return _IntentClaim(
                        origin=existing,
                        refresh_token=refresh_token,
                        account_email=account.workspace_email,
                        replay=_result(existing, replayed=True),
                    )
                raise GmailSendConflict("gmail_send_reconciliation_required")

            parent: GmailMessageOrigin | None = None
            if payload.retry_of_request_id is not None:
                parent = await session.scalar(
                    select(GmailMessageOrigin).where(
                        GmailMessageOrigin.account_id == account.id,
                        GmailMessageOrigin.request_id == payload.retry_of_request_id,
                    )
                )
                if parent is None:
                    raise GmailSendConflict("gmail_send_retry_parent_invalid")
                if parent.canonical_send_hash != canonical.canonical_send_hash:
                    raise GmailSendConflict("gmail_send_retry_parent_mismatch")
                if (
                    parent.reconciled_outcome != "not_delivered"
                    or parent.delivery_state
                    not in {"sending", "delivery_uncertain"}
                ):
                    raise GmailSendConflict("gmail_send_retry_parent_invalid")
                used = await session.scalar(
                    select(GmailMessageOrigin.id).where(
                        GmailMessageOrigin.retry_of_origin_id == parent.id
                    )
                )
                if used is not None:
                    raise GmailSendConflict("gmail_send_retry_parent_used")
            else:
                unresolved = await session.scalar(
                    select(GmailMessageOrigin).where(
                        GmailMessageOrigin.account_id == account.id,
                        GmailMessageOrigin.canonical_send_hash
                        == canonical.canonical_send_hash,
                        GmailMessageOrigin.delivery_state.in_(
                            ("sending", "delivery_uncertain")
                        ),
                        GmailMessageOrigin.reconciled_outcome.is_distinct_from(
                            "not_delivered"
                        ),
                    )
                )
                if unresolved is not None:
                    raise GmailSendConflict("gmail_send_reconciliation_required")
                released_candidates = list(
                    (
                        await session.scalars(
                            select(GmailMessageOrigin.id).where(
                                GmailMessageOrigin.account_id == account.id,
                                GmailMessageOrigin.canonical_send_hash
                                == canonical.canonical_send_hash,
                                GmailMessageOrigin.reconciled_outcome
                                == "not_delivered",
                            )
                        )
                    ).all()
                )
                released = False
                for released_id in released_candidates:
                    successor = await session.scalar(
                        select(GmailMessageOrigin.id).where(
                            GmailMessageOrigin.retry_of_origin_id == released_id
                        )
                    )
                    if successor is None:
                        released = True
                        break
                if released:
                    raise GmailSendConflict("gmail_send_retry_parent_required")

            try:
                audit = await self._audit_writer(
                    session,
                    request=request,
                    actor=actor,
                    action_id="workspace.gmail.send.intent",
                    status_code=202,
                    allowed=True,
                    request_meta=self._intent_meta(payload),
                    response_meta={},
                )
            except BaseException:
                await session.rollback()
                raise RuntimeError("agent_send_audit_failed") from None
            if not isinstance(audit, AgentActionAudit) or audit.id is None:
                await session.rollback()
                raise RuntimeError("agent_send_audit_failed")

            origin = GmailMessageOrigin(
                account_id=account.id,
                request_id=payload.request_id,
                retry_of_origin_id=(parent.id if parent is not None else None),
                canonical_send_hash=canonical.canonical_send_hash,
                canonical_envelope_hash=canonical.canonical_envelope_hash,
                canonical_body_hash=canonical.canonical_body_hash,
                intended_thread_id=None,
                origin_kind=origin_kind,
                delivery_state="sending",
                version=1,
                action_audit_id=audit.id,
                created_at=self._clock(),
                updated_at=self._clock(),
            )
            session.add(origin)
            await _maybe_await(
                self._before_intent_flush() if self._before_intent_flush else None
            )
            await session.flush()
            await session.commit()
            return _IntentClaim(
                origin=origin,
                refresh_token=refresh_token,
                account_email=account.workspace_email,
            )
        except IntegrityError:
            await session.rollback()
            category = (
                "gmail_send_retry_parent_used"
                if payload.retry_of_request_id is not None
                else "gmail_send_reconciliation_required"
            )
            raise GmailSendConflict(category) from None
        finally:
            await session.close()

    async def claim_intent_only(
        self,
        *,
        payload: Any,
        request: Any,
        actor: str,
        origin_kind: str = "sydney_client_send",
    ) -> GmailMessageOrigin:
        claim = await self._claim(
            payload=payload,
            request=request,
            actor=actor,
            origin_kind=origin_kind,
        )
        return claim.origin

    async def send(
        self,
        *,
        payload: Any,
        request: Any,
        actor: str,
        origin_kind: str = "sydney_client_send",
    ) -> GmailOriginResult:
        claim = await self._claim(
            payload=payload,
            request=request,
            actor=actor,
            origin_kind=origin_kind,
        )
        if claim.replay is not None:
            return claim.replay
        origin = claim.origin

        try:
            provider_result = await self._executor.run(
                key=f"gmail-send:{origin.account_id}",
                deadline_seconds=self._deadline,
                function=lambda: self._transport(
                    to=list(payload.to),
                    cc=list(payload.cc),
                    bcc=list(payload.bcc),
                    subject=payload.subject,
                    body_text=payload.body_text,
                    refresh_token=claim.refresh_token,
                    account_email=claim.account_email,
                    num_retries=0,
                ),
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._force_uncertain(
                    origin.id,
                    "provider_cancelled",
                    expected_version=1,
                )
            )
            raise
        except ProviderCallTimedOut:
            await self._force_uncertain(
                origin.id,
                "provider_timeout",
                expected_version=1,
            )
            raise RuntimeError("gmail_send_delivery_uncertain") from None
        except (ProviderJobStillRunning, ProviderExecutorSaturated):
            await self._force_uncertain(
                origin.id,
                "transient_provider",
                expected_version=1,
            )
            raise RuntimeError("gmail_send_delivery_uncertain") from None
        except BaseException as error:
            category = "malformed_provider" if isinstance(error, ValueError) else "transient_provider"
            await self._force_uncertain(
                origin.id,
                category,
                expected_version=1,
            )
            raise RuntimeError("gmail_send_delivery_uncertain") from None

        try:
            if not isinstance(provider_result, dict):
                raise ValueError
            message_id = parse_gmail_provider_id(provider_result.get("id"))
            thread_id = parse_gmail_provider_id(provider_result.get("thread_id"))
        except (TypeError, ValueError):
            await self._force_uncertain(
                origin.id,
                "malformed_provider",
                expected_version=1,
            )
            raise RuntimeError("gmail_send_delivery_uncertain") from None

        try:
            return await self.finalize_success(
                origin_id=origin.id,
                expected_version=1,
                message_id=message_id,
                thread_id=thread_id,
            )
        except GmailSendConflict as error:
            if error.category != "gmail_send_provider_identity_conflict":
                await self._force_uncertain(
                    origin.id,
                    "post_provider_persistence",
                    expected_version=1,
                )
            raise RuntimeError("gmail_send_delivery_uncertain") from None
        except BaseException:
            await self._force_uncertain(
                origin.id,
                "post_provider_persistence",
                expected_version=1,
            )
            raise RuntimeError("gmail_send_delivery_uncertain") from None

    async def _force_uncertain(
        self,
        origin_id: UUID,
        category: str,
        *,
        expected_version: int,
    ) -> None:
        session = self._sessions()
        try:
            origin = await session.scalar(
                select(GmailMessageOrigin)
                .where(GmailMessageOrigin.id == origin_id)
                .with_for_update()
            )
            if (
                origin is not None
                and origin.delivery_state == "sending"
                and origin.version == expected_version
            ):
                origin.version += 1
                origin.delivery_state = "delivery_uncertain"
                origin.failure_category = category[:64]
                origin.failure_message = _failure_message(category)
                origin.gmail_message_id = None
                origin.gmail_thread_id = None
                await session.commit()
        except BaseException:
            await session.rollback()
        finally:
            await session.close()

    async def mark_delivery_uncertain(
        self,
        *,
        origin_id: UUID,
        expected_version: int,
        category: str,
    ) -> GmailMessageOrigin:
        session = self._sessions()
        try:
            origin = await session.scalar(
                select(GmailMessageOrigin)
                .where(GmailMessageOrigin.id == origin_id)
                .with_for_update()
            )
            if (
                origin is None
                or origin.version != expected_version
                or origin.delivery_state not in {"sending", "delivery_uncertain"}
            ):
                raise GmailSendConflict("gmail_send_state_conflict")
            origin.delivery_state = "delivery_uncertain"
            origin.version += 1
            origin.failure_category = category[:64]
            origin.failure_message = _failure_message(category)
            origin.gmail_message_id = None
            origin.gmail_thread_id = None
            await session.commit()
            return origin
        finally:
            await session.close()

    def _receipt_from_origin(
        self,
        origin: GmailMessageOrigin,
        *,
        message_id: str,
        thread_id: str,
        message_at: datetime | None = None,
        labels: tuple[str, ...] = ("SENT",),
        subject_preview: str | None = None,
    ) -> GmailMessageReceipt:
        ignored = origin.origin_kind == "system_automation"
        return GmailMessageReceipt(
            account_id=origin.account_id,
            gmail_message_id=message_id,
            gmail_thread_id=thread_id,
            direction="sent",
            message_at=message_at or self._clock(),
            sender_hmac=None,
            recipient_hmacs_json="[]",
            subject_preview=(subject_preview[:255] if subject_preview else None),
            body_hash=origin.canonical_body_hash,
            labels_json=json.dumps(list(labels)),
            processing_state="ignored" if ignored else "pending",
            classification=(
                "ignored_system_automation" if ignored else "eligible"
            ),
        )

    def _receipt_evidence_from_message(
        self,
        origin: GmailMessageOrigin,
        message: GmailMessageContent,
        *,
        mailbox_email: str,
    ) -> GmailMessageReceipt:
        classification = gmail_message_classification(
            message,
            origin_kind=origin.origin_kind,
        )
        if self._participant_hash_key is None:
            receipt = self._receipt_from_origin(
                origin,
                message_id=message.message_id,
                thread_id=message.thread_id,
                message_at=message.message_at,
                labels=tuple(message.label_ids),
                subject_preview=_header(message, "subject"),
            )
            receipt.processing_state = (
                "pending" if classification == "eligible" else "ignored"
            )
            receipt.classification = classification
            return receipt
        sanitized = sanitize_gmail_message(
            message,
            mailbox_email=mailbox_email,
            participant_hash_key=self._participant_hash_key,
            origin_kind=origin.origin_kind,
        )
        receipt = GmailMessageReceipt(
            account_id=origin.account_id,
            gmail_message_id=sanitized.message_id,
            gmail_thread_id=sanitized.thread_id,
            direction=sanitized.direction,
            message_at=sanitized.message_at,
            sender_hmac=sanitized.sender_hmac,
            recipient_hmacs_json=json.dumps(list(sanitized.recipient_hmacs)),
            subject_preview=sanitized.subject_preview,
            body_hash=sanitized.body_hash,
            labels_json=json.dumps(list(sanitized.labels)),
            processing_state=sanitized.processing_state,
            classification=sanitized.classification,
        )
        del sanitized
        return receipt

    async def _ensure_receipt(
        self,
        session: AsyncSession,
        origin: GmailMessageOrigin,
        *,
        message_id: str,
        thread_id: str,
        message_at: datetime | None = None,
        labels: tuple[str, ...] = ("SENT",),
        subject_preview: str | None = None,
        receipt_evidence: GmailMessageReceipt | None = None,
    ) -> GmailMessageReceipt:
        if receipt_evidence is not None and (
            receipt_evidence.account_id != origin.account_id
            or receipt_evidence.gmail_message_id != message_id
            or receipt_evidence.gmail_thread_id != thread_id
        ):
            raise GmailSendConflict("gmail_history_receipt_evidence_invalid")
        receipt = await session.scalar(
            select(GmailMessageReceipt)
            .where(
                GmailMessageReceipt.account_id == origin.account_id,
                GmailMessageReceipt.gmail_message_id == message_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt is None:
            receipt = receipt_evidence or self._receipt_from_origin(
                origin,
                message_id=message_id,
                thread_id=thread_id,
                message_at=message_at,
                labels=labels,
                subject_preview=subject_preview,
            )
            session.add(receipt)
        elif receipt.gmail_thread_id != thread_id:
            raise GmailSendConflict("gmail_send_provider_identity_conflict")
        elif receipt_evidence is not None:
            receipt.direction = receipt_evidence.direction
            receipt.message_at = receipt_evidence.message_at
            receipt.sender_hmac = receipt_evidence.sender_hmac
            receipt.recipient_hmacs_json = receipt_evidence.recipient_hmacs_json
            receipt.subject_preview = receipt_evidence.subject_preview
            receipt.body_hash = receipt_evidence.body_hash
            receipt.labels_json = receipt_evidence.labels_json
            if (
                receipt_evidence.processing_state == "ignored"
                and receipt.processing_state in {"pending", "failed"}
            ):
                receipt.processing_state = "ignored"
                receipt.classification = receipt_evidence.classification
                receipt.processing_started_at = None
                receipt.failure_category = None
                receipt.failure_message = None
            elif receipt.processing_state == "pending":
                receipt.processing_state = receipt_evidence.processing_state
                receipt.classification = receipt_evidence.classification
                receipt.failure_category = None
                receipt.failure_message = None
        return receipt

    async def finalize_success(
        self,
        *,
        origin_id: UUID,
        expected_version: int,
        message_id: str,
        thread_id: str,
    ) -> GmailOriginResult:
        await _maybe_await(
            self._before_finalize_flush() if self._before_finalize_flush else None
        )
        session = self._sessions()
        try:
            origin = await session.scalar(
                select(GmailMessageOrigin)
                .where(GmailMessageOrigin.id == origin_id)
                .with_for_update()
            )
            if origin is None:
                raise GmailSendConflict("gmail_send_state_conflict")
            if origin.delivery_state == "succeeded":
                identity_matches = (
                    origin.gmail_message_id == message_id
                    and origin.gmail_thread_id == thread_id
                )
                if identity_matches:
                    await self._ensure_receipt(
                        session,
                        origin,
                        message_id=message_id,
                        thread_id=thread_id,
                    )
                    await session.commit()
                    return _result(origin, replayed=True)
                origin.version += 1
                origin.quarantine_category = "provider_identity_conflict"
                origin.quarantine_evidence = (
                    "Provider response conflicted with Gmail History evidence."
                )
                origin.failure_category = "provider_identity_conflict"
                origin.failure_message = _failure_message(
                    "provider_identity_conflict"
                )
                await session.flush()
                await _maybe_await(
                    self._before_finalize_commit()
                    if self._before_finalize_commit
                    else None
                )
                await session.commit()
                raise GmailSendConflict("gmail_send_provider_identity_conflict")
            if origin.version != expected_version or origin.delivery_state != "sending":
                raise GmailSendConflict("gmail_send_state_conflict")
            origin.gmail_message_id = message_id
            origin.gmail_thread_id = thread_id
            origin.delivery_state = "succeeded"
            origin.version += 1
            origin.failure_category = None
            origin.failure_message = None
            await self._ensure_receipt(
                session,
                origin,
                message_id=message_id,
                thread_id=thread_id,
            )
            await session.flush()
            await _maybe_await(
                self._before_finalize_commit()
                if self._before_finalize_commit
                else None
            )
            await session.commit()
            return _result(origin)
        finally:
            await session.close()

    async def reconcile_stale_sending(
        self,
        *,
        account_id: UUID,
        request_id: UUID,
        expected_version: int,
        reason: str,
    ) -> GmailOriginResult:
        _safe_reason(reason)
        session = self._sessions()
        try:
            origin = await session.scalar(
                select(GmailMessageOrigin)
                .where(
                    GmailMessageOrigin.account_id == account_id,
                    GmailMessageOrigin.request_id == request_id,
                )
                .with_for_update()
            )
            if (
                origin is None
                or origin.delivery_state != "sending"
                or origin.version != expected_version
            ):
                raise GmailSendConflict("gmail_reconciliation_state_conflict")
            cutoff = self._clock() - timedelta(seconds=self._sending_stale_after)
            if origin.created_at > cutoff:
                raise GmailSendConflict("gmail_send_still_in_flight")
            origin.delivery_state = "delivery_uncertain"
            origin.version += 1
            origin.failure_category = "stale_sending"
            origin.failure_message = _failure_message("stale_sending")
            await session.commit()
            return _result(origin)
        finally:
            await session.close()

    async def mark_not_delivered(
        self,
        *,
        account_id: UUID,
        request_id: UUID,
        expected_state: str,
        expected_version: int,
        reason: str,
        request: Any,
        actor: str,
    ) -> GmailOriginResult:
        bounded_reason = _safe_reason(reason)
        session = self._sessions()
        try:
            origin = await session.scalar(
                select(GmailMessageOrigin)
                .where(
                    GmailMessageOrigin.account_id == account_id,
                    GmailMessageOrigin.request_id == request_id,
                )
                .with_for_update()
            )
            if origin is not None and origin.quarantine_category is not None:
                raise GmailSendConflict("gmail_send_quarantined")
            if (
                origin is None
                or expected_state != "delivery_uncertain"
                or origin.delivery_state != expected_state
                or origin.version != expected_version
                or origin.delivery_state != "delivery_uncertain"
                or origin.reconciled_outcome is not None
            ):
                raise GmailSendConflict("gmail_reconciliation_state_conflict")
            origin.reconciled_outcome = "not_delivered"
            origin.reconciled_at = self._clock()
            origin.version += 1
            try:
                audit = await self._audit_writer(
                    session,
                    request=request,
                    actor=actor,
                    action_id="workspace.gmail.send.reconcile.not_delivered",
                    status_code=200,
                    allowed=True,
                    request_meta={
                        "request_id": str(request_id),
                        "expected_state": expected_state,
                        "expected_version": expected_version,
                        "reason_length": len(bounded_reason),
                    },
                    response_meta={"outcome": "not_delivered"},
                )
            except BaseException:
                await session.rollback()
                raise RuntimeError("gmail_reconciliation_audit_failed") from None
            if not isinstance(audit, AgentActionAudit) or audit.id is None:
                await session.rollback()
                raise RuntimeError("gmail_reconciliation_audit_failed") from None
            await session.commit()
            return _result(origin)
        finally:
            await session.close()

    async def _select_history_origin(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        message: GmailMessageContent | GmailSentObservation,
    ) -> tuple[GmailSyncAccount, UUID | None, GmailSentObservation]:
        if "SENT" not in {label.upper() for label in message.label_ids}:
            raise GmailSendConflict("gmail_history_message_not_sent")
        account = await session.get(GmailSyncAccount, account_id)
        if account is None:
            raise GmailSendConflict(
                "gmail_account_binding_dangling",
                status_code=503,
            )
        observation = (
            message
            if isinstance(message, GmailSentObservation)
            else prepare_gmail_sent_observation(
                account_email=account.workspace_email,
                message=message,
            )
        )
        existing_by_message = await session.scalar(
            select(GmailMessageOrigin).where(
                GmailMessageOrigin.account_id == account_id,
                GmailMessageOrigin.gmail_message_id == observation.message_id,
            )
        )
        candidates = list(
            (
                await session.scalars(
                    select(GmailMessageOrigin).where(
                        GmailMessageOrigin.account_id == account_id,
                        GmailMessageOrigin.origin_kind.in_(
                            ("sydney_client_send", "system_automation")
                        ),
                        GmailMessageOrigin.delivery_state.in_(
                            ("sending", "delivery_uncertain")
                        ),
                        GmailMessageOrigin.reconciled_outcome.is_(None),
                    )
                    .order_by(
                        GmailMessageOrigin.created_at.desc(),
                        GmailMessageOrigin.version.desc(),
                    )
                )
            ).all()
        )
        selected = existing_by_message
        if selected is None:
            for candidate in candidates:
                if _origin_matches_history_observation(candidate, observation):
                    selected = candidate
                if selected is not None:
                    break
        return account, selected.id if selected is not None else None, observation

    async def observe_history_sent_in_session(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        message: GmailMessageContent | GmailSentObservation,
        selected_origin_id: UUID | None = None,
        receipt_evidence: GmailMessageReceipt | None = None,
    ) -> GmailOriginResult:
        observation: GmailSentObservation
        if selected_origin_id is None:
            _account, selected_origin_id, observation = await self._select_history_origin(
                session,
                account_id=account_id,
                message=message,
            )
        elif isinstance(message, GmailSentObservation):
            observation = message
        else:
            account = await session.get(GmailSyncAccount, account_id)
            if account is None:
                raise GmailSendConflict(
                    "gmail_account_binding_dangling",
                    status_code=503,
                )
            observation = prepare_gmail_sent_observation(
                account_email=account.workspace_email,
                message=message,
            )
            del message
        origin: GmailMessageOrigin | None = None
        if selected_origin_id is not None:
            selected_origin = await session.scalar(
                select(GmailMessageOrigin)
                .where(GmailMessageOrigin.id == selected_origin_id)
                .with_for_update()
            )
            if selected_origin is not None and selected_origin.delivery_state == "succeeded":
                if (
                    selected_origin.gmail_message_id != observation.message_id
                    or selected_origin.gmail_thread_id != observation.thread_id
                ):
                    raise GmailSendConflict("gmail_send_provider_identity_conflict")
                origin = selected_origin
            elif selected_origin is not None and _origin_matches_history_observation(
                selected_origin,
                observation,
            ):
                origin = selected_origin
            else:
                _account, reselected_id, _observation = await self._select_history_origin(
                    session,
                    account_id=account_id,
                    message=observation,
                )
                if reselected_id is not None and reselected_id != selected_origin_id:
                    reselected = await session.scalar(
                        select(GmailMessageOrigin)
                        .where(GmailMessageOrigin.id == reselected_id)
                        .with_for_update()
                    )
                    if reselected is not None and reselected.delivery_state == "succeeded":
                        if (
                            reselected.gmail_message_id != observation.message_id
                            or reselected.gmail_thread_id != observation.thread_id
                        ):
                            raise GmailSendConflict(
                                "gmail_send_provider_identity_conflict"
                            )
                        origin = reselected
                    elif reselected is not None and _origin_matches_history_observation(
                        reselected,
                        observation,
                    ):
                        origin = reselected
        if origin is not None:
            replayed = origin.delivery_state == "succeeded"
            if (
                origin.gmail_message_id not in {None, observation.message_id}
                or origin.gmail_thread_id not in {None, observation.thread_id}
            ):
                raise GmailSendConflict("gmail_send_provider_identity_conflict")
            if not replayed:
                origin.gmail_message_id = observation.message_id
                origin.gmail_thread_id = observation.thread_id
                origin.delivery_state = "succeeded"
                origin.version += 1
                # Independent exact History evidence is the only recovery path
                # from an operator-candidate quarantine. Keep its immutable
                # evidence, but restore eligibility after successful proof.
                origin.quarantine_category = None
            if not replayed or origin.quarantine_category is None:
                origin.failure_category = None
                origin.failure_message = None
        else:
            origin = GmailMessageOrigin(
                account_id=account_id,
                request_id=None,
                canonical_send_hash=None,
                canonical_envelope_hash=None,
                canonical_body_hash=None,
                gmail_message_id=observation.message_id,
                gmail_thread_id=observation.thread_id,
                origin_kind="human_send",
                delivery_state="succeeded",
                version=1,
                action_audit_id=None,
            )
            session.add(origin)
            replayed = False
            await session.flush()
        if receipt_evidence is not None and origin.origin_kind == "system_automation":
            receipt_evidence.processing_state = "ignored"
            receipt_evidence.classification = "ignored_system_automation"
        await self._ensure_receipt(
            session,
            origin,
            message_id=observation.message_id,
            thread_id=observation.thread_id,
            message_at=observation.message_at,
            labels=observation.label_ids,
            subject_preview=observation.subject_preview,
            receipt_evidence=receipt_evidence,
        )
        await session.flush()
        return _result(origin, replayed=replayed)

    async def observe_history_sent(
        self,
        *,
        account_id: UUID,
        message: GmailMessageContent,
    ) -> GmailOriginResult:
        async with self._sessions() as lookup:
            _account, selected_origin_id, observation = await self._select_history_origin(
                lookup,
                account_id=account_id,
                message=message,
            )
        del message
        await _maybe_await(
            self._before_history_flush() if self._before_history_flush else None
        )
        session = self._sessions()
        try:
            result = await self.observe_history_sent_in_session(
                session,
                account_id=account_id,
                message=observation,
                selected_origin_id=selected_origin_id,
            )
            await session.commit()
            return result
        except IntegrityError:
            await session.rollback()
            async with self._sessions() as reload:
                origin = await reload.scalar(
                    select(GmailMessageOrigin).where(
                        GmailMessageOrigin.account_id == account_id,
                        GmailMessageOrigin.gmail_message_id == observation.message_id,
                    )
                )
                if (
                    origin is None
                    or origin.gmail_thread_id != observation.thread_id
                ):
                    raise GmailSendConflict(
                        "gmail_send_provider_identity_conflict"
                    ) from None
                return _result(origin, replayed=True)
        finally:
            await session.close()

    async def _fetch_reconciliation(
        self,
        *,
        account_id: UUID,
        fetcher: Callable[..., Any],
        kind: str,
        message_id: str | None = None,
    ) -> Any:
        try:
            return await self._executor.run(
                key=f"gmail-reconcile:{account_id}",
                deadline_seconds=self._deadline,
                function=lambda: fetcher(
                    kind=kind,
                    message_id=message_id,
                    num_retries=0,
                ),
            )
        except ProviderCallTimedOut:
            raise GmailProviderFailure("transient_provider") from None
        except (ProviderJobStillRunning, ProviderExecutorSaturated):
            raise GmailProviderFailure("transient_provider") from None
        except GmailProviderFailure as error:
            raise GmailProviderFailure(error.category) from None
        except BaseException:
            raise GmailProviderFailure("transient_provider") from None

    async def reconcile_delivered_candidate(
        self,
        *,
        account_id: UUID,
        request_id: UUID,
        expected_state: str,
        expected_version: int,
        reason: str,
        candidate_message_id: str,
        candidate_thread_id: str,
        fetcher: Callable[..., Any],
        request: Any,
        actor: str,
    ) -> GmailOriginResult:
        bounded_reason = _safe_reason(reason)
        async with self._sessions() as lookup:
            account = await lookup.get(GmailSyncAccount, account_id)
            origin = await lookup.scalar(
                select(GmailMessageOrigin).where(
                    GmailMessageOrigin.account_id == account_id,
                    GmailMessageOrigin.request_id == request_id,
                )
            )
        if (
            account is None
            or origin is None
            or origin.delivery_state != expected_state
            or origin.version != expected_version
            or origin.delivery_state != "delivery_uncertain"
        ):
            raise GmailSendConflict("gmail_reconciliation_state_conflict")
        if origin.quarantine_category is not None:
            raise GmailSendConflict("gmail_send_quarantined")

        profile = await self._fetch_reconciliation(
            account_id=account_id,
            fetcher=fetcher,
            kind="profile",
        )
        category: str | None = None
        message: GmailMessageContent | None = None
        if not isinstance(profile, GmailProfile) or (
            _canonical_email(profile.email_address)
            != _canonical_email(account.workspace_email)
        ):
            category = "candidate_account_mismatch"
        else:
            try:
                fetched = await self._fetch_reconciliation(
                    account_id=account_id,
                    fetcher=fetcher,
                    kind="message",
                    message_id=candidate_message_id,
                )
                if isinstance(fetched, GmailMessageContent):
                    message = fetched
                    del fetched
                else:
                    category = "candidate_message_mismatch"
            except GmailProviderFailure as error:
                if error.category == "message_not_found":
                    category = "candidate_message_missing"
                else:
                    raise GmailProviderFailure(error.category) from None

        if category is None and message is not None:
            if message.message_id != candidate_message_id:
                category = "candidate_message_mismatch"
            elif "SENT" not in {label.upper() for label in message.label_ids}:
                category = "candidate_not_sent"
            elif message.thread_id != candidate_thread_id:
                category = "candidate_thread_mismatch"
            elif (
                origin.intended_thread_id is not None
                and message.thread_id != origin.intended_thread_id
            ):
                category = "candidate_intended_thread_mismatch"
            elif not _message_time_matches_origin(origin, message.message_at):
                category = "candidate_time_mismatch"
            elif not message.body_transport_compatible:
                category = "candidate_mime_ambiguous"
            elif message.body_truncated:
                category = "candidate_body_truncated"
            else:
                canonical = _canonical_from_message(
                    account_email=account.workspace_email,
                    message=message,
                    intended_thread_id=origin.intended_thread_id,
                )
                if canonical.canonical_envelope_hash != origin.canonical_envelope_hash:
                    category = "candidate_envelope_mismatch"
                elif canonical.canonical_body_hash != origin.canonical_body_hash:
                    category = "candidate_body_mismatch"

        receipt_evidence: GmailMessageReceipt | None = None
        verified_message_id: str | None = None
        verified_thread_id: str | None = None
        verified_message_at: datetime | None = None
        verified_labels: tuple[str, ...] = ()
        verified_subject: str | None = None
        if category is None and message is not None:
            try:
                receipt_evidence = self._receipt_evidence_from_message(
                    origin,
                    message,
                    mailbox_email=account.workspace_email,
                )
            except (IndexError, TypeError, ValueError):
                category = "candidate_message_mismatch"
            else:
                verified_message_id = message.message_id
                verified_thread_id = message.thread_id
                verified_message_at = message.message_at
                verified_labels = tuple(message.label_ids)
                verified_subject = _header(message, "subject")
        if message is not None:
            del message

        session = self._sessions()
        try:
            stored = await session.scalar(
                select(GmailMessageOrigin)
                .where(
                    GmailMessageOrigin.account_id == account_id,
                    GmailMessageOrigin.request_id == request_id,
                )
                .with_for_update()
            )
            if (
                stored is None
                or stored.delivery_state != expected_state
                or stored.version != expected_version
                or stored.delivery_state != "delivery_uncertain"
            ):
                raise GmailSendConflict("gmail_reconciliation_state_conflict")
            if stored.quarantine_category is not None:
                raise GmailSendConflict("gmail_send_quarantined")
            if category is not None:
                stored.quarantine_category = category
                stored.quarantine_evidence = "Candidate Gmail message did not verify."
                stored.version += 1
                action_id = "workspace.gmail.send.reconcile.delivered.quarantine"
                allowed = False
                response_meta = {"outcome": "quarantined", "category": category}
            else:
                assert verified_message_id is not None
                assert verified_thread_id is not None
                assert verified_message_at is not None
                stored.delivery_state = "succeeded"
                stored.gmail_message_id = verified_message_id
                stored.gmail_thread_id = verified_thread_id
                stored.reconciled_outcome = "delivered"
                stored.reconciled_at = self._clock()
                stored.failure_category = None
                stored.failure_message = None
                stored.version += 1
                await self._ensure_receipt(
                    session,
                    stored,
                    message_id=verified_message_id,
                    thread_id=verified_thread_id,
                    message_at=verified_message_at,
                    labels=verified_labels,
                    subject_preview=verified_subject,
                    receipt_evidence=receipt_evidence,
                )
                action_id = "workspace.gmail.send.reconcile.delivered"
                allowed = True
                response_meta = {"outcome": "delivered"}
            try:
                audit = await self._audit_writer(
                    session,
                    request=request,
                    actor=actor,
                    action_id=action_id,
                    status_code=200,
                    allowed=allowed,
                    request_meta={
                        "request_id": str(request_id),
                        "expected_state": expected_state,
                        "expected_version": expected_version,
                        "reason_length": len(bounded_reason),
                    },
                    response_meta=response_meta,
                )
            except BaseException:
                await session.rollback()
                raise RuntimeError("gmail_reconciliation_audit_failed") from None
            if not isinstance(audit, AgentActionAudit) or audit.id is None:
                await session.rollback()
                raise RuntimeError("gmail_reconciliation_audit_failed") from None
            await session.commit()
            return _result(stored)
        finally:
            await session.close()


async def send_agent_gmail_with_origin(
    *,
    db: AsyncSession,
    payload: Any,
    request: Any,
    actor: str,
) -> GmailOriginResult:
    from services.workspace_service import (
        WorkspaceIntegrationError,
        send_gmail_message,
        workspace_oauth_client_settings,
    )

    engine = db.bind
    if not isinstance(engine, AsyncEngine):
        raise RuntimeError("gmail_send_database_binding_required")
    try:
        oauth_client = workspace_oauth_client_settings()
    except WorkspaceIntegrationError:
        raise RuntimeError("gmail_workspace_oauth_config_required") from None

    def transport(**kwargs: Any) -> dict[str, str]:
        gmail = build_gmail_service(
            refresh_token=kwargs["refresh_token"],
            client_id=oauth_client.client_id,
            client_secret=oauth_client.client_secret,
            socket_timeout_seconds=(
                settings.INTEGRATION_PROVIDER_SOCKET_TIMEOUT_SECONDS
            ),
        )

        return send_gmail_message(
            to=kwargs["to"],
            cc=kwargs["cc"],
            bcc=kwargs["bcc"],
            subject=kwargs["subject"],
            body_text=kwargs["body_text"],
            gmail_client=gmail,
        )

    service = GmailOriginService(
        engine=engine,
        provider_executor=get_agent_gmail_provider_executor(),
        transport=transport,
        deadline_seconds=settings.INTEGRATION_PROVIDER_DEADLINE_SECONDS,
    )
    return await service.send(
        payload=payload,
        request=request,
        actor=actor,
    )
