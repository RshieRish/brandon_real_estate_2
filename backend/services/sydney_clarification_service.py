"""Transactional one-question clarification flow for Sydney task suggestions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.command import CRMContact
from models.gmail_task_intake import CRMTaskSuggestion
from models.sydney_tasks import (
    CRMTaskClarification,
    CRMTaskSuggestionEvent,
    SydneyQuestionOutbox,
    TaskSuggestionApprovalNonce,
)
from services.command_contact_identity import canonical_email
from services.crm_task_suggestion_service import canonical_task_payload_hash
from services.integration_advisory_locks import (
    contact_identity_transaction_lock,
)


_CLARIFICATION_CODE_DOMAIN = b"sws:sydney-task-clarification-code:v1\0"
_CONTACT_OPTION_CODE_DOMAIN = b"sws:sydney-task-contact-option-code:v1\0"
_CONTACT_RESOLUTION_DOMAIN = b"sws:crm-contact-resolution:v1\0"
_BASE64URL_16_RE = re.compile(r"[A-Za-z0-9_-]{22}")
_BASE64URL_32_RE = re.compile(r"[A-Za-z0-9_-]{43}")
_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+")
_BLOCKER_ORDER = (
    "missing_required_field",
    "ambiguous_due_at",
    "ambiguous_contact",
    "multiple_actions",
    "unsupported_owner",
    "unsupported_link",
)
_ASKABLE_FIELDS = (
    "action_scope",
    "contact",
    "due_at",
    "owner",
    "task_details",
)

# These public masks freeze the v1 wire encoding independently of later framing
# changes. XOR is a bijection over the truncated HMAC output and does not reduce
# its 128-bit unpredictability.
_CLARIFICATION_CODE_V1_MASK = bytes.fromhex("dc288b24e02a783e48fd63c9126cd60c")
_CONTACT_OPTION_CODE_V1_MASK = bytes.fromhex("090e6f01fe73619fc7bf620c9ba6aeae")


class SydneyClarificationError(RuntimeError):
    """A fixed, content-free clarification boundary failure."""


def _fixed_error(category: str) -> SydneyClarificationError:
    error = SydneyClarificationError(category)
    error.__cause__ = None
    error.__context__ = None
    return error


def _require_aware(value: datetime, *, category: str = "invalid_time") -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise _fixed_error(category)
    return value


def _validate_code_key(key: object) -> bytes:
    if type(key) is not bytes or len(key) != 32:
        raise _fixed_error("clarification_code_key_invalid")
    return key


def _xor_bytes(value: bytes, mask: bytes) -> bytes:
    return bytes(left ^ right for left, right in zip(value, mask, strict=True))


def _encode_16(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def derive_clarification_code(
    *,
    key: bytes,
    key_version: int,
    clarification_id: UUID,
    suggestion_id: UUID,
    suggestion_version: int,
    field_name: str,
    round_number: int,
) -> str:
    """Derive the restart-safe v1 opaque code from immutable row identity."""
    checked_key = _validate_code_key(key)
    if (
        type(key_version) is not int
        or not 1 <= key_version <= 32767
        or not isinstance(clarification_id, UUID)
        or not isinstance(suggestion_id, UUID)
        or type(suggestion_version) is not int
        or not 1 <= suggestion_version <= 2**31 - 1
        or field_name not in _ASKABLE_FIELDS
        or type(round_number) is not int
        or not 1 <= round_number <= 5
    ):
        raise _fixed_error("clarification_code_identity_invalid")
    field_bytes = field_name.encode("ascii")
    material = (
        _CLARIFICATION_CODE_DOMAIN
        + key_version.to_bytes(2, "big")
        + clarification_id.bytes
        + suggestion_id.bytes
        + suggestion_version.to_bytes(4, "big")
        + len(field_bytes).to_bytes(2, "big")
        + field_bytes
        + round_number.to_bytes(2, "big")
    )
    digest = hmac.new(checked_key, material, hashlib.sha256).digest()[:16]
    return _encode_16(_xor_bytes(digest, _CLARIFICATION_CODE_V1_MASK))


def _parse_base64url(
    value: object,
    *,
    pattern: re.Pattern[str],
    decoded_size: int,
    category: str,
) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise _fixed_error(category)
    try:
        raw = base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))
        canonical = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    except (UnicodeEncodeError, ValueError):
        raise _fixed_error(category) from None
    if len(raw) != decoded_size or canonical != value:
        raise _fixed_error(category)
    return value


def parse_clarification_code(value: object) -> str:
    return _parse_base64url(
        value,
        pattern=_BASE64URL_16_RE,
        decoded_size=16,
        category="invalid_clarification_code",
    )


def clarification_code_hash(code: object) -> bytes:
    canonical = parse_clarification_code(code)
    return hashlib.sha256(canonical.encode("ascii")).digest()


def derive_contact_option_code(
    *,
    key: bytes,
    key_version: int,
    clarification_id: UUID,
    contact_id: int,
    email: str,
) -> str:
    checked_key = _validate_code_key(key)
    normalized_email = canonical_email(email)
    if (
        type(key_version) is not int
        or not 1 <= key_version <= 32767
        or not isinstance(clarification_id, UUID)
        or type(contact_id) is not int
        or contact_id <= 0
        or normalized_email is None
    ):
        raise _fixed_error("contact_option_identity_invalid")
    email_bytes = normalized_email.encode("utf-8")
    material = (
        _CONTACT_OPTION_CODE_DOMAIN
        + key_version.to_bytes(2, "big")
        + clarification_id.bytes
        + contact_id.to_bytes(8, "big")
        + len(email_bytes).to_bytes(2, "big")
        + email_bytes
    )
    digest = hmac.new(checked_key, material, hashlib.sha256).digest()[:16]
    return _encode_16(_xor_bytes(digest, _CONTACT_OPTION_CODE_V1_MASK))


def contact_option_code_hash(code: object) -> bytes:
    canonical = _parse_base64url(
        code,
        pattern=_BASE64URL_16_RE,
        decoded_size=16,
        category="invalid_contact_option_code",
    )
    return hashlib.sha256(canonical.encode("ascii")).digest()


def generate_approval_token() -> str:
    token = secrets.token_urlsafe(32)
    return parse_approval_token(token)


def parse_approval_token(value: object) -> str:
    return _parse_base64url(
        value,
        pattern=_BASE64URL_32_RE,
        decoded_size=32,
        category="invalid_approval_nonce",
    )


def approval_token_hash(token: object) -> bytes:
    canonical = parse_approval_token(token)
    return hashlib.sha256(canonical.encode("ascii")).digest()


def build_handoff_link(*, suggestion_id: UUID, token: str) -> str:
    if not isinstance(suggestion_id, UUID):
        raise _fixed_error("invalid_suggestion_id")
    canonical = parse_approval_token(token)
    return (
        f"/admin/command/task-suggestions?suggestion={suggestion_id}"
        f"#handoff={canonical}"
    )


def contact_resolution_hash(*, contact_id: int, email: str) -> str:
    normalized_email = canonical_email(email)
    if type(contact_id) is not int or contact_id <= 0 or normalized_email is None:
        raise _fixed_error("contact_resolution_identity_invalid")
    material = (
        _CONTACT_RESOLUTION_DOMAIN
        + str(contact_id).encode("ascii")
        + b"\0"
        + normalized_email.encode("utf-8")
    )
    return hashlib.sha256(material).hexdigest()


_BIDI_AND_ISOLATE = frozenset(
    {
        "\u061c",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }
)


def _has_unsafe_character(value: str, *, multiline: bool) -> bool:
    for character in value:
        codepoint = ord(character)
        if character in _BIDI_AND_ISOLATE or 0xD800 <= codepoint <= 0xDFFF:
            return True
        if character == "\n" and multiline:
            continue
        if character in {"\u2028", "\u2029"} and multiline:
            continue
        if codepoint < 32 or codepoint == 127 or character in {"\u2028", "\u2029"}:
            return True
    return False


def _single_line(value: object, *, maximum: int) -> str:
    if type(value) is not str:
        raise ValueError("text_invalid")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if (
        not normalized
        or len(normalized) > maximum
        or _has_unsafe_character(normalized, multiline=False)
    ):
        raise ValueError("text_invalid")
    return normalized


def _multiline(value: object, *, maximum: int) -> str:
    if type(value) is not str:
        raise ValueError("text_invalid")
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u2028", "\n").replace("\u2029", "\n")
    normalized = normalized.strip()
    if len(normalized) > maximum or _has_unsafe_character(normalized, multiline=True):
        raise ValueError("text_invalid")
    return normalized


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ClarificationQuestionContext(_StrictModel):
    question: str
    party_label: str
    subject_preview: str
    task_title: str

    @field_validator("question", "party_label", "subject_preview", "task_title")
    @classmethod
    def _validate_context_text(cls, value: str) -> str:
        normalized = _single_line(value, maximum=500)
        folded = normalized.casefold()
        if "reference code:" in folded or _BASE64URL_16_RE.search(normalized):
            raise ValueError("question_context_contains_code_material")
        return normalized

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )


def render_clarification_question(
    *, template_id: str, context_json: str, code: str
) -> str:
    if template_id not in {
        "clarification_initial_v1",
        "clarification_reminder_v1",
    }:
        raise _fixed_error("clarification_template_invalid")
    canonical_code = parse_clarification_code(code)
    try:
        context = ClarificationQuestionContext.model_validate_json(context_json)
    except (ValidationError, ValueError):
        raise _fixed_error("clarification_question_context_invalid") from None
    base = (
        f"{context.question}\n\n"
        f"{context.party_label} | {context.subject_preview}\n"
        f"Proposed task: {context.task_title}\n"
        f"Reference code: {canonical_code}"
    )
    return "Reminder: " + base if template_id == "clarification_reminder_v1" else base


def rendered_question_hash(rendered: str) -> str:
    if type(rendered) is not str or not rendered:
        raise _fixed_error("clarification_render_invalid")
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


class ActionScopeSingleTask(_StrictModel):
    kind: Literal["action_scope"]
    decision: Literal["single_task"]
    title: str
    description: str
    priority: Literal["low", "normal", "high"]

    _title = field_validator("title")(lambda value: _single_line(value, maximum=255))
    _description = field_validator("description")(
        lambda value: _multiline(value, maximum=5000)
    )


class ActionScopeSeparateTasks(_StrictModel):
    kind: Literal["action_scope"]
    decision: Literal["separate_tasks"]


class ContactSelectOption(_StrictModel):
    kind: Literal["contact"]
    decision: Literal["select_option"]
    option_code: str

    @field_validator("option_code")
    @classmethod
    def _option_code(cls, value: str) -> str:
        return _parse_base64url(
            value,
            pattern=_BASE64URL_16_RE,
            decoded_size=16,
            category="invalid_contact_option_code",
        )


class ContactExactEmail(_StrictModel):
    kind: Literal["contact"]
    decision: Literal["exact_email"]
    email: str

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        normalized = canonical_email(value)
        if normalized is None or _EMAIL_RE.fullmatch(normalized) is None:
            raise ValueError("email_invalid")
        return normalized


class ContactNoContact(_StrictModel):
    kind: Literal["contact"]
    decision: Literal["no_contact"]


class DueSet(_StrictModel):
    kind: Literal["due_at"]
    decision: Literal["set_due"]
    due_at: str
    timezone_basis: str

    @field_validator("due_at")
    @classmethod
    def _due_at(cls, value: str) -> str:
        if type(value) is not str:
            raise ValueError("due_at_invalid")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("due_at_invalid") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("due_at_invalid")
        return value

    @field_validator("timezone_basis")
    @classmethod
    def _timezone_basis(cls, value: str) -> str:
        if type(value) is not str or not value or len(value) > 64:
            raise ValueError("timezone_basis_invalid")
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("timezone_basis_invalid") from None
        return value

    @model_validator(mode="after")
    def _offset_matches_timezone_basis(self) -> DueSet:
        parsed = datetime.fromisoformat(self.due_at)
        basis = ZoneInfo(self.timezone_basis)
        if parsed.utcoffset() != parsed.astimezone(basis).utcoffset():
            raise ValueError("due_at_timezone_basis_mismatch")
        return self


class DueNone(_StrictModel):
    kind: Literal["due_at"]
    decision: Literal["no_due_date"]


class OwnerBrandon(_StrictModel):
    kind: Literal["owner"]
    decision: Literal["brandon"]


class OwnerOther(_StrictModel):
    kind: Literal["owner"]
    decision: Literal["other"]


class TaskDetailsReplace(_StrictModel):
    kind: Literal["task_details"]
    decision: Literal["replace"]
    title: str
    description: str
    priority: Literal["low", "normal", "high"]

    _title = field_validator("title")(lambda value: _single_line(value, maximum=255))
    _description = field_validator("description")(
        lambda value: _multiline(value, maximum=5000)
    )


class TaskDetailsConfirm(_StrictModel):
    kind: Literal["task_details"]
    decision: Literal["confirm_current"]


ClarificationAnswer = (
    ActionScopeSingleTask
    | ActionScopeSeparateTasks
    | ContactSelectOption
    | ContactExactEmail
    | ContactNoContact
    | DueSet
    | DueNone
    | OwnerBrandon
    | OwnerOther
    | TaskDetailsReplace
    | TaskDetailsConfirm
)

_ANSWER_TYPES: dict[tuple[str, str], type[_StrictModel]] = {
    ("action_scope", "single_task"): ActionScopeSingleTask,
    ("action_scope", "separate_tasks"): ActionScopeSeparateTasks,
    ("contact", "select_option"): ContactSelectOption,
    ("contact", "exact_email"): ContactExactEmail,
    ("contact", "no_contact"): ContactNoContact,
    ("due_at", "set_due"): DueSet,
    ("due_at", "no_due_date"): DueNone,
    ("owner", "brandon"): OwnerBrandon,
    ("owner", "other"): OwnerOther,
    ("task_details", "replace"): TaskDetailsReplace,
    ("task_details", "confirm_current"): TaskDetailsConfirm,
}


def parse_clarification_answer(value: object) -> ClarificationAnswer:
    if type(value) is not dict:
        raise _fixed_error("invalid_clarification_answer")
    kind = value.get("kind")
    decision = value.get("decision")
    if type(kind) is not str or type(decision) is not str:
        raise _fixed_error("invalid_clarification_answer")
    model = _ANSWER_TYPES.get((kind, decision))
    if model is None:
        raise _fixed_error("invalid_clarification_answer")
    try:
        parsed = model.model_validate(value)
    except (ValidationError, ValueError):
        parsed = None
    if parsed is None:
        raise _fixed_error("invalid_clarification_answer")
    return parsed


def select_clarification_field(
    *,
    blocker_codes: tuple[str, ...] | list[str],
    owner_clarification_pending: bool,
    task_details_clarification_pending: bool,
    answered_fields: frozenset[str],
) -> str | None:
    blockers = frozenset(blocker_codes)
    candidates = (
        ("action_scope", "multiple_actions" in blockers),
        ("contact", "ambiguous_contact" in blockers),
        ("due_at", "ambiguous_due_at" in blockers),
        ("owner", owner_clarification_pending),
        ("task_details", task_details_clarification_pending),
    )
    return next(
        (
            field_name
            for field_name, required in candidates
            if required and field_name not in answered_fields
        ),
        None,
    )


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    created: bool
    clarification_id: UUID | None
    outbox_id: UUID | None
    field_name: str | None
    round_number: int | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AnswerResult:
    suggestion_id: UUID
    suggestion_version: int
    next_clarification_id: UUID | None
    handoff_link: str | None


def _canonical_json(value: dict[str, object]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _ordered_blockers(values: set[str] | list[str]) -> list[str]:
    selected = set(values)
    return [blocker for blocker in _BLOCKER_ORDER if blocker in selected]


def _question_for(field_name: str) -> str:
    return {
        "action_scope": "Should this be one task or separate tasks?",
        "contact": "Which CRM contact should this task use?",
        "due_at": "When should this task be due?",
        "owner": "Should this be Brandon's follow-up task?",
        "task_details": "Should I keep the proposed task details or replace them?",
    }[field_name]


async def supersede_locked_clarification(
    *,
    session: AsyncSession,
    suggestion: CRMTaskSuggestion,
    previous_version: int,
    now: datetime,
) -> bool:
    """Supersede an old-version question while the suggestion row is locked."""
    _require_aware(now)
    clarification = await session.scalar(
        sa.select(CRMTaskClarification)
        .where(
            CRMTaskClarification.suggestion_id == suggestion.id,
            CRMTaskClarification.suggestion_version == previous_version,
            CRMTaskClarification.state == "pending",
        )
        .with_for_update()
    )
    if clarification is None:
        return False
    clarification.state = "superseded"
    clarification.resolved_at = now
    clarification.updated_at = now
    await session.flush()
    pending_attempts = list(
        (
            await session.scalars(
                sa.select(SydneyQuestionOutbox)
                .where(
                    SydneyQuestionOutbox.clarification_id == clarification.id,
                    SydneyQuestionOutbox.state == "pending",
                )
                .with_for_update()
            )
        ).all()
    )
    for attempt in pending_attempts:
        attempt.state = "failed"
        attempt.failure_category = "pre_send_superseded"
        attempt.updated_at = now
    session.add(
        CRMTaskSuggestionEvent(
            suggestion_id=suggestion.id,
            suggestion_version=suggestion.version,
            event_type="clarification_superseded",
            actor_type="system",
            event_data_json=_canonical_json(
                {
                    "clarification_id": str(clarification.id),
                    "new_version": suggestion.version,
                    "old_version": previous_version,
                }
            ),
            created_at=now,
        )
    )
    return True


class SydneyClarificationService:
    """Serialize clarification edits while never creating confirmed CRM tasks."""

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        brandon_chat_id: str,
        clarification_code_keys: dict[int, bytes],
        active_code_key_version: int,
    ) -> None:
        if (
            type(brandon_chat_id) is not str
            or re.fullmatch(r"-?[1-9][0-9]*", brandon_chat_id) is None
        ):
            raise _fixed_error("clarification_chat_id_invalid")
        if active_code_key_version not in clarification_code_keys:
            raise _fixed_error("clarification_code_key_missing")
        checked_keys: dict[int, bytes] = {}
        for version, key in clarification_code_keys.items():
            if type(version) is not int or not 1 <= version <= 32767:
                raise _fixed_error("clarification_code_key_invalid")
            checked_keys[version] = _validate_code_key(key)
        self._sessionmaker = sessionmaker
        self._brandon_chat_id = brandon_chat_id
        self._code_keys = checked_keys
        self._active_code_key_version = active_code_key_version

    def __repr__(self) -> str:
        return (
            "SydneyClarificationService("
            f"brandon_chat_id={self._brandon_chat_id!r}, "
            f"active_code_key_version={self._active_code_key_version}, "
            f"configured_key_versions={tuple(sorted(self._code_keys))!r})"
        )

    async def _answered_fields(
        self,
        session: AsyncSession,
        suggestion_id: UUID,
        suggestion_version: int,
    ) -> frozenset[str]:
        fields = await session.scalars(
            sa.select(CRMTaskClarification.field_name).where(
                CRMTaskClarification.suggestion_id == suggestion_id,
                CRMTaskClarification.suggestion_version == suggestion_version,
                CRMTaskClarification.state == "answered",
            )
        )
        return frozenset(fields.all())

    async def _initial_outbox(
        self, session: AsyncSession, clarification_id: UUID
    ) -> SydneyQuestionOutbox | None:
        return await session.scalar(
            sa.select(SydneyQuestionOutbox).where(
                SydneyQuestionOutbox.clarification_id == clarification_id,
                SydneyQuestionOutbox.attempt_kind == "initial",
                SydneyQuestionOutbox.attempt_number == 1,
            )
        )

    async def _create_locked(
        self,
        *,
        session: AsyncSession,
        suggestion: CRMTaskSuggestion,
        party_label: str,
        subject_preview: str,
        now: datetime,
    ) -> EnqueueResult:
        active = await session.scalar(
            sa.select(CRMTaskClarification)
            .where(
                CRMTaskClarification.suggestion_id == suggestion.id,
                CRMTaskClarification.state == "pending",
            )
            .with_for_update()
        )
        if active is not None:
            outbox = await self._initial_outbox(session, active.id)
            return EnqueueResult(
                created=False,
                clarification_id=active.id,
                outbox_id=outbox.id if outbox else None,
                field_name=active.field_name,
                round_number=active.round_number,
            )
        chat_owner = await session.scalar(
            sa.select(CRMTaskClarification.id)
            .where(
                CRMTaskClarification.telegram_chat_id == self._brandon_chat_id,
                CRMTaskClarification.state == "pending",
            )
            .with_for_update()
        )
        if chat_owner is not None:
            return EnqueueResult(
                created=False,
                clarification_id=None,
                outbox_id=None,
                field_name=None,
                round_number=None,
                reason="clarification_chat_busy",
            )
        answered = await self._answered_fields(
            session,
            suggestion.id,
            suggestion.version,
        )
        field_name = select_clarification_field(
            blocker_codes=suggestion.blocker_codes,
            owner_clarification_pending=suggestion.owner_clarification_pending,
            task_details_clarification_pending=(
                suggestion.task_details_clarification_pending
            ),
            answered_fields=answered,
        )
        round_number = (
            int(
                await session.scalar(
                    sa.select(sa.func.count(CRMTaskClarification.id)).where(
                        CRMTaskClarification.suggestion_id == suggestion.id
                    )
                )
                or 0
            )
            + 1
        )
        if field_name is None:
            return EnqueueResult(
                created=False,
                clarification_id=None,
                outbox_id=None,
                field_name=None,
                round_number=None,
                reason="clarification_not_required",
            )
        if round_number > 5:
            suggestion.state = "needs_clarification"
            suggestion.clarification_state = "manual_review_required"
            await session.flush()
            return EnqueueResult(
                created=False,
                clarification_id=None,
                outbox_id=None,
                field_name=None,
                round_number=None,
                reason="clarification_round_limit",
            )
        clarification_id = uuid4()
        key_version = self._active_code_key_version
        code = derive_clarification_code(
            key=self._code_keys[key_version],
            key_version=key_version,
            clarification_id=clarification_id,
            suggestion_id=suggestion.id,
            suggestion_version=suggestion.version,
            field_name=field_name,
            round_number=round_number,
        )
        context = ClarificationQuestionContext(
            question=_question_for(field_name),
            party_label=party_label,
            subject_preview=subject_preview,
            task_title=suggestion.title,
        )
        context_json = context.canonical_json()
        rendered = render_clarification_question(
            template_id="clarification_initial_v1",
            context_json=context_json,
            code=code,
        )
        clarification = CRMTaskClarification(
            id=clarification_id,
            suggestion_id=suggestion.id,
            suggestion_version=suggestion.version,
            field_name=field_name,
            round_number=round_number,
            telegram_chat_id=self._brandon_chat_id,
            code_hash=clarification_code_hash(code),
            code_key_version=key_version,
            options_json="{}",
            state="pending",
            deadline_anchor_kind="created",
            deadline_anchored_at=now,
            slot_deadline_at=now + timedelta(hours=48),
            created_at=now,
            updated_at=now,
        )
        outbox = SydneyQuestionOutbox(
            id=uuid4(),
            clarification_id=clarification_id,
            attempt_kind="initial",
            attempt_number=1,
            dedupe_key=(
                f"clarification:{clarification_id}:v{suggestion.version}:initial:1"
            ),
            template_id="clarification_initial_v1",
            question_context_json=context_json,
            rendered_payload_hash=rendered_question_hash(rendered),
            state="pending",
            created_at=now,
            updated_at=now,
        )
        session.add_all(
            (
                clarification,
                outbox,
                CRMTaskSuggestionEvent(
                    suggestion_id=suggestion.id,
                    suggestion_version=suggestion.version,
                    event_type="clarification_asked",
                    actor_type="sydney",
                    event_data_json=_canonical_json(
                        {
                            "clarification_id": str(clarification_id),
                            "field_name": field_name,
                            "round_number": round_number,
                        }
                    ),
                    created_at=now,
                ),
            )
        )
        suggestion.state = "needs_clarification"
        suggestion.clarification_state = "pending"
        await session.flush()
        return EnqueueResult(
            created=True,
            clarification_id=clarification.id,
            outbox_id=outbox.id,
            field_name=field_name,
            round_number=round_number,
        )

    async def enqueue_next(
        self,
        *,
        suggestion_id: UUID,
        party_label: str,
        subject_preview: str,
        now: datetime,
    ) -> EnqueueResult:
        _require_aware(now)
        if not isinstance(suggestion_id, UUID):
            raise _fixed_error("suggestion_not_found")
        try:
            context = ClarificationQuestionContext(
                question="Context validation",
                party_label=party_label,
                subject_preview=subject_preview,
                task_title="Context validation",
            )
        except ValidationError:
            raise _fixed_error("clarification_question_context_invalid") from None
        async with self._sessionmaker() as session:
            async with session.begin():
                suggestion = await session.scalar(
                    sa.select(CRMTaskSuggestion)
                    .where(CRMTaskSuggestion.id == suggestion_id)
                    .with_for_update()
                )
                if suggestion is None:
                    raise _fixed_error("suggestion_not_found")
                if suggestion.state not in {
                    "needs_clarification",
                    "possible_duplicate",
                }:
                    return EnqueueResult(
                        created=False,
                        clarification_id=None,
                        outbox_id=None,
                        field_name=None,
                        round_number=None,
                        reason="clarification_not_required",
                    )
                try:
                    return await self._create_locked(
                        session=session,
                        suggestion=suggestion,
                        party_label=context.party_label,
                        subject_preview=context.subject_preview,
                        now=now,
                    )
                except IntegrityError:
                    raise _fixed_error("clarification_chat_busy") from None

    async def _cancel_pending_outbox(
        self,
        *,
        session: AsyncSession,
        clarification_id: UUID,
        category: str,
        now: datetime,
    ) -> None:
        rows = list(
            (
                await session.scalars(
                    sa.select(SydneyQuestionOutbox)
                    .where(
                        SydneyQuestionOutbox.clarification_id == clarification_id,
                        SydneyQuestionOutbox.state == "pending",
                    )
                    .with_for_update()
                )
            ).all()
        )
        for row in rows:
            row.state = "failed"
            row.failure_category = category
            row.updated_at = now

    async def _has_delivery(
        self, *, session: AsyncSession, clarification_id: UUID
    ) -> bool:
        return bool(
            await session.scalar(
                sa.select(sa.literal(True))
                .select_from(SydneyQuestionOutbox)
                .where(
                    SydneyQuestionOutbox.clarification_id == clarification_id,
                    SydneyQuestionOutbox.attempt_kind.in_(("initial", "initial_retry")),
                    SydneyQuestionOutbox.telegram_chat_id == self._brandon_chat_id,
                    SydneyQuestionOutbox.telegram_message_id.is_not(None),
                    sa.or_(
                        SydneyQuestionOutbox.state == "sent",
                        sa.and_(
                            SydneyQuestionOutbox.state == "delivery_uncertain",
                            SydneyQuestionOutbox.reconciled_outcome == "delivered",
                        ),
                    ),
                )
                .limit(1)
            )
        )

    async def _apply_contact_answer(
        self,
        *,
        session: AsyncSession,
        suggestion: CRMTaskSuggestion,
        clarification: CRMTaskClarification,
        answer: ContactSelectOption | ContactExactEmail | ContactNoContact,
    ) -> None:
        if isinstance(answer, ContactNoContact):
            suggestion.contact_id = None
            suggestion.contact_resolution_state = "explicit_none"
            suggestion.contact_resolution_hash = None
            return
        options = json.loads(clarification.options_json)
        if isinstance(answer, ContactSelectOption):
            matches = [
                option
                for option in options.get("options", [])
                if hmac.compare_digest(
                    str(option.get("option_code", "")), answer.option_code
                )
            ]
            if len(matches) != 1:
                raise _fixed_error("stale_clarification")
            selected_email = canonical_email(matches[0].get("email"))
            selected_id = matches[0].get("contact_id")
        else:
            if options.get("options"):
                raise _fixed_error("stale_clarification")
            selected_email = answer.email
            selected_id = None
        if selected_email is None:
            raise _fixed_error("stale_clarification")
        await contact_identity_transaction_lock(await session.connection())
        query = (
            sa.select(CRMContact)
            .where(CRMContact.normalized_email == selected_email)
            .order_by(CRMContact.id)
            .limit(2)
            .with_for_update()
        )
        contacts = list((await session.scalars(query)).all())
        if len(contacts) != 1 or (
            selected_id is not None and contacts[0].id != selected_id
        ):
            raise _fixed_error("stale_clarification")
        contact = contacts[0]
        if canonical_email(contact.email) != selected_email:
            raise _fixed_error("stale_clarification")
        suggestion.contact_id = contact.id
        suggestion.contact_resolution_state = "clarified_unique"
        suggestion.contact_resolution_hash = contact_resolution_hash(
            contact_id=contact.id,
            email=selected_email,
        )

    async def _issue_handoff(
        self,
        *,
        session: AsyncSession,
        suggestion: CRMTaskSuggestion,
        now: datetime,
    ) -> tuple[str, TaskSuggestionApprovalNonce]:
        for _attempt in range(3):
            token = generate_approval_token()
            nonce = TaskSuggestionApprovalNonce(
                id=uuid4(),
                suggestion_id=suggestion.id,
                suggestion_version=suggestion.version,
                payload_hash=suggestion.payload_hash,
                kind="handoff",
                issuance_path="approval_link",
                token_hash=approval_token_hash(token),
                issued_at=now,
                expires_at=now + timedelta(minutes=15),
            )
            try:
                async with session.begin_nested():
                    session.add(nonce)
                    await session.flush()
            except IntegrityError:
                continue
            return build_handoff_link(suggestion_id=suggestion.id, token=token), nonce
        raise _fixed_error("approval_nonce_collision")

    async def answer(
        self,
        *,
        code: object,
        expected_suggestion_version: int,
        answer: object,
        now: datetime,
    ) -> AnswerResult:
        _require_aware(now)
        canonical_code = parse_clarification_code(code)
        parsed_answer = parse_clarification_answer(answer)
        if (
            type(expected_suggestion_version) is not int
            or expected_suggestion_version < 1
        ):
            raise _fixed_error("stale_clarification")
        code_digest = clarification_code_hash(canonical_code)
        async with self._sessionmaker() as session:
            async with session.begin():
                identity = await session.execute(
                    sa.select(
                        CRMTaskClarification.id,
                        CRMTaskClarification.suggestion_id,
                    ).where(CRMTaskClarification.code_hash == code_digest)
                )
                identity_row = identity.one_or_none()
                if identity_row is None:
                    raise _fixed_error("stale_clarification")
                suggestion = await session.scalar(
                    sa.select(CRMTaskSuggestion)
                    .where(CRMTaskSuggestion.id == identity_row.suggestion_id)
                    .with_for_update()
                )
                clarification = await session.scalar(
                    sa.select(CRMTaskClarification)
                    .where(CRMTaskClarification.id == identity_row.id)
                    .with_for_update()
                )
                if suggestion is None or clarification is None:
                    raise _fixed_error("stale_clarification")
                key = self._code_keys.get(clarification.code_key_version)
                if key is None:
                    raise _fixed_error("stale_clarification")
                derived = derive_clarification_code(
                    key=key,
                    key_version=clarification.code_key_version,
                    clarification_id=clarification.id,
                    suggestion_id=clarification.suggestion_id,
                    suggestion_version=clarification.suggestion_version,
                    field_name=clarification.field_name,
                    round_number=clarification.round_number,
                )
                if (
                    clarification.state != "pending"
                    or clarification.suggestion_version != expected_suggestion_version
                    or suggestion.version != expected_suggestion_version
                    or parsed_answer.kind != clarification.field_name
                    or now >= clarification.slot_deadline_at
                    or not hmac.compare_digest(derived, canonical_code)
                    or not await self._has_delivery(
                        session=session,
                        clarification_id=clarification.id,
                    )
                ):
                    raise _fixed_error("stale_clarification")
                old_version = suggestion.version
                old_payload_hash = suggestion.payload_hash
                old_blockers = list(suggestion.blocker_codes)
                blockers = set(old_blockers)
                force_manual = False
                if isinstance(parsed_answer, ActionScopeSingleTask):
                    suggestion.title = parsed_answer.title
                    suggestion.description = parsed_answer.description
                    suggestion.priority = parsed_answer.priority
                    blockers.discard("multiple_actions")
                elif isinstance(parsed_answer, ActionScopeSeparateTasks):
                    force_manual = True
                elif isinstance(
                    parsed_answer,
                    (ContactSelectOption, ContactExactEmail, ContactNoContact),
                ):
                    await self._apply_contact_answer(
                        session=session,
                        suggestion=suggestion,
                        clarification=clarification,
                        answer=parsed_answer,
                    )
                    blockers.discard("ambiguous_contact")
                elif isinstance(parsed_answer, DueSet):
                    suggestion.due_at = datetime.fromisoformat(
                        parsed_answer.due_at
                    ).astimezone(timezone.utc)
                    blockers.discard("ambiguous_due_at")
                elif isinstance(parsed_answer, DueNone):
                    suggestion.due_at = None
                    blockers.discard("ambiguous_due_at")
                elif isinstance(parsed_answer, (OwnerBrandon, OwnerOther)):
                    suggestion.owner_clarification_pending = False
                    if isinstance(parsed_answer, OwnerOther):
                        blockers.add("unsupported_owner")
                elif isinstance(parsed_answer, TaskDetailsReplace):
                    suggestion.title = parsed_answer.title
                    suggestion.description = parsed_answer.description
                    suggestion.priority = parsed_answer.priority
                    suggestion.task_details_clarification_pending = False
                elif isinstance(parsed_answer, TaskDetailsConfirm):
                    suggestion.task_details_clarification_pending = False
                if not (
                    suggestion.owner_clarification_pending
                    or suggestion.task_details_clarification_pending
                ):
                    blockers.discard("missing_required_field")
                suggestion.blocker_codes = _ordered_blockers(blockers)
                suggestion.version += 1
                suggestion.payload_hash = canonical_task_payload_hash(
                    title=suggestion.title,
                    description=suggestion.description,
                    priority=suggestion.priority,
                    due_at=suggestion.due_at,
                    contact_id=suggestion.contact_id,
                    status=suggestion.task_status,
                )
                clarification.state = "answered"
                clarification.answer_json = _canonical_json(
                    parsed_answer.model_dump(mode="json")
                )
                clarification.resolved_at = now
                clarification.updated_at = now
                await session.flush()
                await self._cancel_pending_outbox(
                    session=session,
                    clarification_id=clarification.id,
                    category="pre_send_resolved",
                    now=now,
                )
                session.add(
                    CRMTaskSuggestionEvent(
                        suggestion_id=suggestion.id,
                        suggestion_version=suggestion.version,
                        event_type="clarification_answered",
                        actor_type="untrusted_hermes_input",
                        event_data_json=_canonical_json(
                            {
                                "clarification_id": str(clarification.id),
                                "field_name": clarification.field_name,
                                "new_blocker_codes": suggestion.blocker_codes,
                                "new_payload_hash": suggestion.payload_hash,
                                "new_version": suggestion.version,
                                "old_blocker_codes": old_blockers,
                                "old_payload_hash": old_payload_hash,
                                "old_version": old_version,
                            }
                        ),
                        created_at=now,
                    )
                )
                initial = await self._initial_outbox(session, clarification.id)
                if initial is None:
                    raise _fixed_error("stale_clarification")
                context = ClarificationQuestionContext.model_validate_json(
                    initial.question_context_json
                )
                answered_fields = await self._answered_fields(
                    session,
                    suggestion.id,
                    suggestion.version,
                )
                next_field = select_clarification_field(
                    blocker_codes=suggestion.blocker_codes,
                    owner_clarification_pending=(
                        suggestion.owner_clarification_pending
                    ),
                    task_details_clarification_pending=(
                        suggestion.task_details_clarification_pending
                    ),
                    answered_fields=answered_fields,
                )
                next_clarification_id: UUID | None = None
                handoff_link: str | None = None
                if force_manual or (
                    next_field is not None and clarification.round_number >= 5
                ):
                    suggestion.state = "needs_clarification"
                    suggestion.clarification_state = "manual_review_required"
                elif next_field is not None:
                    suggestion.state = "needs_clarification"
                    suggestion.clarification_state = "pending"
                    queued = await self._create_locked(
                        session=session,
                        suggestion=suggestion,
                        party_label=context.party_label,
                        subject_preview=context.subject_preview,
                        now=now,
                    )
                    next_clarification_id = queued.clarification_id
                elif (
                    suggestion.blocker_codes or suggestion.state == "possible_duplicate"
                ):
                    suggestion.state = (
                        "possible_duplicate"
                        if suggestion.state == "possible_duplicate"
                        else "pending_review"
                    )
                    suggestion.clarification_state = "not_required"
                else:
                    suggestion.state = "pending_review"
                    suggestion.clarification_state = "not_required"
                    handoff_link, nonce = await self._issue_handoff(
                        session=session,
                        suggestion=suggestion,
                        now=now,
                    )
                    session.add(
                        CRMTaskSuggestionEvent(
                            suggestion_id=suggestion.id,
                            suggestion_version=suggestion.version,
                            event_type="preview",
                            actor_type="sydney",
                            event_data_json=_canonical_json(
                                {
                                    "handoff_nonce_id": str(nonce.id),
                                    "payload_hash": suggestion.payload_hash,
                                    "suggestion_version": suggestion.version,
                                }
                            ),
                            created_at=now + timedelta(microseconds=1),
                        )
                    )
                await session.flush()
                return AnswerResult(
                    suggestion_id=suggestion.id,
                    suggestion_version=suggestion.version,
                    next_clarification_id=next_clarification_id,
                    handoff_link=handoff_link,
                )

    async def supersede_for_locked_suggestion(
        self,
        *,
        session: AsyncSession,
        suggestion: CRMTaskSuggestion,
        previous_version: int,
        now: datetime,
    ) -> bool:
        return await supersede_locked_clarification(
            session=session,
            suggestion=suggestion,
            previous_version=previous_version,
            now=now,
        )
