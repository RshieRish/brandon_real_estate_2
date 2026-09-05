"""Read captured Command note content without changing its archived evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date
from typing import NoReturn

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMNote
from models.command_contacts import (
    CRMContactCapturePosition,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
)
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from services.command_contact_contracts import ContactNoteOccurrence

_TITLE_LIMIT = 500
_BODY_LIMIT = 20_000
_CAPTURE_TIME = re.compile(r"(?:0?[1-9]|1[0-2]):[0-5][0-9] (?:AM|PM)")
_CAPTURE_DATE = re.compile(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})")


class ContactNoteContentError(ValueError):
    """A note payload does not establish bounded, trustworthy note content."""


def _invalid_content() -> NoReturn:
    raise ContactNoteContentError("contact occurrence payload is invalid")


def _note_values(payload_json: object) -> dict[str, object]:
    def reject_nonfinite(_value: str) -> NoReturn:
        _invalid_content()

    try:
        payload = json.loads(payload_json, parse_constant=reject_nonfinite)
    except (TypeError, ValueError, RecursionError):
        raise ContactNoteContentError("contact occurrence payload is invalid") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("values"), dict):
        _invalid_content()
    return payload["values"]


def _structured_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if len(normalized) > limit:
        _invalid_content()
    return normalized


def _is_capture_suffix(line: str) -> bool:
    if line == "Welcome to KWIQ":
        return True
    match = _CAPTURE_DATE.fullmatch(line)
    if match is None:
        return False
    month, day, year = (int(part) for part in match.groups())
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _bounded_raw_lines(value: object) -> list[str]:
    # Even empty body lines consume the body limit through their newline separators.
    if (
        not isinstance(value, list)
        or not 6 <= len(value) <= _BODY_LIMIT + 8
        or any(not isinstance(line, str) for line in value)
        or sum(len(line) + 1 for line in value) > _BODY_LIMIT + 2 * _TITLE_LIMIT + 64
    ):
        _invalid_content()
    return value


def _captured_note_content(raw_lines: object) -> ContactNoteOccurrence:
    lines = _bounded_raw_lines(raw_lines)
    if (
        _CAPTURE_TIME.fullmatch(lines[0]) is None
        or lines[1] not in {"Created", "Updated"}
        or not lines[2].startswith("By ")
        or not lines[2][3:].strip()
        or len(lines[2]) > _TITLE_LIMIT
        or "\n" in lines[2]
        or "\r" in lines[2]
    ):
        _invalid_content()

    end = len(lines)
    if _is_capture_suffix(lines[-1]):
        end -= 1
    if end < 6 or lines[end - 2 : end] != ["Delete", "Edit"]:
        _invalid_content()

    title = lines[3]
    body = "\n".join(lines[4 : end - 2])
    if not title.strip() or len(title) > _TITLE_LIMIT or len(body) > _BODY_LIMIT:
        _invalid_content()
    return ContactNoteOccurrence(kind="note", title=title, body=body)


def _read_note_values(
    values: dict[str, object], *, display_label: object
) -> ContactNoteOccurrence:
    title = _structured_text(values.get("title"), limit=_TITLE_LIMIT)
    body = _structured_text(values.get("body"), limit=_BODY_LIMIT)
    if "raw_lines" in values and (not title or "body" not in values):
        captured = _captured_note_content(values["raw_lines"])
        title = title or captured.title
        if "body" not in values:
            body = captured.body
    if not title:
        title = _structured_text(display_label, limit=_TITLE_LIMIT)
    if not title:
        _invalid_content()
    return ContactNoteOccurrence(kind="note", title=title, body=body)


def read_contact_note_content(
    payload_json: object, *, display_label: object
) -> ContactNoteOccurrence:
    """Prefer explicit fields; recover legacy text only from a complete note capture."""
    return _read_note_values(_note_values(payload_json), display_label=display_label)


async def present_contact_notes(
    db: AsyncSession,
    *,
    contact_id: int,
    notes: Sequence[CRMNote],
) -> list[dict[str, object]]:
    """Clean an unchanged imported note's response using one owned provenance query."""
    if not notes:
        return []

    # Count all links, including incompatible links filtered out by the main query.
    # A conflicting source or note must never become unambiguous through filtering.
    source_link_count = (
        select(func.count(CRMEntitySource.id))
        .where(CRMEntitySource.source_record_id == CRMSourceRecord.id)
        .correlate(CRMSourceRecord)
        .scalar_subquery()
    )
    note_link_count = (
        select(func.count(CRMEntitySource.id))
        .where(
            CRMEntitySource.entity_type == "note",
            CRMEntitySource.entity_id == CRMNote.id,
        )
        .correlate(CRMNote)
        .scalar_subquery()
    )
    with db.no_autoflush:
        rows = (
            await db.execute(
                select(
                    CRMNote.id,
                    CRMSourceRecord.payload_json,
                    CRMSourceRecord.display_label,
                )
                .select_from(CRMNote)
                .join(
                    CRMEntitySource,
                    and_(
                        CRMEntitySource.entity_type == "note",
                        CRMEntitySource.entity_id == CRMNote.id,
                    ),
                )
                .join(
                    CRMSourceRecord,
                    CRMSourceRecord.id == CRMEntitySource.source_record_id,
                )
                .join(
                    CRMContactSourceOccurrence,
                    CRMContactSourceOccurrence.source_record_id == CRMSourceRecord.id,
                )
                .join(
                    CRMContactSectionCapture,
                    CRMContactSectionCapture.id
                    == CRMContactSourceOccurrence.section_capture_id,
                )
                .join(
                    CRMContactCapturePosition,
                    CRMContactCapturePosition.id
                    == CRMContactSectionCapture.capture_position_id,
                )
                .where(
                    CRMNote.contact_id == contact_id,
                    CRMNote.id.in_([note.id for note in notes]),
                    CRMSourceRecord.source_system == "kw_command",
                    CRMSourceRecord.module == "contacts",
                    CRMSourceRecord.record_kind == "contact_note",
                    CRMContactSourceOccurrence.contact_id == contact_id,
                    CRMContactSourceOccurrence.occurrence_ordinal > 0,
                    CRMContactSectionCapture.section_name == "notes",
                    CRMContactCapturePosition.contact_id == contact_id,
                    CRMContactCapturePosition.capture_ordinal > 0,
                    source_link_count == 1,
                    note_link_count == 1,
                )
            )
        ).all()

    notes_by_id = {note.id: note for note in notes}
    display_bodies: dict[int, str] = {}
    for note_id, payload_json, display_label in rows:
        try:
            values = _note_values(payload_json)
            raw_lines = _bounded_raw_lines(values.get("raw_lines"))
            if notes_by_id[note_id].body != "\n".join(raw_lines):
                continue
            _captured_note_content(raw_lines)
            content = _read_note_values(values, display_label=display_label)
        except ContactNoteContentError:
            # Unproven evidence cannot hide or rewrite an existing internal note.
            continue
        if content.body is not None:
            display_bodies[note_id] = (
                f"{content.title}\n\n{content.body}" if content.body else content.title
            )

    return [
        {
            "id": note.id,
            "contact_id": note.contact_id,
            "body": display_bodies.get(note.id, note.body),
            "created_at": note.created_at,
            "updated_at": note.updated_at,
        }
        for note in notes
    ]
