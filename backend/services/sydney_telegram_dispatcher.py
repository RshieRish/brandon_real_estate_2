"""Outbound-only Telegram delivery state machine for Sydney clarifications."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Callable, Mapping
from uuid import UUID, uuid4

import requests
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.gmail_task_intake import CRMTaskSuggestion
from models.sydney_tasks import (
    CRMTaskClarification,
    CRMTaskSuggestionEvent,
    SydneyQuestionOutbox,
)
from services.sydney_clarification_service import (
    SydneyClarificationError,
    clarification_code_hash,
    derive_clarification_code,
    rendered_question_hash,
    supersede_locked_clarification,
)
from services.sydney_clarification_service import (
    render_clarification_question as _render_question,
)


__all__ = (
    "clarification_code_hash",
    "derive_clarification_code",
    "rendered_question_hash",
)


TELEGRAM_RESPONSE_MAX_BYTES = 64 * 1024
_TELEGRAM_TEXT_MAX = 4096
_CHAT_ID_RE = re.compile(r"-?[1-9][0-9]*")
_BOT_TOKEN_RE = re.compile(r"[1-9][0-9]{4,15}:[A-Za-z0-9_-]{20,128}")
TELEGRAM_INTERRUPTED_RECOVERY_MARGIN_SECONDS = 5.0


class TelegramConfigurationError(RuntimeError):
    """A secret-free Telegram configuration failure."""


class TelegramDispatchError(RuntimeError):
    """A sanitized Telegram dispatch boundary failure."""


class TelegramProviderRejected(TelegramDispatchError):
    """A definite Telegram 4xx rejection before accepted delivery."""


class TelegramDeliveryUncertain(TelegramDispatchError):
    """A failure for which delivery cannot be ruled out."""


def _configuration_error() -> TelegramConfigurationError:
    error = TelegramConfigurationError("sydney_telegram_configuration_invalid")
    error.__cause__ = None
    error.__context__ = None
    return error


def _dispatch_error(category: str, kind: type[TelegramDispatchError]) -> TelegramDispatchError:
    error = kind(category)
    error.__cause__ = None
    error.__context__ = None
    return error


def _chat_id_valid(value: object) -> bool:
    if type(value) is not str or _CHAT_ID_RE.fullmatch(value) is None:
        return False
    try:
        numeric = int(value)
    except ValueError:
        return False
    return -(2**52) < numeric < 2**52


def _positive_finite(value: object) -> bool:
    return (
        type(value) in {int, float}
        and math.isfinite(float(value))
        and float(value) > 0
    )


class SydneyTelegramDispatcherConfig:
    """Validated immutable configuration without secret-bearing repr output."""

    def __init__(
        self,
        *,
        enabled: bool,
        bot_token: str,
        brandon_chat_id: str,
        clarification_code_keys: Mapping[int, bytes],
        active_code_key_version: int,
        provider_deadline_seconds: float,
        provider_socket_timeout_seconds: float,
    ) -> None:
        if type(enabled) is not bool:
            raise _configuration_error()
        if not _positive_finite(provider_deadline_seconds) or not _positive_finite(
            provider_socket_timeout_seconds
        ):
            raise _configuration_error()
        if float(provider_socket_timeout_seconds) >= float(
            provider_deadline_seconds
        ):
            raise _configuration_error()
        frozen_keys: dict[int, bytes] = {}
        try:
            key_items = clarification_code_keys.items()
        except AttributeError:
            raise _configuration_error() from None
        for version, key in key_items:
            if (
                type(version) is not int
                or not 1 <= version <= 32767
                or type(key) is not bytes
                or len(key) != 32
            ):
                raise _configuration_error()
            frozen_keys[version] = bytes(key)
        if enabled and (
            type(bot_token) is not str
            or _BOT_TOKEN_RE.fullmatch(bot_token) is None
            or not _chat_id_valid(brandon_chat_id)
            or type(active_code_key_version) is not int
            or active_code_key_version not in frozen_keys
        ):
            raise _configuration_error()
        self.enabled = enabled
        self.bot_token = bot_token
        self.brandon_chat_id = brandon_chat_id
        self.clarification_code_keys = MappingProxyType(frozen_keys)
        self.active_code_key_version = active_code_key_version
        self.provider_deadline_seconds = float(provider_deadline_seconds)
        self.provider_socket_timeout_seconds = float(
            provider_socket_timeout_seconds
        )

    def __repr__(self) -> str:
        return (
            "SydneyTelegramDispatcherConfig("
            f"enabled={self.enabled!r}, "
            f"brandon_chat_id={self.brandon_chat_id!r}, "
            f"active_code_key_version={self.active_code_key_version!r}, "
            f"configured_key_versions="
            f"{tuple(sorted(self.clarification_code_keys))!r}, "
            f"provider_deadline_seconds={self.provider_deadline_seconds!r}, "
            "provider_socket_timeout_seconds="
            f"{self.provider_socket_timeout_seconds!r})"
        )


def render_clarification_question(
    *, template_id: str, context_json: str, code: str
) -> str:
    failed = False
    try:
        rendered = _render_question(
            template_id=template_id,
            context_json=context_json,
            code=code,
        )
    except (SydneyClarificationError, ValueError):
        rendered = ""
        failed = True
    if failed or not rendered or len(rendered) > _TELEGRAM_TEXT_MAX:
        raise SydneyClarificationError("clarification_question_invalid")
    return rendered


def build_telegram_send_payload(
    *,
    configured_chat_id: str,
    text: str,
    reply_to_message_id: int | None,
) -> dict[str, object]:
    if (
        not _chat_id_valid(configured_chat_id)
        or type(text) is not str
        or not text
        or len(text) > _TELEGRAM_TEXT_MAX
        or (
            reply_to_message_id is not None
            and (
                type(reply_to_message_id) is not int
                or reply_to_message_id <= 0
                or reply_to_message_id > 2**63 - 1
            )
        )
    ):
        raise _dispatch_error("telegram_payload_invalid", TelegramDispatchError)
    payload: dict[str, object] = {"chat_id": configured_chat_id, "text": text}
    if reply_to_message_id is not None:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}
    return payload


@dataclass(frozen=True, slots=True)
class TelegramHTTPResponse:
    status_code: int
    payload: object

    def __repr__(self) -> str:
        return f"TelegramHTTPResponse(status_code={self.status_code!r})"


@dataclass
class TelegramSendCorrelation:
    chat_id: str
    message_id: str


def parse_telegram_send_response(
    *, response: TelegramHTTPResponse, configured_chat_id: str
) -> TelegramSendCorrelation:
    if not isinstance(response, TelegramHTTPResponse) or not _chat_id_valid(
        configured_chat_id
    ):
        raise _dispatch_error(
            "telegram_delivery_uncertain", TelegramDeliveryUncertain
        )
    status = response.status_code
    payload = response.payload
    if type(status) is not int or status < 200 or status >= 300:
        if (
            type(status) is int
            and 400 <= status < 500
            and type(payload) is dict
            and payload.get("ok") is False
            and type(payload.get("error_code")) is int
            and 400 <= payload["error_code"] < 500
        ):
            raise _dispatch_error(
                "telegram_provider_rejected", TelegramProviderRejected
            )
        raise _dispatch_error(
            "telegram_delivery_uncertain", TelegramDeliveryUncertain
        )
    if type(payload) is not dict or payload.get("ok") is not True:
        raise _dispatch_error(
            "telegram_delivery_uncertain", TelegramDeliveryUncertain
        )
    result = payload.get("result")
    if type(result) is not dict:
        raise _dispatch_error(
            "telegram_delivery_uncertain", TelegramDeliveryUncertain
        )
    message_id = result.get("message_id")
    chat = result.get("chat")
    if (
        type(message_id) is not int
        or message_id <= 0
        or type(chat) is not dict
        or type(chat.get("id")) is not int
        or str(chat["id"]) != configured_chat_id
    ):
        raise _dispatch_error(
            "telegram_delivery_uncertain", TelegramDeliveryUncertain
        )
    return TelegramSendCorrelation(
        chat_id=configured_chat_id,
        message_id=str(message_id),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise ValueError("json_constant_invalid")


def _send_telegram_message_impl(
    *, token: str, send_payload: dict[str, object], timeout: float
) -> TelegramHTTPResponse:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=send_payload,
        timeout=timeout,
        stream=True,
        allow_redirects=False,
    )
    try:
        raw_length = response.headers.get("Content-Length")
        if raw_length is not None:
            if not raw_length.isascii() or not raw_length.isdigit():
                raise ValueError("response_length_invalid")
            length = int(raw_length)
            if length > TELEGRAM_RESPONSE_MAX_BYTES:
                raise ValueError("response_length_invalid")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192):
            if type(chunk) is not bytes:
                raise ValueError("response_chunk_invalid")
            total += len(chunk)
            if total > TELEGRAM_RESPONSE_MAX_BYTES:
                raise ValueError("response_length_invalid")
            chunks.append(chunk)
        raw = b"".join(chunks)
        text = raw.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
        if type(payload) is not dict:
            raise ValueError("response_json_invalid")
        return TelegramHTTPResponse(
            status_code=response.status_code,
            payload=payload,
        )
    finally:
        response.close()


def send_telegram_message(
    *,
    bot_token: str,
    payload: dict[str, object],
    socket_timeout_seconds: float,
) -> TelegramHTTPResponse:
    valid = (
        isinstance(bot_token, str)
        and _BOT_TOKEN_RE.fullmatch(bot_token) is not None
        and type(payload) is dict
        and _positive_finite(socket_timeout_seconds)
    )
    token = str(bot_token) if valid else ""
    send_payload = dict(payload) if valid else {}
    timeout = float(socket_timeout_seconds) if valid else 0.0
    bot_token = ""
    payload = {}
    socket_timeout_seconds = 0.0
    if not valid:
        token = ""
        send_payload = {}
        raise _dispatch_error("telegram_payload_invalid", TelegramDispatchError)
    failed = False
    result: TelegramHTTPResponse | None = None
    try:
        result = _send_telegram_message_impl(
            token=token,
            send_payload=send_payload,
            timeout=timeout,
        )
    except BaseException:
        failed = True
    token = ""
    send_payload = {}
    timeout = 0.0
    if failed or result is None:
        raise _dispatch_error(
            "telegram_delivery_uncertain", TelegramDeliveryUncertain
        )
    return result


def _canonical_event(value: dict[str, object]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


class SydneyTelegramDispatcher:
    """Persist-before-send dispatcher with no inbound Telegram authority."""

    def __init__(
        self,
        sessionmaker,
        executor,
        send_message,
        config,
        clock,
    ) -> None:
        if not isinstance(config, SydneyTelegramDispatcherConfig):
            raise _configuration_error()
        self._sessionmaker: async_sessionmaker[AsyncSession] = sessionmaker
        self._executor = executor
        self._send_message: Callable[..., TelegramHTTPResponse] = send_message
        self._config = config
        self._clock: Callable[[], datetime] = clock
        self._active_attempt_ids: set[UUID] = set()

    async def _identity_for_attempt(
        self, session: AsyncSession, attempt_id: UUID
    ) -> tuple[UUID, UUID] | None:
        return (
            await session.execute(
                sa.select(
                    SydneyQuestionOutbox.clarification_id,
                    CRMTaskClarification.suggestion_id,
                )
                .join(
                    CRMTaskClarification,
                    CRMTaskClarification.id
                    == SydneyQuestionOutbox.clarification_id,
                )
                .where(SydneyQuestionOutbox.id == attempt_id)
            )
        ).one_or_none()

    async def dispatch_attempt(self, attempt_id):
        if not self._config.enabled or not isinstance(attempt_id, UUID):
            raise _dispatch_error("telegram_dispatch_disabled", TelegramDispatchError)
        if attempt_id in self._active_attempt_ids:
            raise _dispatch_error("telegram_attempt_stale", TelegramDispatchError)
        self._active_attempt_ids.add(attempt_id)
        try:
            return await self._dispatch_active_attempt(attempt_id)
        finally:
            self._active_attempt_ids.discard(attempt_id)

    async def _dispatch_active_attempt(self, attempt_id: UUID):
        now = self._clock().astimezone(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                identity = await self._identity_for_attempt(session, attempt_id)
                if identity is None:
                    raise _dispatch_error(
                        "telegram_attempt_stale", TelegramDispatchError
                    )
                clarification_id, suggestion_id = identity
                suggestion = await session.scalar(
                    sa.select(CRMTaskSuggestion)
                    .where(CRMTaskSuggestion.id == suggestion_id)
                    .with_for_update()
                )
                clarification = await session.scalar(
                    sa.select(CRMTaskClarification)
                    .where(CRMTaskClarification.id == clarification_id)
                    .with_for_update()
                )
                attempt = await session.scalar(
                    sa.select(SydneyQuestionOutbox)
                    .where(SydneyQuestionOutbox.id == attempt_id)
                    .with_for_update()
                )
                if (
                    suggestion is None
                    or clarification is None
                    or attempt is None
                    or clarification.state != "pending"
                    or attempt.state != "pending"
                    or suggestion.version != clarification.suggestion_version
                    or now >= clarification.slot_deadline_at
                ):
                    raise _dispatch_error(
                        "telegram_attempt_stale", TelegramDispatchError
                    )
                key = self._config.clarification_code_keys.get(
                    clarification.code_key_version
                )
                if key is None:
                    raise _dispatch_error(
                        "telegram_attempt_stale", TelegramDispatchError
                    )
                code = derive_clarification_code(
                    key=key,
                    key_version=clarification.code_key_version,
                    clarification_id=clarification.id,
                    suggestion_id=clarification.suggestion_id,
                    suggestion_version=clarification.suggestion_version,
                    field_name=clarification.field_name,
                    round_number=clarification.round_number,
                )
                text = render_clarification_question(
                    template_id=attempt.template_id,
                    context_json=attempt.question_context_json,
                    code=code,
                )
                if rendered_question_hash(text) != attempt.rendered_payload_hash:
                    raise _dispatch_error(
                        "telegram_attempt_stale", TelegramDispatchError
                    )
                reply_id: int | None = None
                if attempt.reply_to_attempt_id is not None:
                    parent_message_id = await session.scalar(
                        sa.select(SydneyQuestionOutbox.telegram_message_id).where(
                            SydneyQuestionOutbox.id == attempt.reply_to_attempt_id
                        )
                    )
                    if parent_message_id is None:
                        raise _dispatch_error(
                            "telegram_attempt_stale", TelegramDispatchError
                        )
                    reply_id = int(parent_message_id)
                transport_payload = build_telegram_send_payload(
                    configured_chat_id=self._config.brandon_chat_id,
                    text=text,
                    reply_to_message_id=reply_id,
                )
                attempt.state = "sending"
                attempt.attempted_at = now
                attempt.telegram_chat_id = self._config.brandon_chat_id
                attempt.updated_at = now
                if clarification.first_attempt_at is None:
                    clarification.first_attempt_at = now
                    clarification.deadline_anchor_kind = "first_attempt"
                    clarification.deadline_anchored_at = now
                    clarification.slot_deadline_at = now + timedelta(hours=48)
                    clarification.updated_at = now
        outcome = "uncertain"
        correlation: TelegramSendCorrelation | None = None
        try:
            response = await self._executor.run(
                key=f"telegram:{attempt_id}",
                function=lambda: self._send_message(
                    bot_token=self._config.bot_token,
                    payload=transport_payload,
                    socket_timeout_seconds=(
                        self._config.provider_socket_timeout_seconds
                    ),
                ),
                deadline_seconds=self._config.provider_deadline_seconds,
            )
            correlation = parse_telegram_send_response(
                response=response,
                configured_chat_id=self._config.brandon_chat_id,
            )
            outcome = "sent"
        except TelegramProviderRejected:
            outcome = "rejected"
        except BaseException:
            outcome = "uncertain"
        finished_at = self._clock().astimezone(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                identity = await self._identity_for_attempt(session, attempt_id)
                if identity is None:
                    raise _dispatch_error(
                        "telegram_attempt_stale", TelegramDispatchError
                    )
                clarification_id, suggestion_id = identity
                suggestion = await session.scalar(
                    sa.select(CRMTaskSuggestion)
                    .where(CRMTaskSuggestion.id == suggestion_id)
                    .with_for_update()
                )
                clarification = await session.scalar(
                    sa.select(CRMTaskClarification)
                    .where(CRMTaskClarification.id == clarification_id)
                    .with_for_update()
                )
                attempt = await session.scalar(
                    sa.select(SydneyQuestionOutbox)
                    .where(SydneyQuestionOutbox.id == attempt_id)
                    .with_for_update()
                )
                if (
                    suggestion is None
                    or clarification is None
                    or attempt is None
                    or attempt.state != "sending"
                ):
                    raise _dispatch_error(
                        "telegram_attempt_stale", TelegramDispatchError
                    )
                if (
                    clarification.state == "pending"
                    and suggestion.version != clarification.suggestion_version
                ):
                    await supersede_locked_clarification(
                        session=session,
                        suggestion=suggestion,
                        previous_version=clarification.suggestion_version,
                        now=finished_at,
                    )
                if outcome == "sent" and correlation is not None:
                    attempt.state = "sent"
                    attempt.sent_at = finished_at
                    attempt.telegram_message_id = correlation.message_id
                    if (
                        attempt.attempt_kind == "initial"
                        and clarification.state == "pending"
                    ):
                        clarification.deadline_anchor_kind = "initial_sent"
                        clarification.deadline_anchored_at = finished_at
                        clarification.slot_deadline_at = finished_at + timedelta(
                            hours=48
                        )
                elif outcome == "rejected":
                    attempt.state = "failed"
                    attempt.failure_category = "provider_rejected"
                else:
                    attempt.state = "delivery_uncertain"
                    attempt.failure_category = "provider_unknown"
                attempt.updated_at = finished_at
                clarification.updated_at = finished_at
        if outcome == "sent":
            return correlation
        if outcome == "rejected":
            raise _dispatch_error(
                "telegram_provider_rejected", TelegramProviderRejected
            )
        raise _dispatch_error(
            "telegram_delivery_uncertain", TelegramDeliveryUncertain
        )

    async def enqueue_due_reminder(self, clarification_id):
        if not isinstance(clarification_id, UUID):
            return None
        now = self._clock().astimezone(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                suggestion_id = await session.scalar(
                    sa.select(CRMTaskClarification.suggestion_id).where(
                        CRMTaskClarification.id == clarification_id
                    )
                )
                if suggestion_id is None:
                    return None
                suggestion = await session.scalar(
                    sa.select(CRMTaskSuggestion)
                    .where(CRMTaskSuggestion.id == suggestion_id)
                    .with_for_update()
                )
                clarification = await session.scalar(
                    sa.select(CRMTaskClarification)
                    .where(CRMTaskClarification.id == clarification_id)
                    .with_for_update()
                )
                if (
                    suggestion is None
                    or clarification is None
                    or clarification.state != "pending"
                    or suggestion.version != clarification.suggestion_version
                    or now >= clarification.slot_deadline_at
                ):
                    return None
                delivered = await session.scalar(
                    sa.select(SydneyQuestionOutbox)
                    .where(
                        SydneyQuestionOutbox.clarification_id == clarification_id,
                        SydneyQuestionOutbox.attempt_kind.in_(
                            ("initial", "initial_retry")
                        ),
                        sa.or_(
                            SydneyQuestionOutbox.state == "sent",
                            sa.and_(
                                SydneyQuestionOutbox.state
                                == "delivery_uncertain",
                                SydneyQuestionOutbox.reconciled_outcome
                                == "delivered",
                            ),
                        ),
                    )
                    .order_by(
                        sa.func.coalesce(
                            SydneyQuestionOutbox.sent_at,
                            SydneyQuestionOutbox.reconciled_at,
                        ).desc(),
                        SydneyQuestionOutbox.id.desc(),
                    )
                    .limit(1)
                    .with_for_update()
                )
                delivered_at = (
                    delivered.sent_at
                    if delivered is not None and delivered.state == "sent"
                    else (
                        delivered.reconciled_at
                        if delivered is not None
                        and delivered.reconciled_outcome == "delivered"
                        else None
                    )
                )
                if delivered_at is None or now < delivered_at + timedelta(hours=24):
                    return None
                existing = await session.scalar(
                    sa.select(SydneyQuestionOutbox.id).where(
                        SydneyQuestionOutbox.clarification_id == clarification_id,
                        SydneyQuestionOutbox.attempt_kind == "reminder",
                    )
                )
                if existing is not None:
                    return existing
                key = self._config.clarification_code_keys.get(
                    clarification.code_key_version
                )
                if key is None:
                    return None
                code = derive_clarification_code(
                    key=key,
                    key_version=clarification.code_key_version,
                    clarification_id=clarification.id,
                    suggestion_id=clarification.suggestion_id,
                    suggestion_version=clarification.suggestion_version,
                    field_name=clarification.field_name,
                    round_number=clarification.round_number,
                )
                rendered = render_clarification_question(
                    template_id="clarification_reminder_v1",
                    context_json=delivered.question_context_json,
                    code=code,
                )
                reminder = SydneyQuestionOutbox(
                    id=uuid4(),
                    clarification_id=clarification.id,
                    attempt_kind="reminder",
                    attempt_number=1,
                    reply_to_attempt_id=delivered.id,
                    dedupe_key=(
                        f"clarification:{clarification.id}:"
                        f"v{clarification.suggestion_version}:reminder:1"
                    ),
                    template_id="clarification_reminder_v1",
                    question_context_json=delivered.question_context_json,
                    rendered_payload_hash=rendered_question_hash(rendered),
                    state="pending",
                    created_at=now,
                    updated_at=now,
                )
                session.add(reminder)
                await session.flush()
                return reminder.id

    async def release_expired_clarification(self, clarification_id):
        if not isinstance(clarification_id, UUID):
            return False
        now = self._clock().astimezone(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                suggestion_id = await session.scalar(
                    sa.select(CRMTaskClarification.suggestion_id).where(
                        CRMTaskClarification.id == clarification_id
                    )
                )
                if suggestion_id is None:
                    return False
                suggestion = await session.scalar(
                    sa.select(CRMTaskSuggestion)
                    .where(CRMTaskSuggestion.id == suggestion_id)
                    .with_for_update()
                )
                clarification = await session.scalar(
                    sa.select(CRMTaskClarification)
                    .where(CRMTaskClarification.id == clarification_id)
                    .with_for_update()
                )
                if (
                    suggestion is None
                    or clarification is None
                    or clarification.state != "pending"
                    or now < clarification.slot_deadline_at
                ):
                    return False
                clarification.state = "timed_out"
                clarification.resolved_at = now
                clarification.updated_at = now
                suggestion.clarification_state = "timed_out"
                pending = list(
                    (
                        await session.scalars(
                            sa.select(SydneyQuestionOutbox)
                            .where(
                                SydneyQuestionOutbox.clarification_id
                                == clarification.id,
                                SydneyQuestionOutbox.state == "pending",
                            )
                            .with_for_update()
                        )
                    ).all()
                )
                for attempt in pending:
                    attempt.state = "failed"
                    attempt.failure_category = "pre_send_expired"
                    attempt.updated_at = now
                session.add(
                    CRMTaskSuggestionEvent(
                        suggestion_id=suggestion.id,
                        suggestion_version=suggestion.version,
                        event_type="clarification_timed_out",
                        actor_type="system",
                        event_data_json=_canonical_event(
                            {"clarification_id": str(clarification.id)}
                        ),
                        created_at=now,
                    )
                )
                return True

    async def recover_interrupted_attempt(self, attempt_id):
        if not isinstance(attempt_id, UUID) or attempt_id in self._active_attempt_ids:
            return False
        now = self._clock().astimezone(timezone.utc)
        stale_before = now - timedelta(
            seconds=(
                self._config.provider_deadline_seconds
                + TELEGRAM_INTERRUPTED_RECOVERY_MARGIN_SECONDS
            )
        )
        async with self._sessionmaker() as session:
            async with session.begin():
                attempt = await session.scalar(
                    sa.select(SydneyQuestionOutbox)
                    .where(
                        SydneyQuestionOutbox.id == attempt_id,
                        SydneyQuestionOutbox.state == "sending",
                        SydneyQuestionOutbox.attempted_at.is_not(None),
                        SydneyQuestionOutbox.attempted_at < stale_before,
                    )
                    .with_for_update()
                )
                if attempt is None:
                    return False
                attempt.state = "delivery_uncertain"
                attempt.failure_category = "worker_interrupted"
                attempt.updated_at = now
                return True

    async def reconcile_attempt(
        self,
        attempt_id,
        expected_state,
        outcome,
        reason,
        audit_id,
        observed_chat_id,
        observed_message_id,
    ):
        if (
            not isinstance(attempt_id, UUID)
            or expected_state not in {"failed", "delivery_uncertain"}
            or outcome not in {"delivered", "not_delivered"}
            or type(reason) is not str
            or not reason.strip()
            or len(reason) > 500
            or type(audit_id) is not int
            or audit_id <= 0
        ):
            raise _dispatch_error("telegram_reconciliation_invalid", TelegramDispatchError)
        now = self._clock().astimezone(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                attempt = await session.scalar(
                    sa.select(SydneyQuestionOutbox)
                    .where(SydneyQuestionOutbox.id == attempt_id)
                    .with_for_update()
                )
                if (
                    attempt is None
                    or attempt.state != expected_state
                    or attempt.reconciled_outcome is not None
                    or (expected_state == "failed" and outcome != "not_delivered")
                ):
                    raise _dispatch_error(
                        "telegram_reconciliation_stale", TelegramDispatchError
                    )
                if outcome == "delivered":
                    if (
                        observed_chat_id != self._config.brandon_chat_id
                        or type(observed_message_id) is not int
                        or observed_message_id <= 0
                    ):
                        raise _dispatch_error(
                            "telegram_reconciliation_invalid",
                            TelegramDispatchError,
                        )
                    attempt.telegram_chat_id = observed_chat_id
                    attempt.telegram_message_id = str(observed_message_id)
                elif observed_chat_id is not None or observed_message_id is not None:
                    raise _dispatch_error(
                        "telegram_reconciliation_invalid", TelegramDispatchError
                    )
                attempt.reconciled_outcome = outcome
                attempt.reconciliation_reason = reason.strip()
                attempt.reconciliation_audit_id = audit_id
                attempt.reconciled_at = now
                attempt.updated_at = now
                return True

    async def create_initial_retry(self, attempt_id, reason, audit_id):
        if (
            not isinstance(attempt_id, UUID)
            or type(reason) is not str
            or not reason.strip()
            or len(reason) > 500
            or type(audit_id) is not int
            or audit_id <= 0
        ):
            raise _dispatch_error("telegram_retry_invalid", TelegramDispatchError)
        now = self._clock().astimezone(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                identity = await self._identity_for_attempt(session, attempt_id)
                if identity is None:
                    raise _dispatch_error(
                        "telegram_retry_stale", TelegramDispatchError
                    )
                clarification_id, suggestion_id = identity
                suggestion = await session.scalar(
                    sa.select(CRMTaskSuggestion)
                    .where(CRMTaskSuggestion.id == suggestion_id)
                    .with_for_update()
                )
                clarification = await session.scalar(
                    sa.select(CRMTaskClarification)
                    .where(CRMTaskClarification.id == clarification_id)
                    .with_for_update()
                )
                source_attempt = await session.scalar(
                    sa.select(SydneyQuestionOutbox)
                    .where(SydneyQuestionOutbox.id == attempt_id)
                    .with_for_update()
                )
                retries = list(
                    (
                        await session.scalars(
                            sa.select(SydneyQuestionOutbox)
                            .where(
                                SydneyQuestionOutbox.clarification_id
                                == clarification_id,
                                SydneyQuestionOutbox.attempt_kind
                                == "initial_retry",
                            )
                            .order_by(
                                SydneyQuestionOutbox.attempt_number,
                                SydneyQuestionOutbox.id,
                            )
                            .with_for_update()
                        )
                    ).all()
                )
                initial = (
                    source_attempt
                    if source_attempt is not None
                    and source_attempt.attempt_kind == "initial"
                    else await session.scalar(
                        sa.select(SydneyQuestionOutbox)
                        .where(
                            SydneyQuestionOutbox.clarification_id
                            == clarification_id,
                            SydneyQuestionOutbox.attempt_kind == "initial",
                            SydneyQuestionOutbox.attempt_number == 1,
                        )
                        .with_for_update()
                    )
                )
                latest_attempt = retries[-1] if retries else initial
                if (
                    suggestion is None
                    or clarification is None
                    or source_attempt is None
                    or initial is None
                    or latest_attempt is None
                    or source_attempt.id != latest_attempt.id
                    or source_attempt.attempt_kind
                    not in {"initial", "initial_retry"}
                    or (
                        source_attempt.attempt_kind == "initial_retry"
                        and source_attempt.parent_initial_attempt_id
                        != initial.id
                    )
                    or source_attempt.reconciled_outcome != "not_delivered"
                    or clarification.state != "pending"
                    or suggestion.version != clarification.suggestion_version
                    or now >= clarification.slot_deadline_at
                ):
                    raise _dispatch_error(
                        "telegram_retry_stale", TelegramDispatchError
                    )
                retry_number = len(retries) + 1
                retry = SydneyQuestionOutbox(
                    id=uuid4(),
                    clarification_id=clarification.id,
                    attempt_kind="initial_retry",
                    attempt_number=retry_number,
                    parent_initial_attempt_id=initial.id,
                    dedupe_key=(
                        f"clarification:{clarification.id}:"
                        f"v{clarification.suggestion_version}:"
                        f"initial_retry:{retry_number}"
                    ),
                    template_id="clarification_initial_v1",
                    question_context_json=initial.question_context_json,
                    rendered_payload_hash=initial.rendered_payload_hash,
                    state="pending",
                    created_at=now,
                    updated_at=now,
                )
                session.add(retry)
                await session.flush()
                session.add(
                    CRMTaskSuggestionEvent(
                        suggestion_id=suggestion_id,
                        suggestion_version=clarification.suggestion_version,
                        event_type="clarification_delivery_retry",
                        actor_type="command_admin",
                        event_data_json=_canonical_event(
                            {
                                "attempt_id": str(retry.id),
                                "parent_attempt_id": str(source_attempt.id),
                                "reason_sha256": hashlib.sha256(
                                    reason.strip().encode("utf-8")
                                ).hexdigest(),
                            }
                        ),
                        action_audit_id=audit_id,
                        created_at=now,
                    )
                )
                return retry.id
