"""Framework-neutral contracts for the recovered Command Contacts workspace."""

from __future__ import annotations

import hashlib
import json
import math
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Literal, TypeAlias, TypeVar


class ContactSection(StrEnum):
    TIMELINE = "timeline"
    OPPORTUNITIES = "opportunities"
    SMART_PLANS = "smart_plans"
    NOTES = "notes"
    SAVED_SEARCHES = "saved_searches"
    TASKS_TO_DO = "tasks_to_do"
    TASKS_COMPLETED = "tasks_completed"
    TASKS_ARCHIVED = "tasks_archived"


class CaptureQualityValue(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    SHELL = "shell"
    ERROR = "error"


class MaterializationStatus(StrEnum):
    SOURCE_ONLY = "source_only"
    MATERIALIZED = "materialized"


class TimelineOrigin(StrEnum):
    RECOVERED = "recovered"
    INTERNAL_CRM = "internal_crm"
    LEGACY_LEAD = "legacy_lead"
    BOOKING = "booking"


class ContactOriginFilter(StrEnum):
    RECOVERED = "recovered"
    LEAD_BACKED = "lead_backed"
    LEGACY_ONLY = "legacy_only"
    INTERNAL_ONLY = "internal_only"


class ContactSourceFilter(StrEnum):
    KW_COMMAND = "kw_command"
    INTERNAL_CRM = "internal_crm"
    LEGACY_LEAD = "legacy_lead"


class ContactSmartView(StrEnum):
    ALL = "all"
    NEVER_CONTACTED = "never_contacted"
    RECENTLY_ACTIVE = "recently_active"
    BIRTHDAYS_THIS_MONTH = "birthdays_this_month"
    ANNIVERSARIES_THIS_MONTH = "anniversaries_this_month"


class ContactSortKey(StrEnum):
    NAME = "name"
    STAGE = "stage"
    HEALTH_SCORE = "health_score"
    LAST_CONTACTED_AT = "last_contacted_at"
    LAST_INTERACTION_AT = "last_interaction_at"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


CONTACT_TOUCH_ACTIVITY_KINDS = frozenset(
    {"call", "email", "sms", "text", "meeting", "contacted"}
)

ContactEvidenceQuality: TypeAlias = Literal["complete", "partial", "limitation"]
CelebrationYearQuality: TypeAlias = Literal[
    "verified", "yearless", "sentinel", "unknown"
]
ContactAuditScalar: TypeAlias = str | int | bool | None
ContactAuditDomain: TypeAlias = Literal[
    "command-contact-audit-v1:first_name",
    "command-contact-audit-v1:last_name",
    "command-contact-audit-v1:email",
    "command-contact-audit-v1:phone",
    "command-contact-audit-v1:note_body",
    "command-contact-audit-v1:saved_search_name",
    "command-contact-audit-v1:saved_search_criteria",
]
ContactAuditAction: TypeAlias = Literal[
    "contact.created",
    "contact.updated",
    "contact.legacy_sync_applied",
    "contact.legacy_import_applied",
    "contact.archive_import_applied",
    "contact.bulk_stage_set",
    "contact.bulk_tag_added",
    "contact.bulk_tag_removed",
    "contact.tag_added",
    "contact.tag_removed",
    "contact.note_created",
    "contact.note_deleted",
    "contact.saved_search_created",
    "contact.saved_search_deleted",
]
JsonValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | tuple["JsonValue", ...]
    | Mapping[str, "JsonValue"]
)


