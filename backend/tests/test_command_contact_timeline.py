"""Lossless, bounded aggregation tests for the Command contact timeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from models.booking import Booking
from models.command import CRMActivity, CRMContact
from models.command_contacts import (
    CRMContactCapturePosition,
    CRMContactMethod,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
    CRMContactTimelineEvent,
)
from models.command_provenance import CRMSourceRecord
from models.lead import Lead
from services.command_contact_contracts import (
    ContactTimelineEntry,
    TimelineCursorV1,
    TimelineOrigin,
    decode_timeline_cursor,
    encode_timeline_cursor,
)
from services.command_contact_timeline import (
    ContactNotFound,
    ContactTimelineIntegrityError,
    _as_utc,
    list_contact_timeline,
)

BASE_TIME = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
TABLES = (
    Lead.__table__,
    CRMContact.__table__,
    Booking.__table__,
    CRMSourceRecord.__table__,
    CRMContactMethod.__table__,
    CRMContactCapturePosition.__table__,
    CRMContactSectionCapture.__table__,
    CRMContactSourceOccurrence.__table__,
    CRMActivity.__table__,
    CRMContactTimelineEvent.__table__,
)


@pytest_asyncio.fixture()
async def timeline_db(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'contact-timeline.sqlite'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(sync, tables=TABLES)
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _source(source_id: int, *, kind: str = "contact_timeline_event") -> CRMSourceRecord:
    return CRMSourceRecord(
        id=source_id,
        source_system="kw_command",
        module="contacts",
        record_kind=kind,
        source_key=f"synthetic:source:{source_id}",
        evidence_level="rendered_occurrence",
        display_label="Synthetic source",
        payload_json="{}",
        capture_quality="complete",
        captured_at=BASE_TIME,
        parser_version="contacts-v1",
    )


def _timeline_ownership(
    source_id: int,
    *,
    contact_id: int,
    section_name: str = "timeline",
    position_contact_id: int | None = None,
) -> tuple[object, ...]:
    position_source_id = 100_000 + source_id * 2
    section_source_id = position_source_id + 1
    position_id = 200_000 + source_id
    section_id = 300_000 + source_id
    return (
        _source(position_source_id, kind="contact_profile"),
        _source(section_source_id, kind="contact_section"),
        CRMContactCapturePosition(
            id=position_id,
            contact_id=position_contact_id or contact_id,
            source_record_id=position_source_id,
            bundle_fingerprint=f"{source_id:064x}",
            capture_ordinal=1,
            source_contact_id=f"{source_id:024x}",
            captured_at=BASE_TIME,
            capture_quality="complete",
            limitations_json="[]",
        ),
        CRMContactSectionCapture(
            id=section_id,
            capture_position_id=position_id,
            source_record_id=section_source_id,
            section_name=section_name,
            captured_at=BASE_TIME,
            capture_quality="complete",
            is_empty=False,
            row_count=1,
            limitations_json="[]",
        ),
        CRMContactSourceOccurrence(
            id=400_000 + source_id,
            contact_id=contact_id,
            section_capture_id=section_id,
            source_record_id=source_id,
            occurrence_ordinal=1,
        ),
    )


async def _flush(db: AsyncSession, *rows: object) -> None:
    db.add_all(rows)
    await db.flush()


@pytest.mark.asyncio
async def test_timeline_aggregates_all_origins_and_dedupes_only_shared_source(
    timeline_db: AsyncSession,
):
    lead = Lead(
        id=11,
        name="Synthetic Lead",
        created_at=BASE_TIME - timedelta(days=2),
    )
    contact = CRMContact(
        id=1,
        lead_id=lead.id,
        first_name="Synthetic",
        last_name="Contact",
        email="contact@example.test",
        stage="lead",
    )
    source = _source(21)
    recovered = CRMContactTimelineEvent(
        id=31,
        contact_id=contact.id,
        source_record_id=source.id,
        source_system="kw_command",
        source_event_key="synthetic:event:31",
        kind="email",
        title="Stored recovered title",
        body="Stored recovered body",
        outcome="replied",
        occurred_at=BASE_TIME,
        attributes_json="{}",
    )
    mirrored = CRMActivity(
        id=41,
        contact_id=contact.id,
        source_record_id=source.id,
        kind="email",
        summary="Stored recovered title",
        created_at=BASE_TIME,
    )
    same_text_and_time = CRMActivity(
        id=42,
        contact_id=contact.id,
        source_record_id=None,
        kind="email",
        summary="Stored recovered title",
        created_at=BASE_TIME,
    )
    booking = Booking(
        id=51,
        lead_id=lead.id,
        name="Different booking name",
        email="different@example.test",
        meeting_type="consultation",
        context="buyer",
        scheduled_at=BASE_TIME - timedelta(days=1),
        notes="Stored booking notes",
    )
    await _flush(
        timeline_db,
        lead,
        contact,
        source,
        *_timeline_ownership(source.id, contact_id=contact.id),
        recovered,
        mirrored,
        same_text_and_time,
        booking,
    )

    page = await list_contact_timeline(
        timeline_db, contact.id, cursor=None, page_size=20
    )

    assert [row.key for row in page.rows] == [
        "recovered:31",
        "activity:42",
        "booking:51",
        "lead:11",
    ]
    assert page.has_more is False and page.next_cursor is None
    assert page.rows == (
        ContactTimelineEntry(
            key="recovered:31",
            origin=TimelineOrigin.RECOVERED,
            kind="email",
            title="Stored recovered title",
            body="Stored recovered body",
            outcome="replied",
            occurred_at=BASE_TIME,
            source_record_id=21,
            entity_type="contact_timeline_event",
            entity_id=31,
        ),
        ContactTimelineEntry(
            key="activity:42",
            origin=TimelineOrigin.INTERNAL_CRM,
            kind="email",
            title="Stored recovered title",
            body=None,
            outcome=None,
            occurred_at=BASE_TIME,
            source_record_id=None,
            entity_type="activity",
            entity_id=42,
        ),
        ContactTimelineEntry(
            key="booking:51",
            origin=TimelineOrigin.BOOKING,
            kind="booking",
            title="consultation",
            body="Stored booking notes",
            outcome="buyer",
            occurred_at=BASE_TIME - timedelta(days=1),
            source_record_id=None,
            entity_type="booking",
            entity_id=51,
        ),
        ContactTimelineEntry(
            key="lead:11",
            origin=TimelineOrigin.LEGACY_LEAD,
            kind="lead_created",
            title="Lead created",
            body=None,
            outcome=None,
            occurred_at=BASE_TIME - timedelta(days=2),
            source_record_id=None,
            entity_type="lead",
            entity_id=11,
        ),
    )


@pytest.mark.asyncio
async def test_timed_activity_mirror_never_replaces_nullable_recovered_event(
    timeline_db: AsyncSession,
):
    contact = CRMContact(
        id=1, first_name="Nullable", last_name="Recovered", stage="lead"
    )
    source = _source(1)
    await _flush(
        timeline_db,
        contact,
        source,
        *_timeline_ownership(source.id, contact_id=contact.id),
        CRMContactTimelineEvent(
            id=1,
            contact_id=contact.id,
            source_record_id=source.id,
            source_system="kw_command",
            source_event_key="synthetic:null-time",
            kind="event",
            title="Recovered without time",
            occurred_at=None,
            attributes_json="{}",
        ),
        CRMActivity(
            id=1,
            contact_id=contact.id,
            source_record_id=source.id,
            kind="event",
            summary="Timed mirror",
            created_at=BASE_TIME,
        ),
    )

    page = await list_contact_timeline(
        timeline_db, contact.id, cursor=None, page_size=10
    )
    assert [row.key for row in page.rows] == ["recovered:1"]
    assert page.rows[0].occurred_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    (
        "non_timeline",
        "different_contact",
        "missing_event",
        "wrong_system",
        "wrong_module",
        "wrong_occurrence_owner",
        "wrong_occurrence_section",
        "wrong_position_owner",
        "wrong_event_system",
    ),
)
async def test_timeline_rejects_invalid_activity_source_links(
    timeline_db: AsyncSession,
    corruption: str,
):
    first = CRMContact(id=1, first_name="First", last_name="Contact", stage="lead")
    second = CRMContact(id=2, first_name="Second", last_name="Contact", stage="lead")
    source = _source(
        1,
        kind="contact_note"
        if corruption == "non_timeline"
        else "contact_timeline_event",
    )
    if corruption == "wrong_system":
        source.source_system = "internal_crm"
    if corruption == "wrong_module":
        source.module = "tasks"
    activity = CRMActivity(
        id=1,
        contact_id=first.id,
        source_record_id=source.id,
        kind="note",
        summary="Linked activity",
        created_at=BASE_TIME,
    )
    owner_id = second.id if corruption == "wrong_occurrence_owner" else first.id
    section_name = "notes" if corruption == "wrong_occurrence_section" else "timeline"
    position_contact_id = second.id if corruption == "wrong_position_owner" else None
    rows: list[object] = [
        first,
        second,
        source,
        *_timeline_ownership(
            source.id,
            contact_id=owner_id,
            section_name=section_name,
            position_contact_id=position_contact_id,
        ),
        activity,
    ]
    if corruption != "missing_event":
        rows.append(
            CRMContactTimelineEvent(
                id=1,
                contact_id=second.id if corruption == "different_contact" else first.id,
                source_record_id=source.id,
                source_system=(
                    "internal_crm"
                    if corruption == "wrong_event_system"
                    else "kw_command"
                ),
                source_event_key="synthetic:wrong-owner",
                kind="email",
                title="Wrong owner",
                occurred_at=BASE_TIME,
                attributes_json="{}",
            )
        )
    await _flush(timeline_db, *rows)

    with pytest.raises(ContactTimelineIntegrityError) as error:
        await list_contact_timeline(timeline_db, first.id, cursor=None, page_size=10)
    assert "synthetic" not in str(error.value)


@pytest.mark.asyncio
async def test_timeline_rejects_source_corruption_outside_page_and_before_cursor(
    timeline_db: AsyncSession,
):
    contact = CRMContact(id=1, first_name="Corrupt", last_name="History", stage="lead")
    source = _source(1)
    corrupt = CRMActivity(
        id=1,
        contact_id=contact.id,
        source_record_id=source.id,
        kind="event",
        summary="Off page corruption",
        created_at=BASE_TIME - timedelta(days=100),
    )
    await _flush(
        timeline_db,
        contact,
        source,
        *_timeline_ownership(source.id, contact_id=contact.id),
        corrupt,
        *(
            CRMActivity(
                id=index,
                contact_id=contact.id,
                kind="event",
                summary=f"Valid {index}",
                created_at=BASE_TIME - timedelta(days=index),
            )
            for index in range(2, 8)
        ),
    )
    cursor = encode_timeline_cursor(
        TimelineCursorV1(0, BASE_TIME - timedelta(days=50), 1, 999)
    )

    with pytest.raises(ContactTimelineIntegrityError):
        await list_contact_timeline(timeline_db, contact.id, cursor=cursor, page_size=1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    (
        "missing_source",
        "wrong_source_system",
        "wrong_source_module",
        "wrong_source_kind",
        "wrong_event_system",
        "missing_occurrence",
        "wrong_occurrence_owner",
        "wrong_occurrence_section",
        "wrong_position_owner",
    ),
)
async def test_timeline_rejects_recovered_source_corruption_without_an_activity(
    timeline_db: AsyncSession,
    corruption: str,
):
    first = CRMContact(id=1, first_name="First", last_name="Contact", stage="lead")
    second = CRMContact(id=2, first_name="Second", last_name="Contact", stage="lead")
    source = _source(1)
    if corruption == "wrong_source_system":
        source.source_system = "internal_crm"
    elif corruption == "wrong_source_module":
        source.module = "tasks"
    elif corruption == "wrong_source_kind":
        source.record_kind = "contact_note"
    ownership = _timeline_ownership(
        source.id,
        contact_id=(second.id if corruption == "wrong_occurrence_owner" else first.id),
        section_name=("notes" if corruption == "wrong_occurrence_section" else "timeline"),
        position_contact_id=(second.id if corruption == "wrong_position_owner" else None),
    )
    if corruption == "missing_occurrence":
        ownership = ownership[:-1]
    rows: list[object] = [first, second, *ownership]
    if corruption != "missing_source":
        rows.append(source)
    rows.append(
        CRMContactTimelineEvent(
            id=1,
            contact_id=first.id,
            source_record_id=source.id,
            source_system=(
                "internal_crm" if corruption == "wrong_event_system" else "kw_command"
            ),
            source_event_key="synthetic:recovered-corruption",
            kind="email",
            title="Recovered event",
            occurred_at=BASE_TIME,
            attributes_json="{}",
        )
    )
    await _flush(timeline_db, *rows)

    with pytest.raises(ContactTimelineIntegrityError) as error:
        await list_contact_timeline(
            timeline_db, first.id, cursor=None, page_size=10
        )
    assert "synthetic" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("activity_owner", (None, 2))
async def test_timeline_rejects_mirror_owned_by_null_or_another_contact(
    timeline_db: AsyncSession,
    activity_owner: int | None,
):
    first = CRMContact(id=1, first_name="First", last_name="Contact", stage="lead")
    second = CRMContact(id=2, first_name="Second", last_name="Contact", stage="lead")
    source = _source(1)
    await _flush(
        timeline_db,
        first,
        second,
        source,
        *_timeline_ownership(source.id, contact_id=first.id),
        CRMContactTimelineEvent(
            id=1,
            contact_id=first.id,
            source_record_id=source.id,
            source_system="kw_command",
            source_event_key="synthetic:mirror-owner",
            kind="email",
            title="Recovered event",
            occurred_at=BASE_TIME,
            attributes_json="{}",
        ),
        CRMActivity(
            id=1,
            contact_id=activity_owner,
            source_record_id=source.id,
            kind="email",
            summary="Invalid mirror owner",
            created_at=BASE_TIME,
        ),
    )

    with pytest.raises(ContactTimelineIntegrityError):
        await list_contact_timeline(
            timeline_db, first.id, cursor=None, page_size=10
        )


@pytest.mark.asyncio
async def test_booking_linkage_is_lead_exclusive_when_contact_has_a_lead(
    timeline_db: AsyncSession,
):
    await _flush(
        timeline_db,
        Lead(id=1, name="Exact lead", created_at=BASE_TIME),
        Lead(id=2, name="Other lead", created_at=BASE_TIME),
        CRMContact(
            id=1,
            lead_id=1,
            first_name="Lead",
            last_name="Backed",
            email="same@example.test",
            phone="+15550000001",
            stage="lead",
        ),
        Booking(
            id=1,
            lead_id=1,
            name="Unrelated",
            email="other@example.test",
            phone=None,
            meeting_type="exact-lead",
            context="general",
            scheduled_at=BASE_TIME,
            notes="",
        ),
        Booking(
            id=2,
            lead_id=None,
            name="Lead Backed",
            email="same@example.test",
            phone="+15550000001",
            meeting_type="email-fallback-forbidden",
            context="general",
            scheduled_at=BASE_TIME,
            notes="",
        ),
        Booking(
            id=3,
            lead_id=2,
            name="Lead Backed",
            email="same@example.test",
            phone="+15550000001",
            meeting_type="other-lead-forbidden",
            context="general",
            scheduled_at=BASE_TIME,
            notes="",
        ),
    )
    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=20)
    assert [row.key for row in page.rows if row.origin is TimelineOrigin.BOOKING] == [
        "booking:1"
    ]


@pytest.mark.asyncio
async def test_lead_booking_drift_is_rejected_before_cursor_and_beyond_page(
    timeline_db: AsyncSession,
):
    await _flush(
        timeline_db,
        Lead(id=1, name="Exact lead", created_at=BASE_TIME),
        CRMContact(
            id=1,
            lead_id=1,
            first_name="Lead",
            last_name="Backed",
            stage="lead",
        ),
        Booking(
            id=1,
            lead_id=1,
            name="Visible booking",
            email="visible@example.test",
            meeting_type="visible",
            context="general",
            scheduled_at=BASE_TIME,
            notes="",
        ),
        Booking(
            id=2,
            lead_id=1,
            name="Off-page booking",
            email="private@example.test",
            meeting_type="hidden",
            context="general",
            scheduled_at=BASE_TIME - timedelta(days=100),
            notes="",
        ),
    )
    await timeline_db.execute(
        update(Booking)
        .where(Booking.id == 2)
        .values(normalized_email="drift@example.test")
    )
    timeline_db.expire_all()
    cursor = encode_timeline_cursor(
        TimelineCursorV1(0, BASE_TIME - timedelta(days=50), 3, 999)
    )

    with pytest.raises(ContactTimelineIntegrityError) as error:
        await list_contact_timeline(
            timeline_db, 1, cursor=cursor, page_size=1
        )
    assert "private@example.test" not in str(error.value)


@pytest.mark.asyncio
async def test_lead_booking_integrity_uses_thousand_row_keyset_batches(
    timeline_db: AsyncSession,
):
    await _flush(
        timeline_db,
        Lead(id=1, name="Exact lead", created_at=BASE_TIME),
        CRMContact(
            id=1,
            lead_id=1,
            first_name="Lead",
            last_name="Backed",
            stage="lead",
        ),
        *(
            Booking(
                id=index,
                lead_id=1,
                name=f"Booking {index}",
                email=f"booking-{index}@example.test",
                meeting_type="fixture",
                context="general",
                scheduled_at=BASE_TIME - timedelta(minutes=index),
                notes="",
            )
            for index in range(1, 2_002)
        ),
    )

    statements: list[tuple[str, object]] = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        normalized = " ".join(statement.split())
        if normalized.startswith(
            "SELECT bookings.id, bookings.email, bookings.normalized_email"
        ):
            statements.append((normalized, parameters))

    assert timeline_db.bind is not None
    event.listen(timeline_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        page = await list_contact_timeline(
            timeline_db, 1, cursor=None, page_size=1
        )
    finally:
        event.remove(timeline_db.bind.sync_engine, "before_cursor_execute", capture)

    assert [row.key for row in page.rows] == ["lead:1"]
    assert len(statements) == 3
    assert all("bookings.lead_id =" in statement for statement, _ in statements)
    assert all("bookings.id >" in statement for statement, _ in statements)
    assert all("ORDER BY bookings.id" in statement for statement, _ in statements)
    assert all("LIMIT" in statement for statement, _ in statements)
    assert all(1_000 in tuple(parameters) for _, parameters in statements)


@pytest.mark.asyncio
async def test_timeline_rejects_a_missing_linked_lead(timeline_db: AsyncSession):
    await _flush(
        timeline_db,
        CRMContact(
            id=1,
            lead_id=777,
            first_name="Missing",
            last_name="Lead",
            stage="lead",
        ),
    )

    with pytest.raises(ContactTimelineIntegrityError) as error:
        await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    assert "777" not in str(error.value)


@pytest.mark.asyncio
async def test_leadless_booking_fallback_requires_one_normalized_contact_owner(
    timeline_db: AsyncSession,
):
    contact = CRMContact(
        id=1,
        first_name="Unique",
        last_name="Email",
        email=" Unique@Example.Test ",
        phone="+15550000001",
        stage="lead",
    )
    included = Booking(
        id=1,
        lead_id=None,
        name="Completely different",
        email="unique@example.test",
        phone=None,
        meeting_type="email-match",
        context="general",
        scheduled_at=BASE_TIME,
        notes="",
    )
    wrong_lead = Booking(
        id=2,
        lead_id=99,
        name="Unique Email",
        email="unique@example.test",
        phone="+15550000001",
        meeting_type="lead-bound-forbidden",
        context="general",
        scheduled_at=BASE_TIME,
        notes="",
    )
    name_phone_only = Booking(
        id=3,
        lead_id=None,
        name="Unique Email",
        email="other@example.test",
        phone="+15550000001",
        meeting_type="name-phone-forbidden",
        context="general",
        scheduled_at=BASE_TIME,
        notes="",
    )
    compatibility_match = Booking(
        id=4,
        lead_id=None,
        name="Compatibility email",
        email="ｕｎｉｑｕｅ@example.test",
        phone=None,
        meeting_type="nfkc-email-match",
        context="general",
        scheduled_at=BASE_TIME,
        notes="",
    )
    await _flush(
        timeline_db,
        contact,
        included,
        wrong_lead,
        name_phone_only,
        compatibility_match,
    )
    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=20)
    assert [row.key for row in page.rows] == ["booking:4", "booking:1"]

    timeline_db.add(
        CRMContact(
            id=2,
            first_name="Shared",
            last_name="Email",
            email="ｕｎｉｑｕｅ@EXAMPLE.test",
            stage="lead",
        )
    )
    await timeline_db.flush()
    ambiguous = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=20)
    assert ambiguous.rows == ()


@pytest.mark.asyncio
async def test_email_fallback_uses_indexed_normalization_and_rejects_raw_drift(
    timeline_db: AsyncSession,
):
    contact = CRMContact(
        id=1,
        first_name="Indexed",
        last_name="Owner",
        email=" Ｕｎｉｑｕｅ@Example.Test ",
        stage="lead",
    )
    booking = Booking(
        id=1,
        lead_id=None,
        name="Indexed owner",
        email="unique@example.test",
        meeting_type="indexed",
        context="general",
        scheduled_at=BASE_TIME,
        notes="",
    )
    noise: list[object] = []
    for index in range(2, 302):
        noise.extend(
            (
                CRMContact(
                    id=index,
                    first_name="Noise",
                    last_name=str(index),
                    email=f"noise-{index}@example.test",
                    stage="lead",
                ),
                Booking(
                    id=index,
                    lead_id=None,
                    name=f"Noise {index}",
                    email=f"noise-{index}@example.test",
                    meeting_type="noise",
                    context="general",
                    scheduled_at=BASE_TIME - timedelta(days=index),
                    notes="",
                ),
            )
        )
    await _flush(timeline_db, contact, booking, *noise)
    assert contact.normalized_email == "unique@example.test"
    assert booking.normalized_email == "unique@example.test"

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    assert timeline_db.bind is not None
    event.listen(timeline_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        page = await list_contact_timeline(
            timeline_db, contact.id, cursor=None, page_size=1
        )
    finally:
        event.remove(timeline_db.bind.sync_engine, "before_cursor_execute", capture)
    assert [row.key for row in page.rows] == ["booking:1"]
    assert sum("FROM crm_contacts" in query for query in statements) <= 2
    assert sum("FROM bookings" in query for query in statements) == 1
    assert all(
        "LIMIT" in query.upper() for query in statements if "FROM bookings" in query
    )

    contact_id = contact.id
    booking_id = booking.id
    await timeline_db.execute(
        update(CRMContact)
        .where(CRMContact.id == contact_id)
        .values(normalized_email="tampered@example.test")
    )
    timeline_db.expire_all()
    with pytest.raises(ContactTimelineIntegrityError):
        await list_contact_timeline(timeline_db, contact_id, cursor=None, page_size=1)

    await timeline_db.execute(
        update(CRMContact)
        .where(CRMContact.id == contact_id)
        .values(normalized_email="unique@example.test")
    )
    await timeline_db.execute(
        update(Booking)
        .where(Booking.id == booking_id)
        .values(email="other@example.test")
    )
    timeline_db.expire_all()
    with pytest.raises(ContactTimelineIntegrityError) as booking_error:
        await list_contact_timeline(timeline_db, contact_id, cursor=None, page_size=1)
    assert "example.test" not in str(booking_error.value)


@pytest.mark.asyncio
async def test_contact_methods_do_not_participate_in_primary_email_ownership(
    timeline_db: AsyncSession,
):
    first = CRMContact(
        id=1,
        first_name="Primary",
        last_name="Owner",
        email="owner@example.test",
        stage="lead",
    )
    second = CRMContact(id=2, first_name="Method", last_name="Only", stage="lead")
    await _flush(
        timeline_db,
        first,
        second,
        CRMContactMethod(
            id=1,
            contact_id=second.id,
            source_record_id=None,
            source_key="synthetic:method:1",
            kind="email",
            raw_value="owner@example.test",
            normalized_value="owner@example.test",
            label="Other",
            is_primary=False,
        ),
        Booking(
            id=1,
            lead_id=None,
            name="Primary owner",
            email="owner@example.test",
            meeting_type="email",
            context="general",
            scheduled_at=BASE_TIME,
            notes="",
        ),
    )
    page = await list_contact_timeline(timeline_db, first.id, cursor=None, page_size=10)
    assert [row.key for row in page.rows] == ["booking:1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("email", (None, "", "not-an-email"))
async def test_leadless_booking_fallback_rejects_blank_or_invalid_email(
    timeline_db: AsyncSession,
    email: str | None,
):
    await _flush(
        timeline_db,
        CRMContact(
            id=1,
            first_name="No",
            last_name="Email",
            email=email,
            phone="+15550000001",
            stage="lead",
        ),
        Booking(
            id=1,
            lead_id=None,
            name="No Email",
            email=email or "other@example.test",
            phone="+15550000001",
            meeting_type="forbidden",
            context="general",
            scheduled_at=BASE_TIME,
            notes="",
        ),
    )
    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=20)
    assert page.rows == ()


async def _seed_ordering_rows(db: AsyncSession, *, reverse: bool = False) -> None:
    timestamp = BASE_TIME.replace(tzinfo=None)
    rows: list[object] = [
        Lead(id=1, name="Lead", created_at=timestamp),
        CRMContact(
            id=1,
            lead_id=1,
            first_name="Ordered",
            last_name="Contact",
            stage="lead",
        ),
        _source(1),
        _source(2),
        _source(3),
        *_timeline_ownership(1, contact_id=1),
        *_timeline_ownership(2, contact_id=1),
        *_timeline_ownership(3, contact_id=1),
        CRMContactTimelineEvent(
            id=2,
            contact_id=1,
            source_record_id=2,
            source_system="kw_command",
            source_event_key="synthetic:2",
            kind="event",
            title="Recovered 2",
            occurred_at=timestamp,
            attributes_json="{}",
        ),
        CRMContactTimelineEvent(
            id=1,
            contact_id=1,
            source_record_id=1,
            source_system="kw_command",
            source_event_key="synthetic:1",
            kind="event",
            title="Recovered 1",
            occurred_at=timestamp,
            attributes_json="{}",
        ),
        CRMActivity(
            id=2,
            contact_id=1,
            kind="activity",
            summary="Activity 2",
            created_at=timestamp,
        ),
        CRMActivity(
            id=1,
            contact_id=1,
            kind="activity",
            summary="Activity 1",
            created_at=timestamp,
        ),
        Booking(
            id=1,
            lead_id=1,
            name="Booking",
            email="booking@example.test",
            meeting_type="booking",
            context="general",
            scheduled_at=timestamp,
            notes="",
        ),
        CRMContactTimelineEvent(
            id=3,
            contact_id=1,
            source_record_id=3,
            source_system="kw_command",
            source_event_key="synthetic:null",
            kind="event",
            title="No exposed timestamp",
            occurred_at=None,
            attributes_json="{}",
        ),
    ]
    await _flush(db, *(reversed(rows) if reverse else rows))


@pytest.mark.asyncio
async def test_exact_order_cursor_pages_deleted_bound_and_nullable_boundary(
    timeline_db: AsyncSession,
):
    await _seed_ordering_rows(timeline_db)
    expected = [
        "recovered:2",
        "recovered:1",
        "activity:2",
        "activity:1",
        "lead:1",
        "booking:1",
        "recovered:3",
    ]
    keys: list[str] = []
    cursor: str | None = None
    first_cursor: str | None = None
    while True:
        page = await list_contact_timeline(timeline_db, 1, cursor=cursor, page_size=2)
        keys.extend(row.key for row in page.rows)
        assert all(
            row.occurred_at is None or row.occurred_at.tzinfo is UTC
            for row in page.rows
        )
        if first_cursor is None:
            first_cursor = page.next_cursor
            assert first_cursor is not None
            bound = decode_timeline_cursor(first_cursor)
            assert bound.entity_id == 1 and bound.origin_rank == 0
            await timeline_db.delete(await timeline_db.get(CRMContactTimelineEvent, 1))
            await timeline_db.flush()
        if not page.has_more:
            assert page.next_cursor is None
            break
        assert page.next_cursor is not None
        cursor = page.next_cursor
    assert keys == expected
    beyond = await list_contact_timeline(
        timeline_db,
        1,
        cursor=encode_timeline_cursor(TimelineCursorV1(1, None, 0, 3)),
        page_size=2,
    )
    assert beyond.rows == () and beyond.next_cursor is None
    assert beyond.has_more is False

    never_existing_bound = await list_contact_timeline(
        timeline_db,
        1,
        cursor=encode_timeline_cursor(TimelineCursorV1(0, BASE_TIME, 1, 999_999)),
        page_size=20,
    )
    assert [row.key for row in never_existing_bound.rows] == [
        "activity:2",
        "activity:1",
        "lead:1",
        "booking:1",
        "recovered:3",
    ]


def test_timeline_timestamp_normalization_converts_offsets_and_assumes_db_naive_utc():
    offset = timezone(timedelta(hours=-4))
    assert _as_utc(datetime(2026, 8, 12, 8, tzinfo=offset)) == BASE_TIME
    assert _as_utc(BASE_TIME.replace(tzinfo=None)) == BASE_TIME
    assert _as_utc(None) is None


@pytest.mark.asyncio
async def test_far_future_microseconds_preserve_exact_order_across_origins(
    timeline_db: AsyncSession,
):
    earlier = datetime(3000, 1, 1, tzinfo=UTC)
    later = earlier + timedelta(microseconds=1)
    contact = CRMContact(id=1, first_name="Exact", last_name="Time", stage="lead")
    source = _source(1)
    await _flush(
        timeline_db,
        contact,
        source,
        *_timeline_ownership(source.id, contact_id=contact.id),
        CRMContactTimelineEvent(
            id=99,
            contact_id=contact.id,
            source_record_id=source.id,
            source_system="kw_command",
            source_event_key="synthetic:future",
            kind="event",
            title="Earlier recovered",
            occurred_at=earlier,
            attributes_json="{}",
        ),
        CRMActivity(
            id=1,
            contact_id=contact.id,
            kind="activity",
            summary="Later internal",
            created_at=later,
        ),
    )

    first = await list_contact_timeline(
        timeline_db, contact.id, cursor=None, page_size=1
    )
    assert [row.key for row in first.rows] == ["activity:1"]
    assert first.next_cursor is not None
    second = await list_contact_timeline(
        timeline_db, contact.id, cursor=first.next_cursor, page_size=1
    )
    assert [row.key for row in second.rows] == ["recovered:99"]
    assert second.has_more is False


@pytest.mark.asyncio
async def test_timeline_is_deterministic_when_fixture_insertion_is_reversed(
    tmp_path: Path,
):
    async def collect(path: Path, reverse: bool) -> tuple[str, ...]:
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Base.metadata.create_all(sync, tables=TABLES)
            )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            await _seed_ordering_rows(db, reverse=reverse)
            page = await list_contact_timeline(db, 1, cursor=None, page_size=20)
            result = tuple(row.key for row in page.rows)
        await engine.dispose()
        return result

    assert await collect(tmp_path / "forward.sqlite", False) == await collect(
        tmp_path / "reverse.sqlite", True
    )


@pytest.mark.asyncio
async def test_timeline_rejects_missing_contact_page_bounds_and_bad_cursor(
    timeline_db: AsyncSession,
):
    with pytest.raises(ContactNotFound):
        await list_contact_timeline(timeline_db, 999, cursor=None, page_size=10)
    await _flush(
        timeline_db,
        CRMContact(id=1, first_name="Empty", last_name="Contact", stage="lead"),
    )
    for invalid_size in (0, 101, True):
        with pytest.raises(ValueError):
            await list_contact_timeline(
                timeline_db, 1, cursor=None, page_size=invalid_size
            )
    with pytest.raises(ValueError):
        await list_contact_timeline(
            timeline_db, 1, cursor="tampered-cursor", page_size=10
        )
    empty = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    assert empty.rows == () and empty.next_cursor is None and empty.has_more is False


@pytest.mark.asyncio
async def test_origin_queries_are_bounded_and_mirrors_do_not_underfill_page(
    timeline_db: AsyncSession,
):
    lead = Lead(id=1, name="Lead", created_at=BASE_TIME - timedelta(days=20))
    contact = CRMContact(
        id=1,
        lead_id=1,
        first_name="Bounded",
        last_name="Contact",
        stage="lead",
    )
    await _flush(timeline_db, lead, contact)
    for index in range(1, 7):
        source = _source(index)
        recovered = CRMContactTimelineEvent(
            id=index,
            contact_id=1,
            source_record_id=index,
            source_system="kw_command",
            source_event_key=f"synthetic:{index}",
            kind="event",
            title=f"Recovered {index}",
            occurred_at=BASE_TIME - timedelta(days=index),
            attributes_json="{}",
        )
        mirrored = CRMActivity(
            id=index,
            contact_id=1,
            source_record_id=index,
            kind="event",
            summary=f"Recovered {index}",
            created_at=BASE_TIME - timedelta(days=index),
        )
        await _flush(
            timeline_db,
            source,
            *_timeline_ownership(source.id, contact_id=contact.id),
            recovered,
            mirrored,
        )
    for index in range(7, 12):
        await _flush(
            timeline_db,
            CRMActivity(
                id=index,
                contact_id=1,
                kind="unique",
                summary=f"Unique {index}",
                created_at=BASE_TIME - timedelta(days=index),
            ),
        )
    for index in range(1, 6):
        await _flush(
            timeline_db,
            Booking(
                id=index,
                lead_id=1,
                name="Booking",
                email="booking@example.test",
                meeting_type="booking",
                context="general",
                scheduled_at=BASE_TIME - timedelta(days=index),
                notes="",
            ),
        )

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    assert timeline_db.bind is not None
    event.listen(timeline_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=3)
    finally:
        event.remove(timeline_db.bind.sync_engine, "before_cursor_execute", capture)

    assert len(page.rows) == 3 and page.has_more is True
    origin_statements = [
        statement
        for statement in statements
        if any(
            table in statement
            for table in (
                "crm_contact_timeline_events",
                "crm_activities",
                "FROM leads",
                "FROM bookings",
            )
        )
    ]
    assert len(origin_statements) == 6
    assert all("LIMIT" in statement.upper() for statement in origin_statements)

    keys = [row.key for row in page.rows]
    cursor = page.next_cursor
    while cursor is not None:
        page = await list_contact_timeline(timeline_db, 1, cursor=cursor, page_size=3)
        keys.extend(row.key for row in page.rows)
        cursor = page.next_cursor
    assert not any(
        key.startswith("activity:") and int(key.split(":")[1]) <= 6 for key in keys
    )
    assert {f"activity:{index}" for index in range(7, 12)} <= set(keys)
