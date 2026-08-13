"""Bounded, non-duplicating aggregation for one internal CRM contact timeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.booking import Booking
from models.command import CRMActivity, CRMContact
from models.command_contacts import (
    CRMContactCapturePosition,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
    CRMContactTimelineEvent,
)
from models.command_provenance import CRMSourceRecord
from models.lead import Lead
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

_ORIGIN_RANK: dict[TimelineOrigin, Literal[0, 1, 2, 3]] = {
    TimelineOrigin.RECOVERED: 0,
    TimelineOrigin.INTERNAL_CRM: 1,
    TimelineOrigin.LEGACY_LEAD: 2,
    TimelineOrigin.BOOKING: 3,
}


class ContactNotFound(LookupError):
    """The requested internal contact does not exist."""


class ContactTimelineIntegrityError(RuntimeError):
    """A source-linked timeline row violates ownership/type invariants."""


@dataclass(frozen=True, slots=True)
class _TimelineCandidate:
    entry: ContactTimelineEntry
    null_rank: Literal[0, 1]
    origin_rank: Literal[0, 1, 2, 3]


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
    await _require_activity_source_integrity(db, contact_id=contact.id)

    fetch_limit = page_size + 1
    recovered = await _recovered_candidates(
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
                occurred_at=last.entry.occurred_at,
                origin_rank=last.origin_rank,
                entity_id=last.entry.entity_id,
            )
        )
    return ContactTimelinePage(
        rows=tuple(candidate.entry for candidate in emitted),
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def _recovered_candidates(
    db: AsyncSession,
    *,
    contact_id: int,
    cursor: TimelineCursorV1 | None,
    limit: int,
) -> tuple[_TimelineCandidate, ...]:
    origin = TimelineOrigin.RECOVERED
    statement = select(CRMContactTimelineEvent).where(
        CRMContactTimelineEvent.contact_id == contact_id
    )
    if cursor is not None:
        statement = statement.where(
            _after_cursor(
                CRMContactTimelineEvent.occurred_at,
                CRMContactTimelineEvent.id,
                _ORIGIN_RANK[origin],
                cursor,
            )
        )
    statement = statement.order_by(
        _null_rank(CRMContactTimelineEvent.occurred_at).asc(),
        CRMContactTimelineEvent.occurred_at.desc().nulls_last(),
        CRMContactTimelineEvent.id.desc(),
    ).limit(limit)
    rows = (await db.scalars(statement)).all()
    return tuple(
        _candidate(
            ContactTimelineEntry(
                key=f"recovered:{row.id}",
                origin=origin,
                kind=row.kind,
                title=row.title,
                body=row.body,
                outcome=row.outcome,
                occurred_at=_as_utc(row.occurred_at),
                source_record_id=row.source_record_id,
                entity_type="contact_timeline_event",
                entity_id=row.id,
            )
        )
        for row in rows
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
            CRMActivity.contact_id == contact_id,
            CRMActivity.source_record_id.is_not(None),
            or_(
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
    return _TimelineCandidate(
        entry=entry,
        null_rank=1 if entry.occurred_at is None else 0,
        origin_rank=_ORIGIN_RANK[entry.origin],
    )


def _candidate_sort_key(candidate: _TimelineCandidate) -> tuple[int, int, int, int]:
    occurred_at = candidate.entry.occurred_at
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
    "list_contact_timeline",
]
