"""Bounded, non-duplicating aggregation for one internal CRM contact timeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.booking import Booking
from models.command import CRMActivity, CRMArchiveArtifact, CRMContact
from models.command_contacts import (
    CRMContactCapturePosition,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
    CRMContactTimelineEvent,
)
from models.command_provenance import CRMSourceRecord, CRMSourceRecordArtifact
from models.lead import Lead
from services.command_contact_capture_content import (
    CapturedTimeline,
    capture_coordinates_match,
    has_embedded_timeline_activity,
    read_timeline_capture,
    source_raw_lines,
)
from services.command_contact_contracts import (
    ContactTimelineEntry,
    ContactTimelinePage,
    TimelineCursorV1,
    TimelineOrigin,
    decode_timeline_cursor,
    encode_timeline_cursor,
    timeline_position_is_after,
)
from services.command_contact_identity import canonical_email
from services.command_contact_timeline_html import (
    TimelineHTMLActivity,
    TimelineHTMLFacts,
    match_timeline_html_event,
    parse_timeline_html,
    recover_timeline_navigation_archive_tail,
    recover_timeline_navigation_tail,
    timeline_legacy_projection,
    verified_timeline_fragment_tail_lines,
    verified_timeline_tail_lines,
)
from services.command_contact_timeline_snapshot import parse_timeline_snapshot

_ORIGIN_RANK: dict[TimelineOrigin, Literal[0, 1, 2, 3]] = {
    TimelineOrigin.RECOVERED: 0,
    TimelineOrigin.INTERNAL_CRM: 1,
    TimelineOrigin.LEGACY_LEAD: 2,
    TimelineOrigin.BOOKING: 3,
}
_TECHNICAL_ACTIVITY_KINDS = (
    "archive_contact_imported",
    "archive_timeline_capture",
)


class ContactNotFound(LookupError):
    """The requested internal contact does not exist."""


class ContactTimelineIntegrityError(RuntimeError):
    """A source-linked timeline row violates ownership/type invariants."""


@dataclass(frozen=True, slots=True)
class _TimelineCandidate:
    entry: ContactTimelineEntry
    null_rank: Literal[0, 1]
    origin_rank: Literal[0, 1, 2, 3]
    sort_at: datetime | None


async def list_contact_timeline(
    db: AsyncSession,
    contact_id: int,
    *,
    cursor: str | None,
    page_size: int,
) -> ContactTimelinePage:
    """List a deterministic, cursor-paginated union of contact history origins."""
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("page_size must be an integer between 1 and 100")
    decoded_cursor = decode_timeline_cursor(cursor) if cursor is not None else None
    if type(contact_id) is not int or contact_id <= 0:
        raise ContactNotFound("contact does not exist")

    contact_row = (
        await db.execute(
            select(CRMContact, Lead)
            .outerjoin(Lead, Lead.id == CRMContact.lead_id)
            .where(CRMContact.id == contact_id)
            .limit(1)
        )
    ).one_or_none()
    if contact_row is None:
        raise ContactNotFound("contact does not exist")
    contact, lead = contact_row
    if contact.lead_id is not None and lead is None:
        raise ContactTimelineIntegrityError("linked lead is unavailable")
    _require_contact_email_integrity(contact)
    await _require_recovered_source_integrity(db, contact_id=contact.id)
    await _require_activity_source_integrity(db, contact_id=contact.id)

    fetch_limit = page_size + 1
    recovered, filtered_capture_count = await _recovered_candidates(
        db,
        contact_id=contact.id,
        cursor=decoded_cursor,
        limit=fetch_limit,
    )
    activities = await _activity_candidates(
        db,
        contact_id=contact.id,
        cursor=decoded_cursor,
        limit=fetch_limit,
    )
    legacy = _legacy_lead_candidates(
        lead=lead,
        cursor=decoded_cursor,
    )
    bookings = await _booking_candidates(
        db,
        contact=contact,
        cursor=decoded_cursor,
        limit=fetch_limit,
    )

    recovered_source_ids = {
        candidate.entry.source_record_id
        for candidate in recovered
        if candidate.entry.source_record_id is not None
    }
    unique_activities = tuple(
        candidate
        for candidate in activities
        if candidate.entry.source_record_id not in recovered_source_ids
    )
    combined = sorted(
        (*recovered, *unique_activities, *legacy, *bookings),
        key=_candidate_sort_key,
    )
    has_more = len(combined) > page_size
    emitted = tuple(combined[:page_size])
    next_cursor = None
    if has_more and emitted:
        last = emitted[-1]
        next_cursor = encode_timeline_cursor(
            TimelineCursorV1(
                null_rank=last.null_rank,
                occurred_at=last.sort_at,
                origin_rank=last.origin_rank,
                entity_id=last.entry.entity_id,
            )
        )
    return ContactTimelinePage(
        rows=tuple(candidate.entry for candidate in emitted),
        next_cursor=next_cursor,
        has_more=has_more,
        filtered_capture_count=filtered_capture_count,
    )


async def count_contact_bookings(
    db: AsyncSession,
    contact_id: int,
) -> int:
    """Count bookings using the exact ownership rules of the timeline."""
    if type(contact_id) is not int or contact_id <= 0:
        raise ContactNotFound("contact does not exist")
    with db.no_autoflush:
        contact_row = (
            await db.execute(
                select(CRMContact, Lead)
                .outerjoin(Lead, Lead.id == CRMContact.lead_id)
                .where(CRMContact.id == contact_id)
                .limit(1)
            )
        ).one_or_none()
        if contact_row is None:
            raise ContactNotFound("contact does not exist")
        contact, lead = contact_row
        if contact.lead_id is not None and lead is None:
            raise ContactTimelineIntegrityError("linked lead is unavailable")
        _require_contact_email_integrity(contact)
        if contact.lead_id is not None:
            return await _require_lead_booking_email_integrity(
                db, lead_id=contact.lead_id
            )
        if not await _owns_unique_email(db, contact):
            return 0
        normalized = canonical_email(contact.email)
        assert normalized is not None
        return await _count_email_bookings_with_integrity(
            db, normalized_email=normalized
        )


async def _count_email_bookings_with_integrity(
    db: AsyncSession,
    *,
    normalized_email: str,
) -> int:
    last_scheduled_at: datetime | None = None
    last_id = 0
    count = 0
    batch_size = 1_000
    while True:
        statement = select(
            Booking.id,
            Booking.email,
            Booking.normalized_email,
            Booking.scheduled_at,
        ).where(
            Booking.lead_id.is_(None),
            Booking.normalized_email == normalized_email,
        )
        if last_scheduled_at is not None:
            statement = statement.where(
                or_(
                    Booking.scheduled_at > last_scheduled_at,
                    and_(
                        Booking.scheduled_at == last_scheduled_at,
                        Booking.id > last_id,
                    ),
                )
            )
        rows = (
            await db.execute(
                statement.order_by(Booking.scheduled_at.asc(), Booking.id.asc()).limit(
                    batch_size
                )
            )
        ).all()
        if any(canonical_email(row.email) != row.normalized_email for row in rows):
            raise ContactTimelineIntegrityError(
                "booking email normalization is invalid"
            )
        count += len(rows)
        if not rows or len(rows) < batch_size:
            return count
        last_scheduled_at = rows[-1].scheduled_at
        last_id = rows[-1].id


async def _recovered_candidates(
    db: AsyncSession,
    *,
    contact_id: int,
    cursor: TimelineCursorV1 | None,
    limit: int,
) -> tuple[tuple[_TimelineCandidate, ...], int]:
    origin = TimelineOrigin.RECOVERED
    # Read in bounded capture-order batches: the date heading belongs to the
    # following activity, not the row to which the old parser appended it.
    # Keep only the requested top-N candidates in memory; never mutate captures.
    batch_size = 1_000
    after: tuple[int, int, int] | None = None
    section_id: int | None = None
    html_evidence: tuple[TimelineHTMLFacts, frozenset[int]] | None = None
    html_loaded = False
    html_index = 0
    selected: list[_TimelineCandidate] = []
    filtered_capture_count = 0
    while True:
        statement = (
            select(
                CRMContactTimelineEvent,
                CRMSourceRecord,
                CRMContactSourceOccurrence.section_capture_id,
                CRMContactSourceOccurrence.occurrence_ordinal,
                CRMContactCapturePosition.source_contact_id,
                CRMContactCapturePosition.capture_ordinal,
            )
            .join(
                CRMSourceRecord,
                CRMSourceRecord.id == CRMContactTimelineEvent.source_record_id,
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
            .where(CRMContactTimelineEvent.contact_id == contact_id)
        )
        section = CRMContactSourceOccurrence.section_capture_id
        ordinal = CRMContactSourceOccurrence.occurrence_ordinal
        entity = CRMContactTimelineEvent.id
        if after is not None:
            statement = statement.where(
                or_(
                    section > after[0],
                    and_(section == after[0], ordinal > after[1]),
                    and_(section == after[0], ordinal == after[1], entity > after[2]),
                )
            )
        rows = (
            await db.execute(
                statement.order_by(section, ordinal, entity).limit(batch_size)
            )
        ).all()
        for row, source, row_section, row_ordinal, provider_id, capture_ordinal in rows:
            if row_section != section_id:
                section_id = row_section
                html_evidence, html_loaded, html_index = None, False, 0
            raw = (
                source_raw_lines(source.payload_json)
                if source.parser_version == "contacts-v1"
                else None
            )
            parsed = (
                read_timeline_capture(raw, None, verified_activity=True)
                if raw is not None
                else None
            )
            contains_structural_activity = False
            if raw is not None and not capture_coordinates_match(
                source.payload_json,
                source_contact_id=provider_id,
                capture_ordinal=capture_ordinal,
                occurrence_ordinal=row_ordinal,
            ):
                raise ContactTimelineIntegrityError(
                    "timeline capture source ownership is invalid"
                )
            if raw is not None and not html_loaded:
                html_evidence = await _capture_timeline_structure(
                    db, section_id=row_section, capture_ordinal=capture_ordinal
                )
                html_loaded = True
            if raw is not None and html_evidence is not None:
                facts, linked_sources = html_evidence
                if source.id in linked_sources and parsed is not None and parsed.hidden:
                    normalized_raw = " ".join(" ".join(raw).split()).casefold()
                    # A verified activity with an unreadable clock is not pure
                    # navigation. Keep an explicit review state, not false empty.
                    contains_structural_activity = any(
                        activity.text
                        and f" {activity.text.casefold()} " in f" {normalized_raw} "
                        for activity in facts.activities
                    )
                group = (
                    (
                        recover_timeline_navigation_tail(facts, raw)
                        or recover_timeline_navigation_archive_tail(facts, raw)
                    )
                    if source.id in linked_sources
                    and parsed is not None
                    and parsed.hidden
                    else None
                )
                if group is not None and group.first_activity_index >= html_index:
                    first_activity = facts.activities[group.first_activity_index]
                    parsed = CapturedTimeline(
                        title=(
                            group.lines[0]
                            if group.activity_count == 1
                            else f"{group.activity_count} recovered activities"
                        ),
                        body="\n".join(group.lines),
                        captured_date=first_activity.day,
                        recognized=True,
                        kind=(
                            first_activity.data_test.removeprefix("timeline-").replace(
                                "-", "_"
                            )
                            if group.activity_count == 1
                            else "captured_activity_group"
                        ),
                    )
                    html_index = group.first_activity_index + group.activity_count
                matched = (
                    match_timeline_html_event(facts, raw, start_index=html_index)
                    if source.id in linked_sources
                    else None
                )
                legacy_facts = timeline_legacy_projection(facts)
                legacy_match = (
                    match_timeline_html_event(legacy_facts, raw, start_index=html_index)
                    if source.id in linked_sources
                    else None
                )
                # The historical scalar reader omitted only identified quoted
                # generic values. Both interpretations must agree on identity;
                # an ambiguous projection cannot consume another event's date.
                if (
                    matched is not None
                    and legacy_match is not None
                    and matched.index != legacy_match.index
                ):
                    matched = None
                    legacy_match = None
                matched = matched or legacy_match
                if matched is not None:
                    verified_lines = _verified_activity_lines(
                        facts, facts.activities[matched.index], raw
                    )
                    if verified_lines is None and legacy_match is not None:
                        verified_lines = _verified_activity_lines(
                            legacy_facts, legacy_match, raw
                        )
                    # The structural date is authoritative; unknown/ambiguous dates
                    # remain unknown rather than inheriting a guessed heading.
                    parsed = read_timeline_capture(
                        verified_lines if verified_lines is not None else raw,
                        matched.day,
                        # An unproven trim is not permission to discard matching
                        # words in a real note. Keep raw body text on uncertainty.
                        verified_activity=True,
                    )
                    html_index = matched.index + 1
                elif (
                    group is None
                    and source.id in linked_sources
                    and parsed is not None
                    and not parsed.hidden
                ):
                    fragment = verified_timeline_fragment_tail_lines(facts, raw)
                    if fragment is not None:
                        # Old imports split some note titles into separate rows.
                        # A complete body-suffix proof permits cleanup only: it
                        # grants no new activity identity, date, or cursor advance.
                        parsed = CapturedTimeline(
                            body="\n".join(fragment), recognized=True
                        )
            if (
                raw is not None
                and parsed is not None
                and parsed.hidden
                and (
                    contains_structural_activity or has_embedded_timeline_activity(raw)
                )
            ):
                parsed = CapturedTimeline(
                    title="Captured activity needs review",
                    body=(
                        "This capture contains activity that could not be interpreted safely. "
                        "Open Source Evidence to review the original archive. No captured content has been removed."
                    ),
                    recognized=True,
                    kind="capture_needs_review",
                )
            # Later CRM edits take precedence over captured source presentation.
            unchanged = raw is not None and _matches_original_projection(
                row, source, raw
            )
            if unchanged and parsed is not None and parsed.hidden:
                filtered_capture_count += 1
                continue
            presentation = (
                parsed
                if unchanged and parsed is not None and parsed.recognized
                else None
            )
            entry = ContactTimelineEntry(
                key=f"recovered:{row.id}",
                origin=origin,
                kind=(presentation.kind or row.kind)
                if presentation is not None
                else row.kind,
                title=(presentation.title or row.title)
                if presentation is not None
                else row.title,
                body=presentation.body if presentation is not None else row.body,
                outcome=row.outcome
                or (presentation.outcome if presentation is not None else None),
                occurred_at=_as_utc(row.occurred_at),
                source_record_id=row.source_record_id,
                entity_type="contact_timeline_event",
                entity_id=row.id,
                captured_date=presentation.captured_date
                if presentation is not None
                else None,
                captured_time=presentation.captured_time
                if presentation is not None
                else None,
            )
            candidate = _candidate(entry)
            if cursor is None or timeline_position_is_after(
                cursor,
                null_rank=candidate.null_rank,
                occurred_at=candidate.sort_at,
                origin_rank=candidate.origin_rank,
                entity_id=row.id,
            ):
                selected.append(candidate)
                selected.sort(key=_candidate_sort_key)
                del selected[limit:]
        if len(rows) < batch_size:
            return tuple(selected), filtered_capture_count
        last, _source, row_section, row_ordinal, _provider, _capture = rows[-1]
        after = (row_section, row_ordinal, last.id)


async def _capture_timeline_structure(
    db: AsyncSession, *, section_id: int, capture_ordinal: int
) -> tuple[TimelineHTMLFacts, frozenset[int]] | None:
    """Load one owned, byte-verified capture, never a page from another contact."""
    rows = (
        await db.execute(
            select(
                CRMArchiveArtifact.id,
                CRMArchiveArtifact.sha256,
                CRMArchiveArtifact.size_bytes,
                CRMArchiveArtifact.filename,
                CRMSourceRecordArtifact.source_record_id,
            )
            .join(
                CRMSourceRecordArtifact,
                CRMSourceRecordArtifact.artifact_id == CRMArchiveArtifact.id,
            )
            .join(
                CRMContactSourceOccurrence,
                CRMContactSourceOccurrence.source_record_id
                == CRMSourceRecordArtifact.source_record_id,
            )
            .where(
                CRMContactSourceOccurrence.section_capture_id == section_id,
                CRMSourceRecordArtifact.relation == "evidence",
                CRMArchiveArtifact.domain == "kw_command",
                CRMArchiveArtifact.source_path.in_(
                    tuple(
                        f"kw_command_repaired/contacts/sections/{capture_ordinal:07d}/timeline.{extension}"
                        for extension in ("html", "json")
                    )
                ),
                or_(
                    and_(
                        CRMArchiveArtifact.artifact_type == "html",
                        CRMArchiveArtifact.filename == "timeline.html",
                    ),
                    and_(
                        CRMArchiveArtifact.artifact_type == "json",
                        CRMArchiveArtifact.filename == "timeline.json",
                    ),
                ),
            )
        )
    ).all()
    if not rows:
        return None
    # The archive used two capture formats. JSON accessibility roles are the
    # original structural source for later captures; earlier visible-text JSON
    # instead has its structure in the sibling HTML. Never guess from plain text.
    for filename in ("timeline.json", "timeline.html"):
        linked = [row for row in rows if row.filename == filename]
        if not linked:
            continue
        identities = {(row.id, row.sha256, row.size_bytes) for row in linked}
        if len(identities) != 1:
            raise ContactTimelineIntegrityError(
                "timeline archive identity is ambiguous"
            )
        artifact_id, digest, size = next(iter(identities))
        if not 0 < size <= 8 * 1024 * 1024:
            raise ContactTimelineIntegrityError("timeline archive size is invalid")
        content = await db.scalar(
            select(CRMArchiveArtifact.content_bytes).where(
                CRMArchiveArtifact.id == artifact_id,
                func.length(CRMArchiveArtifact.content_bytes) == size,
            )
        )
        if content is None or hashlib.sha256(content).hexdigest() != digest:
            raise ContactTimelineIntegrityError("timeline archive integrity is invalid")
        try:
            decoded = content.decode("utf-8")
            if filename == "timeline.json":
                payload = json.loads(decoded)
                snapshot = (
                    payload.get("accessibility_snapshot")
                    if isinstance(payload, dict)
                    else None
                )
                if not isinstance(snapshot, str):
                    continue
                facts = parse_timeline_snapshot(snapshot)
            else:
                facts = parse_timeline_html(decoded)
        except (UnicodeError, ValueError) as exc:
            raise ContactTimelineIntegrityError(
                "timeline archive encoding is invalid"
            ) from exc
        if facts.activities:
            return facts, frozenset(row.source_record_id for row in linked)
    return None


def _verified_activity_lines(
    facts: TimelineHTMLFacts, activity: TimelineHTMLActivity, raw: list[str]
) -> list[str] | None:
    """Keep exact captured lines, trimming only boundaries proven outside HTML."""

    def normalized(lines):
        return " ".join(" ".join(lines).split()).casefold()

    expected = activity.text.casefold()

    def without_verified_reply(lines):
        if activity.trailing_reply_button and lines and lines[-1] == "Reply":
            return lines[:-1]
        return lines

    if normalized(raw) == expected:
        return without_verified_reply(raw)
    next_headings = {
        heading.text.casefold()
        for heading in facts.headings
        if heading.before_event_index == activity.index + 1
    }
    if raw[-1].casefold() in next_headings and normalized(raw[:-1]) == expected:
        return without_verified_reply(raw[:-1])
    if facts.terminal_footer and activity.index == len(facts.activities) - 1:
        for index, line in enumerate(raw[4:], 4):
            if line == "End of Timeline" and normalized(raw[:index]) == expected:
                return without_verified_reply(raw[:index])
    return verified_timeline_tail_lines(facts, activity, raw)


def _matches_original_projection(row, source, raw: list[str]) -> bool:
    """Transform only the unedited materializer output, including hidden rows."""
    try:
        values = json.loads(source.payload_json)["values"]
        attributes = json.loads(row.attributes_json)
    except (KeyError, TypeError, ValueError):
        return False

    def value(name):
        item = values.get(name)
        return item.strip() if isinstance(item, str) and item.strip() else None

    explicit_time = None
    if value("occurred_at"):
        try:
            explicit_time = _as_utc(
                datetime.fromisoformat(value("occurred_at").replace("Z", "+00:00"))
            )
        except ValueError:
            pass
    return (
        row.body == "\n".join(raw)
        and row.title == source.display_label
        and row.kind == (value("kind") or "CONTACT").casefold()
        and row.source_event_key == source.source_key
        and row.outcome == value("outcome")
        and row.actor_label == value("actor_label")
        and row.channel == value("channel")
        and _as_utc(row.occurred_at) == explicit_time
        and attributes == values
    )


async def _activity_candidates(
    db: AsyncSession,
    *,
    contact_id: int,
    cursor: TimelineCursorV1 | None,
    limit: int,
) -> tuple[_TimelineCandidate, ...]:
    origin = TimelineOrigin.INTERNAL_CRM
    statement = select(CRMActivity).where(
        CRMActivity.contact_id == contact_id,
        CRMActivity.source_record_id.is_(None),
        CRMActivity.kind.not_in(_TECHNICAL_ACTIVITY_KINDS),
    )
    if cursor is not None:
        statement = statement.where(
            _after_cursor(
                CRMActivity.created_at,
                CRMActivity.id,
                _ORIGIN_RANK[origin],
                cursor,
            )
        )
    statement = statement.order_by(
        _null_rank(CRMActivity.created_at).asc(),
        CRMActivity.created_at.desc().nulls_last(),
        CRMActivity.id.desc(),
    ).limit(limit)
    rows = (await db.scalars(statement)).all()
    return tuple(
        _candidate(
            ContactTimelineEntry(
                key=f"activity:{activity.id}",
                origin=origin,
                kind=activity.kind,
                title=activity.summary,
                body=None,
                outcome=None,
                occurred_at=_as_utc(activity.created_at),
                source_record_id=None,
                entity_type="activity",
                entity_id=activity.id,
            )
        )
        for activity in rows
    )


async def _require_activity_source_integrity(
    db: AsyncSession, *, contact_id: int
) -> None:
    invalid_source = (
        select(CRMActivity.id)
        .outerjoin(
            CRMSourceRecord,
            CRMSourceRecord.id == CRMActivity.source_record_id,
        )
        .outerjoin(
            CRMContactSourceOccurrence,
            CRMContactSourceOccurrence.source_record_id == CRMActivity.source_record_id,
        )
        .outerjoin(
            CRMContactSectionCapture,
            CRMContactSectionCapture.id
            == CRMContactSourceOccurrence.section_capture_id,
        )
        .outerjoin(
            CRMContactCapturePosition,
            CRMContactCapturePosition.id
            == CRMContactSectionCapture.capture_position_id,
        )
        .outerjoin(
            CRMContactTimelineEvent,
            CRMContactTimelineEvent.source_record_id == CRMActivity.source_record_id,
        )
        .where(
            CRMActivity.source_record_id.is_not(None),
            or_(
                CRMActivity.contact_id == contact_id,
                CRMContactTimelineEvent.contact_id == contact_id,
            ),
            or_(
                CRMActivity.contact_id.is_(None),
                CRMActivity.contact_id != contact_id,
                CRMSourceRecord.id.is_(None),
                CRMSourceRecord.source_system != "kw_command",
                CRMSourceRecord.module != "contacts",
                CRMSourceRecord.record_kind != "contact_timeline_event",
                CRMContactSourceOccurrence.id.is_(None),
                CRMContactSourceOccurrence.contact_id != contact_id,
                CRMContactSectionCapture.id.is_(None),
                CRMContactSectionCapture.section_name != "timeline",
                CRMContactCapturePosition.id.is_(None),
                CRMContactCapturePosition.contact_id != contact_id,
                CRMContactTimelineEvent.id.is_(None),
                CRMContactTimelineEvent.contact_id != contact_id,
                CRMContactTimelineEvent.source_system != "kw_command",
            ),
        )
        .limit(1)
    )
    if (await db.scalar(invalid_source)) is not None:
        raise ContactTimelineIntegrityError(
            "timeline activity source integrity is invalid"
        )


async def _require_recovered_source_integrity(
    db: AsyncSession, *, contact_id: int
) -> None:
    invalid_source = (
        select(CRMContactTimelineEvent.id)
        .outerjoin(
            CRMSourceRecord,
            CRMSourceRecord.id == CRMContactTimelineEvent.source_record_id,
        )
        .outerjoin(
            CRMContactSourceOccurrence,
            CRMContactSourceOccurrence.source_record_id
            == CRMContactTimelineEvent.source_record_id,
        )
        .outerjoin(
            CRMContactSectionCapture,
            CRMContactSectionCapture.id
            == CRMContactSourceOccurrence.section_capture_id,
        )
        .outerjoin(
            CRMContactCapturePosition,
            CRMContactCapturePosition.id
            == CRMContactSectionCapture.capture_position_id,
        )
        .where(
            CRMContactTimelineEvent.contact_id == contact_id,
            or_(
                CRMSourceRecord.id.is_(None),
                CRMSourceRecord.source_system != "kw_command",
                CRMSourceRecord.module != "contacts",
                CRMSourceRecord.record_kind != "contact_timeline_event",
                CRMContactTimelineEvent.source_system != "kw_command",
                CRMContactSourceOccurrence.id.is_(None),
                CRMContactSourceOccurrence.contact_id != contact_id,
                CRMContactSectionCapture.id.is_(None),
                CRMContactSectionCapture.section_name != "timeline",
                CRMContactCapturePosition.id.is_(None),
                CRMContactCapturePosition.contact_id != contact_id,
            ),
        )
        .limit(1)
    )
    if (await db.scalar(invalid_source)) is not None:
        raise ContactTimelineIntegrityError(
            "recovered timeline source integrity is invalid"
        )


def _legacy_lead_candidates(
    *,
    lead: Lead | None,
    cursor: TimelineCursorV1 | None,
) -> tuple[_TimelineCandidate, ...]:
    if lead is None:
        return ()
    origin = TimelineOrigin.LEGACY_LEAD
    occurred_at = _as_utc(lead.created_at)
    if cursor is not None and not timeline_position_is_after(
        cursor,
        null_rank=1 if occurred_at is None else 0,
        occurred_at=occurred_at,
        origin_rank=_ORIGIN_RANK[origin],
        entity_id=lead.id,
    ):
        return ()
    return (
        _candidate(
            ContactTimelineEntry(
                key=f"lead:{lead.id}",
                origin=origin,
                kind="lead_created",
                title="Lead created",
                body=None,
                outcome=None,
                occurred_at=occurred_at,
                source_record_id=None,
                entity_type="lead",
                entity_id=lead.id,
            )
        ),
    )


async def _booking_candidates(
    db: AsyncSession,
    *,
    contact: CRMContact,
    cursor: TimelineCursorV1 | None,
    limit: int,
) -> tuple[_TimelineCandidate, ...]:
    if contact.lead_id is not None:
        await _require_lead_booking_email_integrity(db, lead_id=contact.lead_id)
        return await _lead_booking_candidates(
            db,
            lead_id=contact.lead_id,
            cursor=cursor,
            limit=limit,
        )
    if not await _owns_unique_email(db, contact):
        return ()
    normalized = canonical_email(contact.email)
    assert normalized is not None
    return await _email_booking_candidates(
        db,
        normalized_email=normalized,
        cursor=cursor,
        limit=limit,
    )


async def _require_lead_booking_email_integrity(
    db: AsyncSession, *, lead_id: int
) -> int:
    last_id = 0
    count = 0
    batch_size = 1_000
    while True:
        rows = (
            await db.execute(
                select(Booking.id, Booking.email, Booking.normalized_email)
                .where(Booking.lead_id == lead_id, Booking.id > last_id)
                .order_by(Booking.id)
                .limit(batch_size)
            )
        ).all()
        if any(canonical_email(row.email) != row.normalized_email for row in rows):
            raise ContactTimelineIntegrityError(
                "booking email normalization is invalid"
            )
        count += len(rows)
        if not rows or len(rows) < batch_size:
            return count
        last_id = rows[-1].id


async def _lead_booking_candidates(
    db: AsyncSession,
    *,
    lead_id: int,
    cursor: TimelineCursorV1 | None,
    limit: int,
) -> tuple[_TimelineCandidate, ...]:
    statement = select(Booking).where(Booking.lead_id == lead_id)
    return await _execute_booking_statement(
        db,
        statement=statement,
        cursor=cursor,
        limit=limit,
    )


async def _email_booking_candidates(
    db: AsyncSession,
    *,
    normalized_email: str,
    cursor: TimelineCursorV1 | None,
    limit: int,
) -> tuple[_TimelineCandidate, ...]:
    statement = select(Booking).where(
        Booking.lead_id.is_(None),
        Booking.normalized_email == normalized_email,
    )
    rows = await _booking_rows(
        db,
        statement=statement,
        cursor=cursor,
        limit=limit,
    )
    for row in rows:
        if canonical_email(row.email) != row.normalized_email:
            raise ContactTimelineIntegrityError(
                "booking email normalization is invalid"
            )
    return tuple(_booking_candidate(row) for row in rows)


async def _execute_booking_statement(
    db: AsyncSession,
    *,
    statement,
    cursor: TimelineCursorV1 | None,
    limit: int,
) -> tuple[_TimelineCandidate, ...]:
    rows = await _booking_rows(
        db,
        statement=statement,
        cursor=cursor,
        limit=limit,
    )
    return tuple(_booking_candidate(row) for row in rows)


async def _booking_rows(
    db: AsyncSession,
    *,
    statement,
    cursor: TimelineCursorV1 | None,
    limit: int,
):

    origin = TimelineOrigin.BOOKING
    if cursor is not None:
        statement = statement.where(
            _after_cursor(
                Booking.scheduled_at,
                Booking.id,
                _ORIGIN_RANK[origin],
                cursor,
            )
        )
    statement = statement.order_by(
        _null_rank(Booking.scheduled_at).asc(),
        Booking.scheduled_at.desc().nulls_last(),
        Booking.id.desc(),
    ).limit(limit)
    return (await db.scalars(statement)).all()


def _booking_candidate(row: Booking) -> _TimelineCandidate:
    return _candidate(
        ContactTimelineEntry(
            key=f"booking:{row.id}",
            origin=TimelineOrigin.BOOKING,
            kind="booking",
            title=row.meeting_type,
            body=row.notes or None,
            outcome=row.context or None,
            occurred_at=_as_utc(row.scheduled_at),
            source_record_id=None,
            entity_type="booking",
            entity_id=row.id,
        )
    )


async def _owns_unique_email(db: AsyncSession, contact: CRMContact) -> bool:
    normalized = canonical_email(contact.email)
    if normalized is None:
        return False
    rows = (
        await db.execute(
            select(CRMContact.id, CRMContact.email, CRMContact.normalized_email)
            .where(CRMContact.normalized_email == normalized)
            .order_by(CRMContact.id)
            .limit(2)
        )
    ).all()
    if any(canonical_email(row.email) != row.normalized_email for row in rows):
        raise ContactTimelineIntegrityError("contact email normalization is invalid")
    return len(rows) == 1 and rows[0].id == contact.id


def _require_contact_email_integrity(contact: CRMContact) -> None:
    if canonical_email(contact.email) != contact.normalized_email:
        raise ContactTimelineIntegrityError("contact email normalization is invalid")


def _null_rank(timestamp_column):
    return case((timestamp_column.is_(None), 1), else_=0)


def _after_cursor(
    timestamp_column,
    id_column,
    origin_rank: int,
    cursor: TimelineCursorV1,
):
    null_rank = _null_rank(timestamp_column)
    if cursor.null_rank == 0:
        assert cursor.occurred_at is not None
        within_rank = or_(
            timestamp_column < cursor.occurred_at,
            and_(
                timestamp_column == cursor.occurred_at,
                _after_origin_and_id(id_column, origin_rank, cursor),
            ),
        )
    else:
        within_rank = _after_origin_and_id(id_column, origin_rank, cursor)
    return or_(
        null_rank > cursor.null_rank,
        and_(null_rank == cursor.null_rank, within_rank),
    )


def _after_origin_and_id(id_column, origin_rank: int, cursor: TimelineCursorV1):
    if origin_rank > cursor.origin_rank:
        return True
    if origin_rank < cursor.origin_rank:
        return False
    return id_column < cursor.entity_id


def _candidate(entry: ContactTimelineEntry) -> _TimelineCandidate:
    sort_at = entry.occurred_at
    if sort_at is None and entry.captured_date is not None:
        # This is a deterministic wall-clock sort coordinate ONLY. The public
        # occurred_at remains null: no captured timezone is being invented.
        sort_at = datetime.fromisoformat(
            f"{entry.captured_date.isoformat()}T{entry.captured_time or '00:00:00'}"
        ).replace(tzinfo=UTC)
    return _TimelineCandidate(
        entry=entry,
        null_rank=1 if sort_at is None else 0,
        origin_rank=_ORIGIN_RANK[entry.origin],
        sort_at=sort_at,
    )


def _candidate_sort_key(candidate: _TimelineCandidate) -> tuple[int, int, int, int]:
    occurred_at = candidate.sort_at
    return (
        candidate.null_rank,
        -_utc_microseconds(occurred_at) if occurred_at is not None else 0,
        candidate.origin_rank,
        -candidate.entry.entity_id,
    )


def _utc_microseconds(value: datetime) -> int:
    normalized = _as_utc(value)
    assert normalized is not None
    return (
        normalized.toordinal() * 86_400_000_000
        + normalized.hour * 3_600_000_000
        + normalized.minute * 60_000_000
        + normalized.second * 1_000_000
        + normalized.microsecond
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "ContactNotFound",
    "ContactTimelineIntegrityError",
    "count_contact_bookings",
    "list_contact_timeline",
]