def _exact_int(value: object, field_name: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        qualifier = f" >= {minimum}" if minimum is not None else ""
        raise ValueError(f"{field_name} must be an integer{qualifier}")
    return value


def _bounded_text(
    value: object,
    field_name: str,
    *,
    minimum: int,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not minimum <= len(normalized) <= maximum:
        raise ValueError(f"{field_name} length is outside the allowed range")
    return normalized


def _optional_text(value: object, field_name: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, field_name, minimum=0, maximum=maximum) or None


def _optional_exact_date(value: object, field_name: str) -> date | None:
    if value is None:
        return None
    if type(value) is not date:
        raise TypeError(f"{field_name} must be an exact date or null")
    return value


def _positive_id(value: object, field_name: str = "id") -> int:
    return _exact_int(value, field_name, minimum=1)


def _freeze_json(value: object) -> JsonValue:
    if value is None or isinstance(value, str) or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON floats must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise TypeError("value is not canonical JSON")


def _thaw_json(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        _thaw_json(_freeze_json(value)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


_CONTACT_AUDIT_DOMAINS = frozenset(
    {
        "command-contact-audit-v1:first_name",
        "command-contact-audit-v1:last_name",
        "command-contact-audit-v1:email",
        "command-contact-audit-v1:phone",
        "command-contact-audit-v1:note_body",
        "command-contact-audit-v1:saved_search_name",
        "command-contact-audit-v1:saved_search_criteria",
    }
)
_CONTACT_AUDIT_ACTIONS = frozenset(
    {
        "contact.created",
        "contact.updated",
        "contact.legacy_sync_applied",
        "contact.legacy_import_applied",
        "contact.archive_import_applied",
        "contact.bulk_stage_set",
        "contact.bulk_tag_added",
        "contact.bulk_tag_removed",
        "contact.tag_added",
        "contact.tag_removed",
        "contact.note_created",
        "contact.note_deleted",
        "contact.saved_search_created",
        "contact.saved_search_deleted",
    }
)
_CREATE_AUDIT_FIELDS = frozenset(
    {
        "anniversary",
        "birthday",
        "email",
        "first_name",
        "last_name",
        "phone",
        "stage",
    }
)
_SYNC_CREATE_AUDIT_FIELDS = frozenset(
    {"email", "first_name", "last_name", "phone", "stage", "lead_id"}
)
_CONTACT_UPDATE_FIELDS = frozenset(_CREATE_AUDIT_FIELDS)
_TEXT_AUDIT_DOMAINS: dict[str, ContactAuditDomain] = {
    "first_name": "command-contact-audit-v1:first_name",
    "last_name": "command-contact-audit-v1:last_name",
    "email": "command-contact-audit-v1:email",
    "phone": "command-contact-audit-v1:phone",
}


def redact_contact_audit_value(
    value: str | None,
    *,
    domain: ContactAuditDomain,
) -> dict[str, ContactAuditScalar]:
    """Return the exact Task 5C-E domain-separated UTF-8 fingerprint."""
    if type(domain) is not str or domain not in _CONTACT_AUDIT_DOMAINS:
        raise ValueError("contact audit domain is invalid")
    if value is None:
        raw_utf8 = b""
        present = False
    elif type(value) is str:
        raw_utf8 = value.encode("utf-8")
        present = True
    else:
        raise TypeError("contact audit value must be a string or null")
    return {
        "present": present,
        "length": len(raw_utf8),
        "sha256": hashlib.sha256(
            domain.encode("ascii") + b"\0" + raw_utf8
        ).hexdigest(),
    }


def _require_exact_keys(payload: Mapping[str, object], expected: set[str]) -> None:
    if set(payload) != expected or any(type(key) is not str for key in payload):
        raise ValueError("contact audit payload shape is invalid")


def _audit_date(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not date:
        raise TypeError(f"{field_name} must be an exact date or null")
    return value.isoformat()


def _audit_text(
    value: object,
    field_name: str,
    *,
    minimum: int,
    maximum: int,
    nullable: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{field_name} length is outside the allowed range")
    return value


def _audit_contact_field(field_name: str, value: object) -> object:
    if field_name == "first_name":
        text = _audit_text(value, field_name, minimum=1, maximum=120)
        return redact_contact_audit_value(
            text, domain=_TEXT_AUDIT_DOMAINS[field_name]
        )
    if field_name == "last_name":
        text = _audit_text(value, field_name, minimum=0, maximum=120)
        return redact_contact_audit_value(
            text, domain=_TEXT_AUDIT_DOMAINS[field_name]
        )
    if field_name == "email":
        text = _audit_text(
            value, field_name, minimum=0, maximum=255, nullable=True
        )
        return redact_contact_audit_value(
            text, domain=_TEXT_AUDIT_DOMAINS[field_name]
        )
    if field_name == "phone":
        text = _audit_text(
            value, field_name, minimum=0, maximum=50, nullable=True
        )
        return redact_contact_audit_value(
            text, domain=_TEXT_AUDIT_DOMAINS[field_name]
        )
    if field_name == "stage":
        return _audit_text(value, field_name, minimum=1, maximum=50)
    if field_name in {"birthday", "anniversary"}:
        return _audit_date(value, field_name)
    if field_name == "lead_id":
        return _positive_id(value, field_name)
    raise ValueError("contact audit field is invalid")


def _contact_snapshot(
    action: ContactAuditAction,
    fields: set[str],
    payload: Mapping[str, object],
) -> dict[str, object]:
    _require_exact_keys(payload, fields)
    encoded: dict[str, object] = {
        "action": action,
        "changed_fields": sorted(fields),
    }
    encoded.update(
        (field_name, _audit_contact_field(field_name, payload[field_name]))
        for field_name in fields
    )
    return encoded


def _updated_contact_snapshot(
    action: ContactAuditAction,
    payload: Mapping[str, object],
) -> dict[str, object]:
    changed = payload.get("changed_fields")
    if not isinstance(changed, (tuple, list)) or not changed:
        raise ValueError("contact audit changed fields are invalid")
    if any(type(field) is not str for field in changed):
        raise ValueError("contact audit changed fields are invalid")
    fields = set(changed)
    if (
        len(fields) != len(changed)
        or tuple(changed) != tuple(sorted(changed))
        or not fields <= _CONTACT_UPDATE_FIELDS
    ):
        raise ValueError("contact audit changed fields are invalid")
    _require_exact_keys(payload, fields | {"changed_fields"})
    values = {field: payload[field] for field in fields}
    return _contact_snapshot(action, fields, values)


def _special_contact_audit_payload(
    action: ContactAuditAction,
    phase: Literal["before", "after"],
    payload: Mapping[str, object],
) -> dict[str, object]:
    if action == "contact.bulk_stage_set":
        _require_exact_keys(payload, {"stage"})
        stage = _audit_text(
            payload["stage"], "stage", minimum=1, maximum=50
        )
        if stage is None or stage != stage.strip():
            raise ValueError("contact audit stage is invalid")
        return {
            "action": action,
            "stage": stage,
        }
    if action in {
        "contact.bulk_tag_added",
        "contact.bulk_tag_removed",
        "contact.tag_added",
        "contact.tag_removed",
    }:
        _require_exact_keys(payload, {"present", "tag_id"})
        if type(payload["present"]) is not bool:
            raise TypeError("contact audit presence is invalid")
        expected_presence = (
            action in {"contact.bulk_tag_added", "contact.tag_added"}
        ) == (phase == "after")
        if payload["present"] is not expected_presence:
            raise ValueError("contact audit presence is invalid")
        return {
            "action": action,
            "present": payload["present"],
            "tag_id": _positive_id(payload["tag_id"], "tag_id"),
        }
    if action in {"contact.note_created", "contact.note_deleted"}:
        _require_exact_keys(payload, {"body", "note_id", "present"})
        body = _audit_text(
            payload["body"], "body", minimum=1, maximum=20_000
        )
        if type(payload["present"]) is not bool:
            raise TypeError("contact audit presence is invalid")
        expected_presence = (action == "contact.note_created") == (
            phase == "after"
        )
        if payload["present"] is not expected_presence:
            raise ValueError("contact audit presence is invalid")
        return {
            "action": action,
            "body": redact_contact_audit_value(
                body, domain="command-contact-audit-v1:note_body"
            ),
            "note_id": _positive_id(payload["note_id"], "note_id"),
            "present": payload["present"],
        }
    if action in {
        "contact.saved_search_created",
        "contact.saved_search_deleted",
    }:
        _require_exact_keys(
            payload, {"criteria", "name", "present", "search_id"}
        )
        criteria = _audit_text(
            payload["criteria"], "criteria", minimum=1, maximum=65_536
        )
        name = _audit_text(
            payload["name"], "name", minimum=1, maximum=255
        )
        if type(payload["present"]) is not bool:
            raise TypeError("contact audit presence is invalid")
        expected_presence = (
            action == "contact.saved_search_created"
        ) == (phase == "after")
        if payload["present"] is not expected_presence:
            raise ValueError("contact audit presence is invalid")
        return {
            "action": action,
            "criteria": redact_contact_audit_value(
                criteria,
                domain="command-contact-audit-v1:saved_search_criteria",
            ),
            "name": redact_contact_audit_value(
                name, domain="command-contact-audit-v1:saved_search_name"
            ),
            "present": payload["present"],
            "search_id": _positive_id(payload["search_id"], "search_id"),
        }
    raise ValueError("contact audit action is invalid")


def canonical_contact_audit_json(
    *,
    action: ContactAuditAction,
    phase: Literal["before", "after"],
    payload: Mapping[str, object],
) -> str:
    """Build one exact action-aware, canonical Task 5C-E audit mapping."""
    if type(action) is not str or action not in _CONTACT_AUDIT_ACTIONS:
        raise ValueError("contact audit action is invalid")
    if phase not in {"before", "after"}:
        raise ValueError("contact audit phase is invalid")
    if not isinstance(payload, Mapping):
        raise TypeError("contact audit payload must be a mapping")

    if action == "contact.created":
        value = (
            {}
            if phase == "before" and not payload
            else _contact_snapshot(action, set(_CREATE_AUDIT_FIELDS), payload)
            if phase == "after"
            else None
        )
    elif action == "contact.updated":
        value = _updated_contact_snapshot(action, payload)
    elif action in {
        "contact.legacy_import_applied",
        "contact.archive_import_applied",
    }:
        value = (
            {}
            if phase == "before" and not payload
            else _contact_snapshot(action, set(_CREATE_AUDIT_FIELDS), payload)
            if phase == "after"
            else None
        )
    elif action == "contact.legacy_sync_applied":
        if not payload and phase == "before":
            value = {}
        elif "activity_present" not in payload:
            value = (
                _contact_snapshot(
                    action, set(_SYNC_CREATE_AUDIT_FIELDS), payload
                )
                if phase == "after"
                else None
            )
        else:
            expected = (
                {"activity_present", "lead_id"}
                if phase == "before"
                else {"activity_present", "activity_id", "lead_id"}
            )
            _require_exact_keys(payload, expected)
            expected_presence = phase == "after"
            if payload["activity_present"] is not expected_presence:
                raise ValueError("contact audit activity state is invalid")
            value = {
                "action": action,
                "activity_present": expected_presence,
                "lead_id": _positive_id(payload["lead_id"], "lead_id"),
            }
            if phase == "after":
                value["activity_id"] = _positive_id(
                    payload["activity_id"], "activity_id"
                )
    else:
        value = _special_contact_audit_payload(action, phase, payload)
    if value is None:
        raise ValueError("contact audit phase payload is invalid")
    return _canonical_json(value)


def _validate_audit_actor_subject(actor_subject: object) -> str:
    if (
        type(actor_subject) is not str
        or not 1 <= len(actor_subject) <= 255
        or not actor_subject.isascii()
        or not actor_subject.isdigit()
        or int(actor_subject) <= 0
        or actor_subject != str(int(actor_subject))
    ):
        raise ValueError("administrator subject is invalid")
    return actor_subject


def canonical_workspace_saved_search_activity_json(
    *,
    actor_subject: str,
    search_id: int,
    name: str,
) -> str:
    """Build the sole actor-attributed workspace activity metadata mapping."""
    actor = _validate_audit_actor_subject(actor_subject)
    normalized_name = _audit_text(name, "name", minimum=1, maximum=255)
    return _canonical_json(
        {
            "action": "workspace.saved_search_deleted",
            "actor_subject": actor,
            "saved_search": redact_contact_audit_value(
                normalized_name,
                domain="command-contact-audit-v1:saved_search_name",
            ),
            "search_id": _positive_id(search_id, "search_id"),
        }
    )


@dataclass(frozen=True, slots=True)
class TimelineCursorV1:
    null_rank: Literal[0, 1]
    occurred_at: datetime | None
    origin_rank: Literal[0, 1, 2, 3]
    entity_id: int

    def __post_init__(self) -> None:
        if type(self.null_rank) is not int or self.null_rank not in (0, 1):
            raise ValueError("cursor null rank is invalid")
        if type(self.origin_rank) is not int or self.origin_rank not in (0, 1, 2, 3):
            raise ValueError("cursor origin rank is invalid")
        _positive_id(self.entity_id, "cursor entity id")
        if self.null_rank == 1:
            if self.occurred_at is not None:
                raise ValueError("cursor null rank conflicts with timestamp")
            return
        if not isinstance(self.occurred_at, datetime):
            raise TypeError("cursor timestamp is required")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("cursor timestamp must be UTC")


def _cursor_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def encode_timeline_cursor(cursor: TimelineCursorV1) -> str:
    if not isinstance(cursor, TimelineCursorV1):
        raise TypeError("cursor must be TimelineCursorV1")
    timestamp = (
        _cursor_timestamp(cursor.occurred_at)
        if cursor.occurred_at is not None
        else None
    )
    raw = json.dumps(
        {
            "v": 1,
            "n": cursor.null_rank,
            "t": timestamp,
            "o": cursor.origin_rank,
            "i": cursor.entity_id,
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


_BASE64URL_RE = re.compile(r"[A-Za-z0-9_-]+")
_CURSOR_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z"
)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("timeline cursor is invalid")
        result[key] = value
    return result


def decode_timeline_cursor(encoded: str) -> TimelineCursorV1:
    error = ValueError("timeline cursor is invalid")
    if (
        not isinstance(encoded, str)
        or not encoded
        or "=" in encoded
        or _BASE64URL_RE.fullmatch(encoded) is None
    ):
        raise error
    try:
        padding = "=" * (-len(encoded) % 4)
        raw = urlsafe_b64decode((encoded + padding).encode("ascii"))
        if urlsafe_b64encode(raw).decode("ascii").rstrip("=") != encoded:
            raise error
        text = raw.decode("utf-8")
        payload = json.loads(text, object_pairs_hook=_unique_json_object)
        if not isinstance(payload, dict) or tuple(payload) != ("v", "n", "t", "o", "i"):
            raise error
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise error
        timestamp_raw = payload["t"]
        timestamp: datetime | None
        if timestamp_raw is None:
            timestamp = None
        elif isinstance(timestamp_raw, str) and _CURSOR_TIMESTAMP_RE.fullmatch(timestamp_raw):
            timestamp = datetime.strptime(
                timestamp_raw, "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=UTC)
        else:
            raise error
        cursor = TimelineCursorV1(
            null_rank=payload["n"],  # type: ignore[arg-type]
            occurred_at=timestamp,
            origin_rank=payload["o"],  # type: ignore[arg-type]
            entity_id=payload["i"],  # type: ignore[arg-type]
        )
        if encode_timeline_cursor(cursor) != encoded:
            raise error
        return cursor
    except (
        Base64Error,
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise error from exc


def timeline_position_is_after(
    cursor: TimelineCursorV1,
    *,
    null_rank: Literal[0, 1],
    occurred_at: datetime | None,
    origin_rank: Literal[0, 1, 2, 3],
    entity_id: int,
) -> bool:
    candidate = TimelineCursorV1(null_rank, occurred_at, origin_rank, entity_id)
    if candidate.null_rank != cursor.null_rank:
        return candidate.null_rank > cursor.null_rank
    if candidate.occurred_at != cursor.occurred_at:
        if candidate.occurred_at is None or cursor.occurred_at is None:
            return candidate.occurred_at is None
        return candidate.occurred_at < cursor.occurred_at
    if candidate.origin_rank != cursor.origin_rank:
        return candidate.origin_rank > cursor.origin_rank
    return candidate.entity_id < cursor.entity_id


_EnumValue = TypeVar("_EnumValue", bound=StrEnum)


def _enum_tuple(
    values: tuple[_EnumValue, ...],
    enum_type: type[_EnumValue],
    field_name: str,
) -> tuple[_EnumValue, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if any(not isinstance(value, enum_type) for value in values):
        raise ValueError(f"{field_name} contains an invalid value")
    return tuple(sorted(set(values), key=lambda value: value.value))


@dataclass(frozen=True, slots=True)
class ContactDirectoryFilters:
    page: int = 1
    page_size: int = 50
    query: str | None = None
    stage: str | None = None
    owner_actor_id: str | None = None
    assignee_actor_id: str | None = None
    tag_ids: tuple[int, ...] = ()
    sources: tuple[ContactSourceFilter, ...] = ()
    origins: tuple[ContactOriginFilter, ...] = ()
    health_min: int | None = None
    health_max: int | None = None
    birthday_month: int | None = None
    anniversary_month: int | None = None
    smart_view: ContactSmartView = ContactSmartView.ALL
    sort: ContactSortKey = ContactSortKey.NAME
    direction: SortDirection = SortDirection.ASC

    def __post_init__(self) -> None:
        _exact_int(self.page, "page", minimum=1)
        if _exact_int(self.page_size, "page_size", minimum=1) > 100:
            raise ValueError("page_size must not exceed 100")
        object.__setattr__(self, "query", _optional_text(self.query, "query", 200))
        object.__setattr__(self, "stage", _optional_text(self.stage, "stage", 50))
        object.__setattr__(self, "owner_actor_id", _optional_text(self.owner_actor_id, "owner_actor_id", 255))
        object.__setattr__(self, "assignee_actor_id", _optional_text(self.assignee_actor_id, "assignee_actor_id", 255))
        if not isinstance(self.tag_ids, tuple) or any(type(value) is not int or value <= 0 for value in self.tag_ids):
            raise ValueError("tag_ids must contain positive integers")
        object.__setattr__(self, "tag_ids", tuple(sorted(set(self.tag_ids))))
        object.__setattr__(self, "sources", _enum_tuple(self.sources, ContactSourceFilter, "sources"))
        object.__setattr__(self, "origins", _enum_tuple(self.origins, ContactOriginFilter, "origins"))
        for field_name in ("health_min", "health_max"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not int or not 0 <= value <= 100):
                raise ValueError(f"{field_name} must be between 0 and 100")
        if self.health_min is not None and self.health_max is not None and self.health_min > self.health_max:
            raise ValueError("health_min must not exceed health_max")
        for field_name in ("birthday_month", "anniversary_month"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not int or not 1 <= value <= 12):
                raise ValueError(f"{field_name} must be between 1 and 12")
        if not isinstance(self.smart_view, ContactSmartView) or not isinstance(self.sort, ContactSortKey) or not isinstance(self.direction, SortDirection):
            raise TypeError("filter enum value is invalid")


@dataclass(frozen=True, slots=True)
class ContactTagValue:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ContactActorValue:
    role: Literal["owner", "assignee", "collaborator"]
    provider_actor_id: str | None
    display_name: str | None


@dataclass(frozen=True, slots=True)
class ContactCelebrationValue:
    month: int
    day: int
    year: int | None
    year_quality: CelebrationYearQuality
    origin: Literal["internal_crm", "recovered"]


@dataclass(frozen=True, slots=True)
class ContactAddressValue:
    id: int
    address_type: str | None
    formatted: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    source_record_id: int | None


@dataclass(frozen=True, slots=True)
class ContactDirectoryRow:
    id: int
    first_name: str
    last_name: str
    display_name: str
    primary_email: str | None
    primary_phone: str | None
    stage: str
    lead_backed: bool
    origins: tuple[ContactOriginFilter, ...]
    sources: tuple[ContactSourceFilter, ...]
    health_score: int | None
    last_contacted_at: datetime | None
    last_interaction_at: datetime | None
    owner: ContactActorValue | None
    assignee: ContactActorValue | None
    tags: tuple[ContactTagValue, ...]
    birthday: ContactCelebrationValue | None
    anniversary: ContactCelebrationValue | None
    evidence_quality: ContactEvidenceQuality | None


@dataclass(frozen=True, slots=True)
class ContactDirectoryPage:
    rows: tuple[ContactDirectoryRow, ...]
    total: int
    page: int
    page_size: int
    page_count: int
    sort: ContactSortKey
    direction: SortDirection


@dataclass(frozen=True, slots=True)
class ContactRecoveredProfile:
    legal_name: str | None
    preferred_name: str | None
    description: str | None
    company: str | None
    title: str | None
    lead_source: str | None
    account_name: str | None
    birthday: ContactCelebrationValue | None
    anniversary: ContactCelebrationValue | None


@dataclass(frozen=True, slots=True)
class ContactDetail:
    contact: ContactDirectoryRow
    lead_id: int | None
    recovered_profile: ContactRecoveredProfile | None
    addresses: tuple[ContactAddressValue, ...]
    ownership: tuple[ContactActorValue, ...]
    tags: tuple[ContactTagValue, ...]


@dataclass(frozen=True, slots=True)
class ContactNeighbors:
    previous_contact_id: int | None
    next_contact_id: int | None


@dataclass(frozen=True, slots=True)
class ContactWorkspaceSummary:
    open_tasks: int
    completed_tasks: int
    archived_tasks: int
    active_smart_plans: int
    opportunities: int
    notes: int
    saved_searches: int
    bookings: int


@dataclass(frozen=True, slots=True)
class ContactOpportunityOccurrence:
    kind: Literal["opportunity"]
    title: str
    stage: str | None
    value_cents: int | None


@dataclass(frozen=True, slots=True)
class ContactSmartPlanOccurrence:
    kind: Literal["smart_plan"]
    title: str
    status: str | None


@dataclass(frozen=True, slots=True)
class ContactTaskOccurrence:
    kind: Literal["task"]
    title: str
    description: str | None
    state: Literal["to_do", "completed", "archived"]
    due_at: datetime | None


@dataclass(frozen=True, slots=True)
class ContactNoteOccurrence:
    kind: Literal["note"]
    title: str
    body: str | None


@dataclass(frozen=True, slots=True)
class ContactSavedSearchOccurrence:
    kind: Literal["saved_search"]
    title: str
    criteria_summary: tuple[str, ...]


ContactOccurrenceValue: TypeAlias = (
    ContactOpportunityOccurrence
    | ContactSmartPlanOccurrence
    | ContactTaskOccurrence
    | ContactNoteOccurrence
    | ContactSavedSearchOccurrence
)


@dataclass(frozen=True, slots=True)
class ContactSourceOnly:
    status: Literal["source_only"]
    source_record_id: int
    source_key_hash: str
    section: ContactSection
    occurrence_ordinal: int
    capture_quality: CaptureQualityValue
    captured_at: datetime | None
    value: ContactOccurrenceValue


@dataclass(frozen=True, slots=True)
class ContactMaterialized:
    status: Literal["materialized"]
    source_record_id: int
    source_key_hash: str
    section: ContactSection
    occurrence_ordinal: int
    capture_quality: CaptureQualityValue
    captured_at: datetime | None
    value: ContactOccurrenceValue
    entity_type: Literal[
        "note", "saved_search", "task", "smart_plan", "opportunity",
    ]
    entity_id: int


ContactSectionRow: TypeAlias = ContactSourceOnly | ContactMaterialized


@dataclass(frozen=True, slots=True)
class ContactSectionPage:
    rows: tuple[ContactSectionRow, ...]
    total: int
    page: int
    page_size: int
    page_count: int


@dataclass(frozen=True, slots=True)
class ContactArtifactMetadata:
    artifact_id: int
    artifact_type: str
    sha256: str
    size_bytes: int
    content_href: str


@dataclass(frozen=True, slots=True)
class ContactSourceMetadata:
    source_record_id: int
    record_kind: str
    evidence_level: Literal[
        "observed_record", "rendered_occurrence", "displayed_aggregate"
    ]
    capture_quality: CaptureQualityValue
    captured_at: datetime | None
    artifacts: tuple[ContactArtifactMetadata, ...]


@dataclass(frozen=True, slots=True)
class ContactSectionEvidence:
    capture_position_id: int
    section: ContactSection
    source_record_id: int
    capture_quality: CaptureQualityValue
    row_count: int
    is_empty: bool
    limitation_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContactCaptureEvidence:
    capture_position_id: int
    capture_ordinal: int
    source_record_id: int
    capture_quality: CaptureQualityValue
    sections: tuple[ContactSectionEvidence, ...]


@dataclass(frozen=True, slots=True)
class ContactEvidence:
    contact_id: int
    provider_contact_rows: int
    resolved_provider_identities: int
    coalesced_aliases: Literal[0]
    lead_backed_contacts: int
    reviewed_overlaps: int
    legacy_only_contacts: int
    capture_positions: tuple[ContactCaptureEvidence, ...]
    section_matrix: tuple[ContactSectionEvidence, ...]
    sources: tuple[ContactSourceMetadata, ...]
    capture_quality: ContactEvidenceQuality


@dataclass(frozen=True, slots=True)
class ContactCelebrationRow:
    contact_id: int
    display_name: str
    kind: Literal["birthday", "anniversary"]
    month: int
    day: int
    year: int | None
    year_quality: CelebrationYearQuality
    origin: Literal["internal_crm", "recovered"]


@dataclass(frozen=True, slots=True)
class ContactCelebrations:
    birthdays: tuple[ContactCelebrationRow, ...]
    anniversaries: tuple[ContactCelebrationRow, ...]


class UnsetType(Enum):
    TOKEN = "unset"


UNSET = UnsetType.TOKEN


@dataclass(frozen=True, slots=True)
class ContactCreateCommand:
    first_name: str
    last_name: str = ""
    email: str | None = None
    phone: str | None = None
    stage: str = "lead"
    birthday: date | None = None
    anniversary: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "first_name", _bounded_text(self.first_name, "first_name", minimum=1, maximum=120))
        object.__setattr__(self, "last_name", _bounded_text(self.last_name, "last_name", minimum=0, maximum=120))
        object.__setattr__(self, "email", _optional_text(self.email, "email", 255))
        object.__setattr__(self, "phone", _optional_text(self.phone, "phone", 50))
        object.__setattr__(self, "stage", _bounded_text(self.stage, "stage", minimum=1, maximum=50))
        object.__setattr__(
            self, "birthday", _optional_exact_date(self.birthday, "birthday")
        )
        object.__setattr__(
            self,
            "anniversary",
            _optional_exact_date(self.anniversary, "anniversary"),
        )


@dataclass(frozen=True, slots=True)
class ContactUpdateCommand:
    first_name: str | UnsetType = UNSET
    last_name: str | UnsetType = UNSET
    email: str | None | UnsetType = UNSET
    phone: str | None | UnsetType = UNSET
    stage: str | UnsetType = UNSET
    birthday: date | None | UnsetType = UNSET
    anniversary: date | None | UnsetType = UNSET

    def __post_init__(self) -> None:
        if all(getattr(self, name) is UNSET for name in self.__dataclass_fields__):
            raise ValueError("contact update must change at least one field")
        for field_name, maximum, minimum in (
            ("first_name", 120, 1), ("last_name", 120, 0), ("stage", 50, 1),
        ):
            value = getattr(self, field_name)
            if value is None:
                raise ValueError(f"{field_name} cannot be null")
            if value is not UNSET:
                object.__setattr__(self, field_name, _bounded_text(value, field_name, minimum=minimum, maximum=maximum))
        for field_name, maximum in (("email", 255), ("phone", 50)):
            value = getattr(self, field_name)
            if value is not UNSET:
                object.__setattr__(self, field_name, _optional_text(value, field_name, maximum))
        for field_name in ("birthday", "anniversary"):
            value = getattr(self, field_name)
            if value is not UNSET:
                object.__setattr__(
                    self, field_name, _optional_exact_date(value, field_name)
                )


@dataclass(frozen=True, slots=True)
class ContactBulkSetStage:
    action: Literal["set_stage"]
    stage: str

    def __post_init__(self) -> None:
        if self.action != "set_stage":
            raise ValueError("bulk action is invalid")
        object.__setattr__(self, "stage", _bounded_text(self.stage, "stage", minimum=1, maximum=50))


@dataclass(frozen=True, slots=True)
class ContactBulkAddTag:
    action: Literal["add_tag"]
    tag_id: int

    def __post_init__(self) -> None:
        if self.action != "add_tag":
            raise ValueError("bulk action is invalid")
        _positive_id(self.tag_id, "tag_id")


@dataclass(frozen=True, slots=True)
class ContactBulkRemoveTag:
    action: Literal["remove_tag"]
    tag_id: int

    def __post_init__(self) -> None:
        if self.action != "remove_tag":
            raise ValueError("bulk action is invalid")
        _positive_id(self.tag_id, "tag_id")


ContactBulkAction: TypeAlias = ContactBulkSetStage | ContactBulkAddTag | ContactBulkRemoveTag


@dataclass(frozen=True, slots=True)
class ContactBulkCommand:
    contact_ids: tuple[int, ...]
    action: ContactBulkAction

    def __post_init__(self) -> None:
        if not isinstance(self.contact_ids, tuple) or not 1 <= len(self.contact_ids) <= 200:
            raise ValueError("bulk contact_ids must contain 1 to 200 values")
        if any(type(value) is not int or value <= 0 for value in self.contact_ids):
            raise ValueError("bulk contact_ids must be positive integers")
        if len(set(self.contact_ids)) != len(self.contact_ids):
            raise ValueError("bulk contact_ids must be unique")
        if not isinstance(self.action, (ContactBulkSetStage, ContactBulkAddTag, ContactBulkRemoveTag)):
            raise TypeError("bulk action is invalid")


@dataclass(frozen=True, slots=True)
class ContactBulkResult:
    requested_contact_ids: tuple[int, ...]
    actioned_contact_ids: tuple[int, ...]
    action: Literal["set_stage", "add_tag", "remove_tag"]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requested_contact_ids, tuple)
            or not self.requested_contact_ids
            or len(self.requested_contact_ids) > 200
            or any(
                type(value) is not int or value <= 0
                for value in self.requested_contact_ids
            )
            or tuple(sorted(set(self.requested_contact_ids)))
            != self.requested_contact_ids
        ):
            raise ValueError("requested contact ids are invalid")
        if (
            not isinstance(self.actioned_contact_ids, tuple)
            or any(
                type(value) is not int or value <= 0
                for value in self.actioned_contact_ids
            )
            or tuple(sorted(set(self.actioned_contact_ids)))
            != self.actioned_contact_ids
            or not set(self.actioned_contact_ids) <= set(self.requested_contact_ids)
        ):
            raise ValueError("actioned contact ids are invalid")
        if self.action not in {"set_stage", "add_tag", "remove_tag"}:
            raise ValueError("bulk result action is invalid")


@dataclass(frozen=True, slots=True)
class ContactNoteCreateCommand:
    body: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "body", _bounded_text(self.body, "body", minimum=1, maximum=20_000))


@dataclass(frozen=True, slots=True)
class ContactSavedSearchCreateCommand:
    name: str
    criteria: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _bounded_text(self.name, "name", minimum=1, maximum=255))
        frozen = _freeze_json(self.criteria)
        if not isinstance(frozen, Mapping):
            raise TypeError("criteria must be a mapping")
        if len(_canonical_json(frozen).encode("utf-8")) > 65_536:
            raise ValueError("canonical criteria must not exceed 64 KiB")
        object.__setattr__(self, "criteria", frozen)


@dataclass(frozen=True, slots=True)
class ContactImportRowCommand:
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    stage: str
    birthday: date | None
    anniversary: date | None

    def __post_init__(self) -> None:
        normalized = ContactCreateCommand(
            self.first_name, self.last_name, self.email, self.phone, self.stage,
            self.birthday, self.anniversary,
        )
        for field_name in ("first_name", "last_name", "email", "phone", "stage"):
            object.__setattr__(self, field_name, getattr(normalized, field_name))


@dataclass(frozen=True, slots=True)
class ContactImportCommand:
    contacts: tuple[ContactImportRowCommand, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.contacts, tuple) or not 1 <= len(self.contacts) <= 1_000:
            raise ValueError("contacts import must contain 1 to 1000 rows")
        if any(not isinstance(row, ContactImportRowCommand) for row in self.contacts):
            raise TypeError("contacts import rows are invalid")


@dataclass(frozen=True, slots=True)
class ContactMutationResult:
    contact_id: int
    record_id: int | None
    changed: bool
    audit_entity_type: Literal["contact_audit"] | None
    audit_event_id: int | None

    def __post_init__(self) -> None:
        _positive_id(self.contact_id, "contact_id")
        if self.record_id is not None:
            _positive_id(self.record_id, "record_id")
        if type(self.changed) is not bool:
            raise TypeError("changed must be a boolean")
        if self.changed:
            if self.record_id is None:
                raise ValueError("changed contact mutation requires a record id")
            if self.audit_entity_type != "contact_audit":
                raise ValueError("changed contact mutation requires contact audit")
            _positive_id(self.audit_event_id, "audit_event_id")
        elif self.audit_entity_type is not None or self.audit_event_id is not None:
            raise ValueError("no-op contact mutation cannot contain audit data")


@dataclass(frozen=True, slots=True)
class WorkspaceMutationResult:
    record_id: int
    changed: bool
    audit_entity_type: Literal["workspace_activity"]
    audit_event_id: int | None

    def __post_init__(self) -> None:
        _positive_id(self.record_id, "record_id")
        if self.changed is not True:
            raise ValueError("workspace mutation must be changed")
        if self.audit_entity_type != "workspace_activity":
            raise ValueError("workspace mutation requires workspace activity")
        _positive_id(self.audit_event_id, "audit_event_id")


SavedSearchDeletionResult: TypeAlias = ContactMutationResult | WorkspaceMutationResult


@dataclass(frozen=True, slots=True)
class ContactLegacySyncResult:
    created: int
    timeline_backfilled: int
    total_legacy_leads: int

    def __post_init__(self) -> None:
        for field_name in (
            "created",
            "timeline_backfilled",
            "total_legacy_leads",
        ):
            _exact_int(getattr(self, field_name), field_name, minimum=0)
        if self.created + self.timeline_backfilled > self.total_legacy_leads:
            raise ValueError("legacy sync counts are contradictory")


@dataclass(frozen=True, slots=True)
class ContactImportResult:
    created: int
    skipped_duplicates: int


@dataclass(frozen=True, slots=True)
class ContactSavedSearchValue:
    id: int
    contact_id: int | None
    contact_name: str | None
    name: str
    criteria: Mapping[str, JsonValue]
    updated_at: datetime

    def __post_init__(self) -> None:
        frozen = _freeze_json(self.criteria)
        if not isinstance(frozen, Mapping):
            raise TypeError("criteria must be a mapping")
        object.__setattr__(self, "criteria", frozen)


@dataclass(frozen=True, slots=True)
class ContactTimelineEntry:
    key: str
    origin: TimelineOrigin
    kind: str
    title: str
    body: str | None
    outcome: str | None
    occurred_at: datetime | None
    source_record_id: int | None
    entity_type: str
    entity_id: int


@dataclass(frozen=True, slots=True)
class ContactTimelinePage:
    rows: tuple[ContactTimelineEntry, ...]
    next_cursor: str | None
    has_more: bool


__all__ = [name for name in globals() if name.startswith("Contact") or name in {
    "UNSET", "UnsetType", "JsonValue", "CelebrationYearQuality",
    "CaptureQualityValue", "MaterializationStatus", "SortDirection",
    "TimelineCursorV1", "TimelineOrigin", "CONTACT_TOUCH_ACTIVITY_KINDS",
    "encode_timeline_cursor", "decode_timeline_cursor",
    "timeline_position_is_after", "redact_contact_audit_value",
    "canonical_contact_audit_json",
    "canonical_workspace_saved_search_activity_json",
}]
