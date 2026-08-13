"""Pure, evidence-preserving extractors for recovered Command contacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit

from models.command_provenance import CaptureQuality
from services.command_archive import html_text
from services.command_provenance import ArchiveArtifactInput


CONTACT_SECTIONS = (
    "timeline",
    "opportunities",
    "smart_plans",
    "notes",
    "saved_searches",
    "tasks_to_do",
    "tasks_completed",
    "tasks_archived",
)

SECTION_RELATIVE_PATHS: Mapping[str, str] = MappingProxyType(
    {
        "timeline": "timeline.json",
        "opportunities": "opportunities.json",
        "smart_plans": "smartplans.json",
        "notes": "notes.json",
        "saved_searches": "saved_searches.json",
        "tasks_to_do": "tasks/to_do.json",
        "tasks_completed": "tasks/completed.json",
        "tasks_archived": "tasks/archived.json",
    }
)

_CONTACT_ROOT = "kw_command_repaired/contacts"
_PLACEHOLDERS = frozenset({"", "--", "—", "n/a", "none", "null"})
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_OVERLAY_BOUNDARIES = (
    "\nWelcome to KWIQ\n",
    "\nKWIQ\nChat\nHistory\n",
    "\nAI Information Accuracy\n",
    "\nNotifications\nUnread\nRead\n",
    "\n- heading \"Notifications\"",
)
_EMPTY_MARKERS = (
    "no activities yet",
    "no opportunities",
    "no smartplans",
    "no notes yet",
    "no saved searches yet",
    "no to do tasks",
    "no completed tasks",
    "no archived tasks",
)
_EVENT_KINDS = frozenset(
    {"CALL", "EMAIL", "TEXT", "SMARTPLANS", "NOTE", "SYSTEM", "CONTACT"}
)


class ContactParseError(ValueError):
    """Raised when contact evidence is missing, ambiguous, or malformed."""


@dataclass(frozen=True, slots=True)
class ParsedCelebration:
    month: int | None
    day: int | None
    year: int | None
    year_quality: Literal["verified", "yearless", "sentinel", "unknown"]
    raw: str | None


@dataclass(frozen=True, slots=True)
class ParsedOccurrence:
    values: Mapping[str, object]
    stable_id: str | None
    display_label: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _immutable_mapping(self.values))


@dataclass(frozen=True, slots=True)
class ParsedContactProfile:
    ordinal: int
    capture_ordinal: str
    source_contact_id: str
    source_url: str
    display_name: str
    legal_name: str | None
    preferred_name: str | None
    primary_email: str | None
    primary_phone: str | None
    birthday: ParsedCelebration
    anniversary: ParsedCelebration
    captured_at: datetime | None
    capture_quality: CaptureQuality
    artifact_paths: tuple[str, ...]
    profile_source: Literal["structured_json", "detail_html", "section_capture"]
    raw_fields: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_fields", _immutable_mapping(self.raw_fields))


@dataclass(frozen=True, slots=True)
class ParsedSection:
    section: str
    captured_at: datetime | None
    capture_quality: CaptureQuality
    text_source: Literal["visible_text", "accessibility_snapshot"]
    exposed_text: str
    is_empty: bool
    limitations: tuple[str, ...]
    occurrences: tuple[ParsedOccurrence, ...]
    artifact_path: str
    raw_fields: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_fields", _immutable_mapping(self.raw_fields))


def extract_source_contact_id(url: str) -> str:
    """Extract a provider ID only from the canonical authenticated contact URL."""
    if not isinstance(url, str):
        raise ContactParseError("contact URL must be a string")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "console.command.kw.com"
        or parsed.fragment
    ):
        raise ContactParseError(f"noncanonical Command contact URL: {url!r}")
    match = re.fullmatch(r"/command/contacts/([0-9a-f]{24})", parsed.path)
    if match is None:
        raise ContactParseError(f"noncanonical Command contact URL: {url!r}")
    return match.group(1)


def strip_application_boilerplate(text: str) -> str:
    """Remove overlays after their first known boundary without stripping the app header."""
    if not isinstance(text, str):
        raise ContactParseError("captured text must be a string")
    indexes = [index for marker in _OVERLAY_BOUNDARIES if (index := text.find(marker)) >= 0]
    return text[: min(indexes)].strip() if indexes else text.strip()


def canonical_occurrence_key(values: Mapping[str, object], ordinal: int) -> str:
    """Hash canonical row values and their ordinal within the rendered section."""
    if not isinstance(values, Mapping):
        raise ContactParseError("occurrence values must be a mapping")
    if type(ordinal) is not int or ordinal < 1:
        raise ContactParseError("occurrence ordinal must be a positive integer")
    try:
        canonical = json.dumps(
            {"ordinal": ordinal, "values": _json_value(values)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ContactParseError("occurrence values must be canonical JSON") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_contact_profile(
    ordinal: int,
    artifacts: Mapping[str, ArchiveArtifactInput],
) -> ParsedContactProfile:
    """Parse one position with structured evidence taking precedence over fallbacks."""
    capture_ordinal = _capture_ordinal(ordinal)
    nested_path = f"{_CONTACT_ROOT}/nested/{capture_ordinal}/contact.json"
    detail_path = f"{_CONTACT_ROOT}/details/{capture_ordinal}.html"
    section_paths = tuple(
        f"{_CONTACT_ROOT}/sections/{capture_ordinal}/{SECTION_RELATIVE_PATHS[name]}"
        for name in CONTACT_SECTIONS
    )
    canonical_sections = [_json_mapping(_require(artifacts, path)) for path in section_paths]

    source_ids = {
        extract_source_contact_id(value)
        for section_payload in canonical_sections
        if isinstance((value := section_payload.get("url")), str)
    }
    structured: Mapping[str, object] | None = None
    if nested_path in artifacts:
        structured = _json_mapping(artifacts[nested_path])
        structured_id = structured.get("id")
        if not isinstance(structured_id, str) or not re.fullmatch(
            r"[0-9a-f]{24}", structured_id
        ):
            raise ContactParseError(
                f"structured contact {capture_ordinal} has invalid provider ID"
            )
        source_ids.add(structured_id)
    if len(source_ids) != 1:
        raise ContactParseError(
            f"position {capture_ordinal} has ambiguous source contact IDs: "
            + ", ".join(sorted(source_ids))
        )
    source_contact_id = next(iter(source_ids))

    section_payload = canonical_sections[0]
    source_url = section_payload.get("url")
    if not isinstance(source_url, str):
        raise ContactParseError(f"position {capture_ordinal} has no canonical URL")

    detail_text: str | None = None
    if detail_path in artifacts:
        detail_text = strip_application_boilerplate(
            html_text(_content_text(artifacts[detail_path]))
        )
    fallback_text, _ = _capture_text(section_payload)
    fallback_text = strip_application_boilerplate(fallback_text)
    raw_display = {
        "name": _prefer_present(
            _contact_heading(detail_text, section_payload) if detail_text else None,
            _contact_heading(fallback_text, section_payload),
        ),
        "primary_email": _prefer_present(
            _after_label(detail_text, "Primary Email") if detail_text else None,
            _after_label(fallback_text, "Primary Email"),
        ),
        "primary_phone": _prefer_present(
            _after_label(detail_text, "Primary Phone") if detail_text else None,
            _after_label(fallback_text, "Primary Phone"),
        ),
        "birthday": _prefer_present(
            _after_label(detail_text, "Birthday") if detail_text else None,
            _after_label(fallback_text, "Birthday"),
        ),
        "anniversary": _prefer_present(
            _after_label(detail_text, "Home Anniversary") if detail_text else None,
            _after_label(fallback_text, "Home Anniversary"),
        ),
        "legal_name": _prefer_present(
            _after_label(detail_text, "Legal Name") if detail_text else None,
            _after_label(fallback_text, "Legal Name"),
        ),
    }

    if structured is not None:
        name = _mapping(structured.get("name"))
        legal_name = _nonplaceholder(name.get("legal"))
        preferred_name = _nonplaceholder(name.get("preferred"))
        display_name = preferred_name or legal_name or raw_display["name"]
        email = _mapping(_mapping(structured.get("emails")).get("primary"))
        phone = _mapping(_mapping(structured.get("phones")).get("primary"))
        primary_email = _nonplaceholder(email.get("email"))
        primary_phone = _nonplaceholder(
            phone.get("ISOPhoneNumber") or phone.get("phone")
        )
        personal = _mapping(structured.get("personalInfo"))
        birthday_value = _mapping(personal.get("dateOfBirth"))
        anniversary_value = _mapping(personal.get("homeAnniversary"))
        birthday = _parse_structured_celebration(birthday_value)
        anniversary = _parse_structured_celebration(anniversary_value)
        profile_source: Literal[
            "structured_json", "detail_html", "section_capture"
        ] = "structured_json"
    else:
        display_name = raw_display["name"]
        legal_name = _nonplaceholder(raw_display["legal_name"])
        preferred_name = None
        primary_email = _nonplaceholder(raw_display["primary_email"])
        primary_phone = _nonplaceholder(raw_display["primary_phone"])
        birthday = _parse_display_celebration(raw_display["birthday"])
        anniversary = _parse_display_celebration(raw_display["anniversary"])
        profile_source = (
            "detail_html"
            if detail_text is not None
            and any(
                _after_label(detail_text, label) is not None
                for label in ("Primary Email", "Primary Phone", "Birthday", "Legal Name")
            )
            else "section_capture"
        )

    if not display_name:
        raise ContactParseError(f"position {capture_ordinal} has no contact name")
    captured_at = _parse_datetime(section_payload.get("captured_at"))
    artifact_paths = tuple(
        path
        for path in (nested_path, detail_path, section_paths[0])
        if path in artifacts
    )
    return ParsedContactProfile(
        ordinal=ordinal,
        capture_ordinal=capture_ordinal,
        source_contact_id=source_contact_id,
        source_url=source_url,
        display_name=display_name,
        legal_name=legal_name,
        preferred_name=preferred_name,
        primary_email=primary_email,
        primary_phone=primary_phone,
        birthday=birthday,
        anniversary=anniversary,
        captured_at=captured_at,
        capture_quality=CaptureQuality.COMPLETE,
        artifact_paths=artifact_paths,
        profile_source=profile_source,
        raw_fields={
            "structured": structured,
            **raw_display,
        },
    )


def parse_section_capture(
    profile: ParsedContactProfile,
    section: str,
    artifact: ArchiveArtifactInput,
) -> ParsedSection:
    """Parse one canonical section while retaining its complete exposed text."""
    if section not in SECTION_RELATIVE_PATHS:
        raise ContactParseError(f"unknown contact section: {section!r}")
    expected_path = (
        f"{_CONTACT_ROOT}/sections/{profile.capture_ordinal}/"
        f"{SECTION_RELATIVE_PATHS[section]}"
    )
    if artifact.source_path != expected_path:
        raise ContactParseError(
            f"section {section!r} requires exact path {expected_path!r}"
        )
    payload = _json_mapping(artifact)
    url = payload.get("url")
    if not isinstance(url, str) or extract_source_contact_id(url) != profile.source_contact_id:
        raise ContactParseError(
            f"section {section!r} does not belong to contact "
            f"{profile.source_contact_id}"
        )
    raw_text, text_source = _capture_text(payload)
    exposed_text = strip_application_boilerplate(raw_text)
    quality_raw = payload.get("capture_quality", CaptureQuality.COMPLETE.value)
    try:
        quality = CaptureQuality(quality_raw)
    except (TypeError, ValueError) as exc:
        raise ContactParseError(
            f"section {section!r} has invalid capture quality {quality_raw!r}"
        ) from exc
    limitations_raw = payload.get("limitations", ())
    if not isinstance(limitations_raw, Sequence) or isinstance(
        limitations_raw, str | bytes
    ):
        raise ContactParseError(f"section {section!r} limitations must be a list")
    limitations = tuple(str(value) for value in limitations_raw)
    occurrences = _parse_occurrences(section, payload, exposed_text)
    is_empty = not occurrences and any(
        marker in exposed_text.casefold() for marker in _EMPTY_MARKERS
    )
    if not occurrences and not is_empty and quality is CaptureQuality.COMPLETE:
        quality = CaptureQuality.PARTIAL
        limitations = (*limitations, "rendered rows were not structurally distinguishable")
    return ParsedSection(
        section=section,
        captured_at=_parse_datetime(payload.get("captured_at")),
        capture_quality=quality,
        text_source=text_source,
        exposed_text=exposed_text,
        is_empty=is_empty,
        limitations=limitations,
        occurrences=occurrences,
        artifact_path=artifact.source_path,
        raw_fields={
            key: value
            for key, value in payload.items()
            if key not in {"visible_text", "accessibility_snapshot"}
        },
    )


def _parse_occurrences(
    section: str,
    payload: Mapping[str, object],
    exposed_text: str,
) -> tuple[ParsedOccurrence, ...]:
    rows = payload.get("rows")
    if rows is not None:
        if not isinstance(rows, list):
            raise ContactParseError(f"section {section!r} rows must be a list")
        parsed = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, Mapping):
                raise ContactParseError(
                    f"section {section!r} row {index} must be an object"
                )
            values = dict(row)
            parsed.append(
                ParsedOccurrence(
                    values=values,
                    stable_id=_stable_row_id(values),
                    display_label=_row_label(section, values, index),
                )
            )
        return tuple(parsed)

    if section.startswith("tasks_"):
        return _task_occurrences(section, exposed_text)
    if section == "smart_plans":
        return _smart_plan_occurrences(exposed_text)
    if section == "timeline":
        return _timeline_occurrences(exposed_text)
    if section == "notes":
        return _note_occurrences(exposed_text)
    if section == "opportunities":
        return _opportunity_occurrences(exposed_text)
    if section == "saved_searches":
        return _saved_search_occurrences(exposed_text)
    return ()


def _task_occurrences(section: str, text: str) -> tuple[ParsedOccurrence, ...]:
    state = section.removeprefix("tasks_")
    header = {
        "to_do": "TASK\nASSIGNED TO\nPRIORITY\nDUE DATE\nCREATED BY\n",
        "completed": "TASK\nASSIGNED TO\nPRIORITY\nDUE DATE\nCREATED BY\n",
        "archived": "TASK\nASSIGNED TO\nPRIORITY\nDATE ARCHIVED\nDUE DATE\nARCHIVED BY\n",
    }[state]
    if header not in text:
        return ()
    lines = [line.strip() for line in text.split(header, 1)[1].splitlines() if line.strip()]
    rows: list[ParsedOccurrence] = []
    if state == "archived":
        index = 0
        while index + 6 < len(lines):
            if not (_is_us_date(lines[index + 4]) and _is_us_date(lines[index + 5])):
                index += 1
                continue
            values = {
                "title": lines[index],
                "assigned_to": lines[index + 2],
                "priority": lines[index + 3],
                "archived_date": lines[index + 4],
                "due_date": lines[index + 5],
                "archived_by": lines[index + 6],
                "state": state,
            }
            rows.append(ParsedOccurrence(values, None, lines[index]))
            index += 7
        return tuple(rows)
    for index, line in enumerate(lines):
        if _is_us_date(line) and index >= 4:
            title = lines[index - 4]
            if title.casefold().startswith("no "):
                continue
            values = {
                "title": title,
                "assigned_to": lines[index - 2],
                "priority": lines[index - 1],
                "due_date": line,
                "state": state,
            }
            rows.append(ParsedOccurrence(values, None, title))
    return tuple(rows)


def _smart_plan_occurrences(text: str) -> tuple[ParsedOccurrence, ...]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = []
    for index, line in enumerate(lines):
        match = re.fullmatch(r"(\d+) days? · (\d+) touches", line)
        if match is None or index == 0:
            continue
        name = lines[index - 1]
        values = {
            "name": name,
            "duration_days": int(match.group(1)),
            "touches": int(match.group(2)),
            "status": lines[index + 1] if index + 1 < len(lines) else None,
        }
        if index + 2 < len(lines) and lines[index + 2].startswith("Last executed "):
            values["last_executed_raw"] = lines[index + 2].removeprefix(
                "Last executed "
            )
        rows.append(ParsedOccurrence(values, None, name))
    return tuple(rows)


def _timeline_occurrences(text: str) -> tuple[ParsedOccurrence, ...]:
    marker = "Most Recent\n"
    body = text.split(marker, 1)[1] if marker in text else text
    lines = [_snapshot_value(line) for line in body.splitlines()]
    lines = [line for line in lines if line]
    event_indexes = [
        index for index, line in enumerate(lines) if line.upper() in _EVENT_KINDS
    ]
    rows = []
    for occurrence_index, start in enumerate(event_indexes):
        end = event_indexes[occurrence_index + 1] if occurrence_index + 1 < len(event_indexes) else len(lines)
        raw_lines = lines[start:end]
        if len(raw_lines) < 2:
            continue
        values = {"kind": raw_lines[0].upper(), "raw_lines": raw_lines}
        label = next(
            (
                value
                for value in raw_lines[1:]
                if value not in {"Sent", "Received", "Added", "Ended", "Created"}
                and not value.startswith("By ")
                and not re.fullmatch(r"\d{1,2}:\d{2} [AP]M", value)
            ),
            raw_lines[0].title(),
        )
        rows.append(ParsedOccurrence(values, None, label))
    return tuple(rows)


def _opportunity_occurrences(text: str) -> tuple[ParsedOccurrence, ...]:
    lines = [_snapshot_value(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    rows = []
    for index, line in enumerate(lines):
        if line != "Stage" or index == 0 or index + 1 >= len(lines):
            continue
        title_index = index - 1
        if title_index > 0 and _looks_like_date(lines[title_index - 1]):
            captured_date = lines[title_index - 1]
        else:
            captured_date = None
        title = lines[title_index]
        if title in {"Create Opportunity", "All Opportunities"}:
            continue
        values: dict[str, object] = {
            "title": title,
            "date_raw": captured_date,
            "stage": lines[index + 1],
        }
        window = lines[index + 2 : index + 10]
        for label in ("Phase", "Budget", "Commission"):
            if label in window:
                label_index = window.index(label)
                if label_index + 1 < len(window):
                    values[label.casefold()] = window[label_index + 1]
        rows.append(ParsedOccurrence(values, None, title))
    return tuple(rows)


def _saved_search_occurrences(text: str) -> tuple[ParsedOccurrence, ...]:
    lines = [_snapshot_value(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    rows = []
    for index, line in enumerate(lines):
        if not line.startswith("Created by:") or index == 0:
            continue
        name = lines[index - 1]
        if name == "Create Saved Search":
            continue
        values: dict[str, object] = {
            "name": name,
            "created_by": line.removeprefix("Created by:").strip(),
        }
        window = lines[index + 1 : index + 12]
        for label in ("Price", "Beds", "Baths"):
            if label in window:
                label_index = window.index(label)
                if label_index + 1 < len(window):
                    values[label.casefold()] = window[label_index + 1]
        rows.append(ParsedOccurrence(values, None, name))
    return tuple(rows)


def _note_occurrences(text: str) -> tuple[ParsedOccurrence, ...]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = []
    for index, line in enumerate(lines):
        if line != "NOTE":
            continue
        tail = lines[index + 1 : index + 8]
        values = {"raw_lines": tail}
        label = next(
            (
                value
                for value in tail
                if value not in {"Created", "Delete", "Edit"}
                and not value.startswith("By ")
                and not re.fullmatch(r"\d{1,2}:\d{2} [AP]M", value)
            ),
            "Note",
        )
        rows.append(ParsedOccurrence(values, None, label))
    return tuple(rows)


def _parse_structured_celebration(value: Mapping[str, object]) -> ParsedCelebration:
    raw = _raw_string(value.get("full"))
    month = _integer(value.get("month"))
    day = _integer(value.get("day"))
    year = _integer(value.get("year"))
    if (month is None or day is None) and raw:
        parts = re.fullmatch(r"(?:(\d{4})-)?(\d{2})-(\d{2})", raw)
        if parts:
            year = year if year is not None else _integer(parts.group(1))
            month = _integer(parts.group(2))
            day = _integer(parts.group(3))
    if not _valid_month_day(month, day):
        return ParsedCelebration(None, None, None, "unknown", raw)
    assert month is not None and day is not None
    if year == 1900:
        return ParsedCelebration(month, day, None, "sentinel", raw)
    if year is None:
        return ParsedCelebration(month, day, None, "yearless", raw)
    if not _valid_date(year, month, day):
        return ParsedCelebration(month, day, None, "unknown", raw)
    return ParsedCelebration(month, day, year, "verified", raw)


def _parse_display_celebration(value: object) -> ParsedCelebration:
    raw = _raw_string(value)
    normalized = _nonplaceholder(raw)
    if normalized is None:
        return ParsedCelebration(None, None, None, "unknown", raw)
    match = re.fullmatch(
        r"([A-Za-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?",
        normalized,
    )
    if match is None:
        return ParsedCelebration(None, None, None, "unknown", raw)
    month = _MONTHS.get(match.group(1).casefold())
    day = int(match.group(2))
    year = int(match.group(3)) if match.group(3) else None
    if not _valid_month_day(month, day):
        return ParsedCelebration(None, None, None, "unknown", raw)
    assert month is not None
    if year == 1900:
        return ParsedCelebration(month, day, None, "sentinel", raw)
    if year is None:
        return ParsedCelebration(month, day, None, "yearless", raw)
    if not _valid_date(year, month, day):
        return ParsedCelebration(month, day, None, "unknown", raw)
    return ParsedCelebration(month, day, year, "verified", raw)


def _capture_text(
    payload: Mapping[str, object],
) -> tuple[str, Literal["visible_text", "accessibility_snapshot"]]:
    visible = payload.get("visible_text")
    if isinstance(visible, str) and visible.strip():
        return visible, "visible_text"
    snapshot = payload.get("accessibility_snapshot")
    if isinstance(snapshot, str) and snapshot.strip():
        return snapshot, "accessibility_snapshot"
    raise ContactParseError("canonical section has no readable captured text")


def _contact_heading(text: str, payload: Mapping[str, object]) -> str | None:
    match = re.search(r"(?:^|\n)Search Contacts\n([^\n]+)", text)
    if match:
        return _nonplaceholder(match.group(1))
    snapshot_match = re.search(
        r'(?:^|\n)- heading "[^"]+" \[level=2\]:\n\s+- text: ([^\n]+)',
        text,
    )
    if snapshot_match:
        return _nonplaceholder(snapshot_match.group(1))
    direct_heading = re.search(
        r'(?:^|\n)- heading "([^"]+)" \[level=2\](?::|\n|$)',
        text,
    )
    if direct_heading:
        value = re.sub(
            r"\s+[\ue000-\uf8ff].*$",
            "",
            direct_heading.group(1),
        )
        return _nonplaceholder(value)
    title = payload.get("title")
    if isinstance(title, str):
        return _nonplaceholder(title.removesuffix(" | Command"))
    return None


def _after_label(text: str, label: str) -> str | None:
    match = re.search(rf"(?:^|\n){re.escape(label)}\n([^\n]+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    snapshot_match = re.search(
        rf'(?:^|\n)- (?:paragraph|generic): {re.escape(label)}\n'
        rf'(?:\s+- )?(?:paragraph|generic|text):\s*"?([^"\n]+)"?'
        rf'|(?:^|\n)- (?:paragraph|generic): {re.escape(label)}\n'
        rf'- button "([^"]+)"',
        text,
        re.IGNORECASE,
    )
    if snapshot_match:
        return next(
            value.strip()
            for value in snapshot_match.groups()
            if value is not None
        )
    return None


def _json_mapping(artifact: ArchiveArtifactInput) -> Mapping[str, object]:
    try:
        value = json.loads(_content_text(artifact))
    except json.JSONDecodeError as exc:
        raise ContactParseError(f"invalid JSON artifact: {artifact.source_path}") from exc
    if not isinstance(value, Mapping):
        raise ContactParseError(f"JSON artifact must contain an object: {artifact.source_path}")
    return value


def _content_text(artifact: ArchiveArtifactInput) -> str:
    if artifact.content_bytes is None:
        raise ContactParseError(f"artifact bytes are unavailable: {artifact.source_path}")
    try:
        return artifact.content_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContactParseError(f"artifact is not UTF-8: {artifact.source_path}") from exc


def _require(
    artifacts: Mapping[str, ArchiveArtifactInput], source_path: str
) -> ArchiveArtifactInput:
    try:
        return artifacts[source_path]
    except KeyError as exc:
        raise ContactParseError(f"missing canonical section artifact: {source_path}") from exc


def _capture_ordinal(ordinal: int) -> str:
    if type(ordinal) is not int or ordinal < 1 or ordinal > 9_999_999:
        raise ContactParseError("capture ordinal must be between 1 and 9999999")
    return f"{ordinal:07d}"


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContactParseError(f"invalid captured_at value: {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContactParseError(f"invalid captured_at value: {value!r}") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _nonplaceholder(value: object) -> str | None:
    raw = _raw_string(value)
    return None if raw is None or raw.casefold() in _PLACEHOLDERS else raw


def _prefer_present(primary: str | None, fallback: str | None) -> str | None:
    return primary if primary is not None else fallback


def _raw_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) else None


def _integer(value: object) -> int | None:
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _valid_month_day(month: int | None, day: int | None) -> bool:
    return month is not None and day is not None and _valid_date(2000, month, day)


def _valid_date(year: int, month: int, day: int) -> bool:
    try:
        datetime(year, month, day)
    except ValueError:
        return False
    return True


def _stable_row_id(values: Mapping[str, object]) -> str | None:
    for key in (
        "id",
        "_id",
        "note_id",
        "task_id",
        "plan_id",
        "opportunity_id",
        "search_id",
        "event_id",
    ):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if type(value) is int:
            return str(value)
    return None


def _row_label(section: str, values: Mapping[str, object], ordinal: int) -> str:
    for key in ("title", "name", "subject", "body", "kind"):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{section.replace('_', ' ').title()} occurrence {ordinal}"


def _is_us_date(value: str) -> bool:
    return re.fullmatch(r"\d{2}/\d{2}/\d{4}", value) is not None


def _looks_like_date(value: str) -> bool:
    return bool(
        _is_us_date(value)
        or re.fullmatch(r"[A-Za-z]{3,9} \d{1,2}, \d{4}", value)
    )


def _snapshot_value(line: str) -> str:
    value = line.strip()
    match = re.match(
        r'- (?:generic|paragraph|text|strong):\s*"?([^"\n]+)"?$',
        value,
    )
    if match:
        return match.group(1).strip()
    heading = re.match(r'- heading "([^"]+)" \[level=\d+\]', value)
    if heading:
        return heading.group(1).strip()
    link = re.match(r'- link "([^"]+)"', value)
    if link:
        return link.group(1).strip()
    return value if not value.startswith(("- ", "/url:")) else ""


def _immutable_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): _immutable_value(item) for key, item in value.items()})


def _immutable_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _immutable_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_immutable_value(item) for item in value)
    return value


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value
