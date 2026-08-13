"""Deterministic query and mutation services for Command Contacts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from models.command import CRMActivity, CRMContact, CRMContactTag, CRMTag
from models.command_contacts import (
    CRMContactCapturePosition,
    CRMContactMethod,
    CRMContactOwnership,
    CRMContactProfile,
    CRMContactSectionCapture,
    CRMContactTimelineEvent,
)
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from models.lead import Lead  # noqa: F401 - registers the FK target in metadata
from services.command_contact_contracts import (
    CONTACT_TOUCH_ACTIVITY_KINDS,
    ContactDirectoryFilters,
    ContactOriginFilter,
    ContactSmartView,
    ContactSortKey,
    ContactSourceFilter,
    SortDirection,
)
from services.command_contacts import (
    ContactDataIntegrityError,
    ContactDirectoryError,
    ContactLinkConflict,
    ContactNotFound,
    ContactNotInDirectory,
    ContactSectionUnsupported,
    get_contact_neighbors,
    list_contacts,
)


NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture()
async def service_db(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'command-contacts-service.sqlite'}"
    )

    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine.sync_engine, "connect", enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _source_record(index: int) -> CRMSourceRecord:
    return CRMSourceRecord(
        source_system="kw_command",
        module="contacts",
        record_kind="contact_profile",
        source_key=f"synthetic:contact-profile:{index:04d}",
        evidence_level="observed_record",
        display_label="synthetic contact",
        payload_json="{}",
        capture_quality="complete",
        captured_at=NOW,
        parser_version="contacts-service-test-v1",
    )


async def _add_timeline_capture(
    db: AsyncSession,
    contact: CRMContact,
    index: int,
    *,
    quality: str = "complete",
    is_empty: bool = True,
    row_count: int = 0,
    limitations_json: str = "[]",
    captured_at: datetime | None = NOW,
) -> tuple[CRMContactCapturePosition, CRMContactSectionCapture]:
    position_source = _source_record(index * 10)
    position_source.record_kind = "contact_capture_position"
    position_source.source_key = f"synthetic:position:{index:04d}"
    section_source = _source_record(index * 10 + 1)
    section_source.record_kind = "contact_section_capture"
    section_source.source_key = f"synthetic:position:{index:04d}:timeline"
    db.add_all([position_source, section_source])
    await db.flush()
    position = CRMContactCapturePosition(
        contact_id=contact.id,
        source_record_id=position_source.id,
        bundle_fingerprint=f"{index:064x}",
        capture_ordinal=index,
        source_contact_id=f"{index:024x}",
        captured_at=captured_at,
        capture_quality=quality,
        limitations_json=limitations_json,
    )
    db.add(position)
    await db.flush()
    section = CRMContactSectionCapture(
        capture_position_id=position.id,
        source_record_id=section_source.id,
        section_name="timeline",
        captured_at=captured_at,
        capture_quality=quality,
        is_empty=is_empty,
        row_count=row_count,
        limitations_json=limitations_json,
    )
    db.add(section)
    await db.flush()
    return position, section


def test_contact_service_error_taxonomy_has_no_http_dependency():
    assert issubclass(ContactNotFound, LookupError)
    assert issubclass(ContactNotInDirectory, ContactDirectoryError)
    assert issubclass(ContactDataIntegrityError, ContactDirectoryError)
    assert issubclass(ContactLinkConflict, ContactDataIntegrityError)
    assert issubclass(ContactSectionUnsupported, ValueError)
    for error_type in (
        ContactDirectoryError,
        ContactNotFound,
        ContactNotInDirectory,
        ContactDataIntegrityError,
        ContactLinkConflict,
        ContactSectionUnsupported,
    ):
        assert error_type.__module__ == "services.command_contacts"


def test_contact_tag_model_matches_the_deployed_unique_constraint():
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in CRMContactTag.__table__.constraints
        if constraint.name is not None
    }
    assert constraints["uq_crm_contact_tag"] == ("contact_id", "tag_id")


@pytest.mark.asyncio
async def test_contact_tag_uniqueness_is_enforced_in_metadata_created_databases(
    service_db: AsyncSession,
):
    contact = CRMContact(first_name="Tag", last_name="Owner", stage="lead")
    tag = CRMTag(name="synthetic-tag")
    service_db.add_all([contact, tag])
    await service_db.flush()
    service_db.add_all(
        [
            CRMContactTag(contact_id=contact.id, tag_id=tag.id),
            CRMContactTag(contact_id=contact.id, tag_id=tag.id),
        ]
    )
    with pytest.raises(IntegrityError):
        await service_db.flush()


@pytest.mark.asyncio
async def test_directory_exact_combined_truth_and_source_origin_filters_are_bounded(
    service_db: AsyncSession,
):
    service_db.add_all(
        Lead(
            id=index,
            name=f"Synthetic lead {index:02d}",
            routing_status="lead",
        )
        for index in range(1, 52)
    )
    await service_db.flush()
    contacts = [
        CRMContact(
            first_name=f"Synthetic {index:03d}",
            last_name="Contact",
            stage="lead",
            lead_id=(index - 315 if 316 <= index <= 366 else None),
        )
        for index in range(1, 367)
    ]
    service_db.add_all(contacts)
    await service_db.flush()
    sources = [_source_record(index) for index in range(1, 318)]
    service_db.add_all(sources)
    await service_db.flush()
    service_db.add_all(
        CRMEntitySource(
            entity_type="contact",
            entity_id=contacts[index - 1].id,
            source_record_id=sources[index - 1].id,
        )
        for index in range(1, 318)
    )
    await service_db.flush()

    selects: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(" ".join(statement.split()))

    assert service_db.bind is not None
    event.listen(service_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        first = await list_contacts(
            service_db,
            ContactDirectoryFilters(page=1, page_size=100),
            now=NOW,
        )
    finally:
        event.remove(service_db.bind.sync_engine, "before_cursor_execute", capture)

    assert first.total == 366
    assert first.page_count == 4
    assert len(first.rows) == 100
    assert len(selects) <= 8
    final = await list_contacts(
        service_db,
        ContactDirectoryFilters(page=4, page_size=100),
        now=NOW,
    )
    assert len(final.rows) == 66
    beyond = await list_contacts(
        service_db,
        ContactDirectoryFilters(page=5, page_size=100),
        now=NOW,
    )
    assert (beyond.page, beyond.page_count, beyond.rows) == (5, 4, ())

    async def total(**kwargs) -> int:
        page = await list_contacts(
            service_db,
            ContactDirectoryFilters(page_size=1, **kwargs),
            now=NOW,
        )
        return page.total

    assert await total(origins=(ContactOriginFilter.RECOVERED,)) == 317
    assert await total(origins=(ContactOriginFilter.LEAD_BACKED,)) == 51
    assert await total(origins=(ContactOriginFilter.LEGACY_ONLY,)) == 49
    assert await total(origins=(ContactOriginFilter.INTERNAL_ONLY,)) == 0
    assert await total(sources=(ContactSourceFilter.KW_COMMAND,)) == 317
    assert await total(sources=(ContactSourceFilter.LEGACY_LEAD,)) == 51
    assert await total(sources=(ContactSourceFilter.INTERNAL_CRM,)) == 0
    assert await total(
        sources=(ContactSourceFilter.KW_COMMAND, ContactSourceFilter.LEGACY_LEAD)
    ) == 366
    assert await total(
        sources=(ContactSourceFilter.KW_COMMAND,),
        origins=(ContactOriginFilter.LEAD_BACKED,),
    ) == 2

    overlap = first.rows[0]
    assert overlap.origins in {
        (ContactOriginFilter.RECOVERED,),
        (
            ContactOriginFilter.RECOVERED,
            ContactOriginFilter.LEAD_BACKED,
        ),
    }


@pytest.mark.asyncio
async def test_literal_search_escapes_wildcards_and_searches_primary_email(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(
            first_name="Email",
            last_name="Owner",
            email="Primary.Owner@Example.Test",
            stage="lead",
        ),
        CRMContact(first_name="Percent%Only", last_name="Value", stage="lead"),
        CRMContact(first_name="Under_score", last_name="Value", stage="lead"),
        CRMContact(first_name="Back\\slash", last_name="Value", stage="lead"),
        CRMContact(first_name="Ordinary", last_name="Noise", stage="lead"),
    ]
    service_db.add_all(contacts)
    await service_db.flush()

    async def matching_ids(query: str) -> tuple[int, ...]:
        page = await list_contacts(
            service_db,
            ContactDirectoryFilters(query=query),
            now=NOW,
        )
        return tuple(row.id for row in page.rows)

    assert await matching_ids("primary.owner@example.test") == (contacts[0].id,)
    assert await matching_ids("%") == (contacts[1].id,)
    assert await matching_ids("_") == (contacts[2].id,)
    assert await matching_ids("\\") == (contacts[3].id,)


@pytest.mark.asyncio
async def test_literal_search_covers_profile_and_normalized_method_fields(
    service_db: AsyncSession,
):
    contact = CRMContact(first_name="Synthetic", last_name="Search", stage="lead")
    service_db.add(contact)
    await service_db.flush()
    service_db.add_all(
        [
            CRMContactProfile(
                contact_id=contact.id,
                legal_name="Legal Needle",
                preferred_name="Preferred Needle",
                company="Company Needle",
                title="Title Needle",
                birth_year_quality="unknown",
                anniversary_year_quality="unknown",
            ),
            CRMContactMethod(
                contact_id=contact.id,
                source_key="synthetic:search:method",
                kind="phone",
                normalized_value="+15550123456",
                is_primary=True,
            ),
        ]
    )
    await service_db.flush()

    for query in (
        "legal needle",
        "preferred needle",
        "company needle",
        "title needle",
        "+15550123456",
    ):
        page = await list_contacts(
            service_db, ContactDirectoryFilters(query=query), now=NOW
        )
        assert tuple(row.id for row in page.rows) == (contact.id,)
    no_match = await list_contacts(
        service_db, ContactDirectoryFilters(query="missing"), now=NOW
    )
    assert (no_match.total, no_match.page_count, no_match.rows) == (0, 0, ())


@pytest.mark.asyncio
async def test_actor_all_tags_and_health_filters_are_anded(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(first_name=name, last_name="Filter", stage="lead")
        for name in ("Exact", "Missing tag", "Wrong assignee", "Wrong health")
    ]
    tags = [CRMTag(name="tag-one"), CRMTag(name="tag-two")]
    service_db.add_all([*contacts, *tags])
    await service_db.flush()
    service_db.add_all(
        CRMContactProfile(
            contact_id=contact.id,
            health_score=health,
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        )
        for contact, health in zip(contacts, (60, 60, 60, 90), strict=True)
    )
    for index, contact in enumerate(contacts, start=1):
        service_db.add_all(
            [
                CRMContactOwnership(
                    contact_id=contact.id,
                    source_key=f"synthetic:{index}:owner",
                    role="owner",
                    provider_actor_id="owner-1",
                    display_name="Owner",
                    is_primary=True,
                ),
                CRMContactOwnership(
                    contact_id=contact.id,
                    source_key=f"synthetic:{index}:assignee",
                    role="assignee",
                    provider_actor_id=(
                        "assignee-2" if index == 3 else "assignee-1"
                    ),
                    display_name="Assignee",
                    is_primary=True,
                ),
            ]
        )
    service_db.add_all(
        [
            CRMContactTag(contact_id=contacts[0].id, tag_id=tags[0].id),
            CRMContactTag(contact_id=contacts[0].id, tag_id=tags[1].id),
            CRMContactTag(contact_id=contacts[1].id, tag_id=tags[0].id),
            CRMContactTag(contact_id=contacts[2].id, tag_id=tags[0].id),
            CRMContactTag(contact_id=contacts[2].id, tag_id=tags[1].id),
            CRMContactTag(contact_id=contacts[3].id, tag_id=tags[0].id),
            CRMContactTag(contact_id=contacts[3].id, tag_id=tags[1].id),
        ]
    )
    await service_db.flush()

    page = await list_contacts(
        service_db,
        ContactDirectoryFilters(
            owner_actor_id="owner-1",
            assignee_actor_id="assignee-1",
            tag_ids=(tags[0].id, tags[1].id),
            health_min=50,
            health_max=70,
        ),
        now=NOW,
    )
    assert tuple(row.id for row in page.rows) == (contacts[0].id,)
    assert page.rows[0].owner is not None
    assert page.rows[0].owner.provider_actor_id == "owner-1"
    assert page.rows[0].assignee is not None
    assert page.rows[0].assignee.provider_actor_id == "assignee-1"
    assert tuple(tag.id for tag in page.rows[0].tags) == (
        tags[0].id,
        tags[1].id,
    )


@pytest.mark.asyncio
async def test_celebration_filters_and_rows_share_exact_valid_eligibility(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(first_name=label, last_name="Celebration", stage="lead")
        for label in (
            "Verified",
            "Yearless",
            "Sentinel",
            "Unknown",
            "Impossible",
            "Missing year",
            "Internal wins",
            "Anniversary",
        )
    ]
    contacts[6].birthday = date(1990, 8, 27)
    service_db.add_all(contacts)
    await service_db.flush()
    profiles = [
        CRMContactProfile(
            contact_id=contacts[0].id,
            birth_month=8,
            birth_day=30,
            birth_year=1988,
            birth_year_quality="verified",
            anniversary_year_quality="unknown",
        ),
        CRMContactProfile(
            contact_id=contacts[1].id,
            birth_month=8,
            birth_day=31,
            birth_year=None,
            birth_year_quality="yearless",
            anniversary_year_quality="unknown",
        ),
        CRMContactProfile(
            contact_id=contacts[2].id,
            birth_month=8,
            birth_day=29,
            birth_year=None,
            birth_year_quality="sentinel",
            anniversary_year_quality="unknown",
        ),
        CRMContactProfile(
            contact_id=contacts[3].id,
            birth_month=8,
            birth_day=28,
            birth_year=None,
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        ),
        CRMContactProfile(
            contact_id=contacts[4].id,
            birth_month=4,
            birth_day=31,
            birth_year=None,
            birth_year_quality="yearless",
            anniversary_year_quality="unknown",
        ),
        CRMContactProfile(
            contact_id=contacts[5].id,
            birth_month=8,
            birth_day=26,
            birth_year=None,
            birth_year_quality="verified",
            anniversary_year_quality="unknown",
        ),
        CRMContactProfile(
            contact_id=contacts[6].id,
            birth_month=4,
            birth_day=31,
            birth_year=None,
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        ),
        CRMContactProfile(
            contact_id=contacts[7].id,
            birth_year_quality="unknown",
            anniversary_month=8,
            anniversary_day=25,
            anniversary_year=2020,
            anniversary_year_quality="verified",
        ),
    ]
    service_db.add_all(profiles)
    await service_db.flush()

    all_rows = await list_contacts(
        service_db, ContactDirectoryFilters(page_size=100), now=NOW
    )
    projected = {
        row.id: row.birthday
        for row in all_rows.rows
        if row.birthday is not None
    }
    august = await list_contacts(
        service_db,
        ContactDirectoryFilters(birthday_month=8, page_size=100),
        now=NOW,
    )
    smart_view = await list_contacts(
        service_db,
        ContactDirectoryFilters(
            smart_view=ContactSmartView.BIRTHDAYS_THIS_MONTH,
            page_size=100,
        ),
        now=NOW,
    )
    expected_ids = {
        contacts[0].id,
        contacts[1].id,
        contacts[2].id,
        contacts[6].id,
    }
    assert set(projected) == expected_ids
    assert {row.id for row in august.rows} == expected_ids
    assert {row.id for row in smart_view.rows} == expected_ids
    assert projected[contacts[0].id].year == 1988
    assert projected[contacts[0].id].year_quality == "verified"
    assert projected[contacts[1].id].year is None
    assert projected[contacts[1].id].year_quality == "yearless"
    assert projected[contacts[2].id].year is None
    assert projected[contacts[2].id].year_quality == "sentinel"
    assert projected[contacts[6].id].origin == "internal_crm"
    april = await list_contacts(
        service_db,
        ContactDirectoryFilters(birthday_month=4, page_size=100),
        now=NOW,
    )
    assert april.rows == ()
    anniversaries = await list_contacts(
        service_db,
        ContactDirectoryFilters(
            smart_view=ContactSmartView.ANNIVERSARIES_THIS_MONTH,
            page_size=100,
        ),
        now=NOW,
    )
    assert tuple(row.id for row in anniversaries.rows) == (contacts[7].id,)
    assert anniversaries.rows[0].anniversary is not None
    assert anniversaries.rows[0].anniversary.year == 2020


@pytest.mark.asyncio
async def test_smart_views_use_authoritative_contact_evidence_and_injected_now(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(first_name=label, last_name="SmartView", stage=stage)
        for label, stage in (
            ("Never", " Lead "),
            ("Wrong stage", "active"),
            ("Partial", "lead"),
            ("Nonempty", "lead"),
            ("Limited", "lead"),
            ("Contacted", "lead"),
            ("Touched", "lead"),
            ("Exact kind only", "lead"),
            ("No capture", "lead"),
            ("Latest empty", "lead"),
            ("Latest nonempty", "lead"),
            ("Recent start", "active"),
            ("Recent end", "active"),
            ("Recent old", "active"),
            ("Recent future", "active"),
        )
    ]
    service_db.add_all(contacts)
    await service_db.flush()
    profiles = []
    for index, contact in enumerate(contacts):
        last_contacted = NOW if index == 5 else None
        last_interaction = {
            11: NOW - timedelta(days=30),
            12: NOW,
            13: NOW - timedelta(days=30, microseconds=1),
            14: NOW + timedelta(microseconds=1),
        }.get(index)
        profiles.append(
            CRMContactProfile(
                contact_id=contact.id,
                last_contacted_at=last_contacted,
                last_interaction_at=last_interaction,
                birth_year_quality="unknown",
                anniversary_year_quality="unknown",
            )
        )
    service_db.add_all(profiles)
    await service_db.flush()

    await _add_timeline_capture(service_db, contacts[0], 1)
    await _add_timeline_capture(service_db, contacts[1], 2)
    await _add_timeline_capture(service_db, contacts[2], 3, quality="partial")
    await _add_timeline_capture(
        service_db, contacts[3], 4, is_empty=False, row_count=1
    )
    await _add_timeline_capture(
        service_db, contacts[4], 5, limitations_json='["limited"]'
    )
    await _add_timeline_capture(service_db, contacts[5], 6)
    await _add_timeline_capture(service_db, contacts[6], 7)
    await _add_timeline_capture(service_db, contacts[7], 8)
    await _add_timeline_capture(
        service_db,
        contacts[9],
        10,
        is_empty=False,
        row_count=1,
        captured_at=NOW - timedelta(days=2),
    )
    await _add_timeline_capture(
        service_db, contacts[9], 11, captured_at=NOW - timedelta(days=1)
    )
    await _add_timeline_capture(
        service_db,
        contacts[10],
        12,
        captured_at=NOW - timedelta(days=2),
    )
    await _add_timeline_capture(
        service_db,
        contacts[10],
        13,
        is_empty=False,
        row_count=1,
        captured_at=NOW - timedelta(days=1),
    )
    service_db.add_all(
        [
            CRMActivity(
                contact_id=contacts[6].id,
                kind="call",
                summary="Synthetic touch",
            ),
            CRMActivity(
                contact_id=contacts[7].id,
                kind=" CALL ",
                summary="Noncanonical administrative kind",
            ),
            CRMActivity(
                contact_id=contacts[0].id,
                kind="contact_created",
                summary="Administrative event",
            ),
        ]
    )
    await service_db.flush()

    never = await list_contacts(
        service_db,
        ContactDirectoryFilters(
            smart_view=ContactSmartView.NEVER_CONTACTED,
            page_size=100,
        ),
        now=NOW,
    )
    assert {row.id for row in never.rows} == {
        contacts[0].id,
        contacts[7].id,
        contacts[9].id,
    }

    recent = await list_contacts(
        service_db,
        ContactDirectoryFilters(
            smart_view=ContactSmartView.RECENTLY_ACTIVE,
            page_size=100,
        ),
        now=NOW,
    )
    assert {row.id for row in recent.rows} == {
        contacts[11].id,
        contacts[12].id,
    }
    moved_now = await list_contacts(
        service_db,
        ContactDirectoryFilters(
            smart_view=ContactSmartView.RECENTLY_ACTIVE,
            page_size=100,
        ),
        now=NOW + timedelta(days=31),
    )
    assert moved_now.rows == ()


@pytest.mark.asyncio
async def test_never_contacted_distinguishes_no_capture_missing_cell_and_contradiction(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(first_name=label, last_name="Evidence", stage="lead")
        for label in ("No capture", "Missing cell", "Contradiction", "Complete")
    ]
    service_db.add_all(contacts)
    await service_db.flush()
    service_db.add_all(
        CRMContactProfile(
            contact_id=contact.id,
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        )
        for contact in contacts
    )
    await service_db.flush()
    _position, missing_cell = await _add_timeline_capture(
        service_db, contacts[1], 20
    )
    await service_db.delete(missing_cell)
    await _add_timeline_capture(
        service_db,
        contacts[2],
        21,
        is_empty=False,
        row_count=0,
    )
    await _add_timeline_capture(service_db, contacts[3], 22)
    await service_db.flush()

    page = await list_contacts(
        service_db,
        ContactDirectoryFilters(
            smart_view=ContactSmartView.NEVER_CONTACTED,
            page_size=100,
        ),
        now=NOW,
    )
    assert tuple(row.id for row in page.rows) == (contacts[3].id,)


@pytest.mark.asyncio
@pytest.mark.parametrize("quality", ("shell", "error"))
async def test_never_contacted_rejects_shell_and_error_timeline_cells(
    service_db: AsyncSession,
    quality: str,
):
    contact = CRMContact(first_name=quality, last_name="Quality", stage="lead")
    service_db.add(contact)
    await service_db.flush()
    service_db.add(
        CRMContactProfile(
            contact_id=contact.id,
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        )
    )
    await _add_timeline_capture(service_db, contact, 30, quality=quality)
    await service_db.flush()

    page = await list_contacts(
        service_db,
        ContactDirectoryFilters(smart_view=ContactSmartView.NEVER_CONTACTED),
        now=NOW,
    )
    assert page.rows == ()


@pytest.mark.asyncio
async def test_complete_null_timestamp_uses_deterministic_latest_id_tie_break(
    service_db: AsyncSession,
):
    sole = CRMContact(first_name="Sole null", last_name="Capture", stage="lead")
    latest = CRMContact(first_name="Latest null", last_name="Capture", stage="lead")
    service_db.add_all([sole, latest])
    await service_db.flush()
    service_db.add_all(
        CRMContactProfile(
            contact_id=contact.id,
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        )
        for contact in (sole, latest)
    )
    await _add_timeline_capture(service_db, sole, 40, captured_at=None)
    await _add_timeline_capture(
        service_db,
        latest,
        41,
        is_empty=False,
        row_count=1,
        captured_at=None,
    )
    await _add_timeline_capture(
        service_db,
        latest,
        42,
        captured_at=None,
    )
    await service_db.flush()

    page = await list_contacts(
        service_db,
        ContactDirectoryFilters(
            smart_view=ContactSmartView.NEVER_CONTACTED,
            page_size=100,
        ),
        now=NOW,
    )
    assert {row.id for row in page.rows} == {sole.id, latest.id}


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse_insertion", (False, True))
async def test_authoritative_capture_is_independent_of_insertion_order(
    service_db: AsyncSession,
    reverse_insertion: bool,
):
    contact = CRMContact(first_name="Order", last_name="Independent", stage="lead")
    service_db.add(contact)
    await service_db.flush()
    service_db.add(
        CRMContactProfile(
            contact_id=contact.id,
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        )
    )
    captures: tuple[tuple[int, bool, int, datetime], ...] = (
        (50, False, 1, NOW - timedelta(days=1)),
        (51, True, 0, NOW),
    )
    ordered = tuple(reversed(captures)) if reverse_insertion else captures
    for index, is_empty, row_count, captured_at in ordered:
        await _add_timeline_capture(
            service_db,
            contact,
            index,
            is_empty=is_empty,
            row_count=row_count,
            captured_at=captured_at,
        )
    await service_db.flush()

    page = await list_contacts(
        service_db,
        ContactDirectoryFilters(smart_view=ContactSmartView.NEVER_CONTACTED),
        now=NOW,
    )
    assert tuple(row.id for row in page.rows) == (contact.id,)


@pytest.mark.asyncio
@pytest.mark.parametrize("touch_kind", tuple(sorted(CONTACT_TOUCH_ACTIVITY_KINDS)))
async def test_every_exact_touch_kind_excludes_never_contacted(
    service_db: AsyncSession,
    touch_kind: str,
):
    contact = CRMContact(first_name=touch_kind, last_name="Touch", stage="lead")
    service_db.add(contact)
    await service_db.flush()
    service_db.add(
        CRMContactProfile(
            contact_id=contact.id,
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        )
    )
    await _add_timeline_capture(service_db, contact, 60)
    service_db.add(
        CRMActivity(
            contact_id=contact.id,
            kind=touch_kind,
            summary="Synthetic exact touch",
        )
    )
    await service_db.flush()

    page = await list_contacts(
        service_db,
        ContactDirectoryFilters(smart_view=ContactSmartView.NEVER_CONTACTED),
        now=NOW,
    )
    assert page.rows == ()


async def _add_recovered_timeline_event(
    db: AsyncSession,
    contact: CRMContact,
    index: int,
) -> CRMContactTimelineEvent:
    source = _source_record(1_000 + index)
    source.record_kind = "contact_timeline_event"
    source.source_key = f"synthetic:timeline-event:{index:04d}"
    db.add(source)
    await db.flush()
    event = CRMContactTimelineEvent(
        contact_id=contact.id,
        source_record_id=source.id,
        source_system="kw_command",
        source_event_key=f"synthetic-event-{index:04d}",
        kind="call",
        title="Synthetic recovered event",
        occurred_at=NOW,
    )
    db.add(event)
    await db.flush()
    return event


@pytest.mark.asyncio
async def test_recovered_events_and_their_mirrored_activities_preserve_exclusion(
    service_db: AsyncSession,
):
    event_only = CRMContact(first_name="Event", last_name="Only", stage="lead")
    mirrored = CRMContact(first_name="Mirrored", last_name="Event", stage="lead")
    non_mirrored = CRMContact(first_name="Broken", last_name="Mirror", stage="lead")
    service_db.add_all([event_only, mirrored, non_mirrored])
    await service_db.flush()
    service_db.add_all(
        CRMContactProfile(
            contact_id=contact.id,
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        )
        for contact in (event_only, mirrored, non_mirrored)
    )
    for index, contact in enumerate((event_only, mirrored, non_mirrored), start=70):
        await _add_timeline_capture(service_db, contact, index)
    event_without_mirror = await _add_recovered_timeline_event(
        service_db, event_only, 1
    )
    mirrored_event = await _add_recovered_timeline_event(service_db, mirrored, 2)
    source_without_event = _source_record(1_003)
    source_without_event.record_kind = "contact_timeline_event"
    source_without_event.source_key = "synthetic:timeline-event:0003"
    service_db.add(source_without_event)
    await service_db.flush()
    service_db.add_all(
        [
            CRMActivity(
                contact_id=mirrored.id,
                source_record_id=mirrored_event.source_record_id,
                kind="call",
                summary="Mirrored recovered touch",
            ),
            CRMActivity(
                contact_id=non_mirrored.id,
                source_record_id=source_without_event.id,
                kind="call",
                summary="Missing recovered counterpart",
            ),
        ]
    )
    await service_db.flush()

    page = await list_contacts(
        service_db,
        ContactDirectoryFilters(
            smart_view=ContactSmartView.NEVER_CONTACTED,
            page_size=100,
        ),
        now=NOW,
    )
    assert page.rows == ()
    assert event_without_mirror.source_record_id != mirrored_event.source_record_id


@pytest.mark.asyncio
async def test_leap_day_eligibility_accepts_verified_leap_and_yearless_only(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(first_name=label, last_name="Leap", stage="lead")
        for label in ("Verified leap", "Verified common", "Yearless")
    ]
    service_db.add_all(contacts)
    await service_db.flush()
    service_db.add_all(
        [
            CRMContactProfile(
                contact_id=contacts[0].id,
                birth_month=2,
                birth_day=29,
                birth_year=2000,
                birth_year_quality="verified",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[1].id,
                birth_month=2,
                birth_day=29,
                birth_year=1900,
                birth_year_quality="verified",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[2].id,
                birth_month=2,
                birth_day=29,
                birth_year=None,
                birth_year_quality="yearless",
                anniversary_year_quality="unknown",
            ),
        ]
    )
    await service_db.flush()

    page = await list_contacts(
        service_db,
        ContactDirectoryFilters(birthday_month=2, page_size=100),
        now=NOW,
    )
    assert tuple(row.id for row in page.rows) == (
        contacts[0].id,
        contacts[2].id,
    )
    by_id = {row.id: row.birthday for row in page.rows}
    assert by_id[contacts[0].id] is not None
    assert by_id[contacts[0].id].year == 2000
    assert by_id[contacts[2].id] is not None
    assert by_id[contacts[2].id].year is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sort", "direction", "expected_names"),
    [
        (ContactSortKey.NAME, SortDirection.ASC, ("Able", "Baker", "Charlie")),
        (ContactSortKey.NAME, SortDirection.DESC, ("Charlie", "Baker", "Able")),
        (ContactSortKey.STAGE, SortDirection.ASC, ("Baker", "Charlie", "Able")),
        (ContactSortKey.STAGE, SortDirection.DESC, ("Able", "Charlie", "Baker")),
        (ContactSortKey.HEALTH_SCORE, SortDirection.ASC, ("Able", "Baker", "Charlie")),
        (ContactSortKey.HEALTH_SCORE, SortDirection.DESC, ("Baker", "Able", "Charlie")),
        (ContactSortKey.LAST_CONTACTED_AT, SortDirection.ASC, ("Able", "Baker", "Charlie")),
        (ContactSortKey.LAST_CONTACTED_AT, SortDirection.DESC, ("Baker", "Able", "Charlie")),
        (ContactSortKey.LAST_INTERACTION_AT, SortDirection.ASC, ("Baker", "Able", "Charlie")),
        (ContactSortKey.LAST_INTERACTION_AT, SortDirection.DESC, ("Able", "Baker", "Charlie")),
        (ContactSortKey.CREATED_AT, SortDirection.ASC, ("Able", "Baker", "Charlie")),
        (ContactSortKey.CREATED_AT, SortDirection.DESC, ("Charlie", "Baker", "Able")),
        (ContactSortKey.UPDATED_AT, SortDirection.ASC, ("Baker", "Charlie", "Able")),
        (ContactSortKey.UPDATED_AT, SortDirection.DESC, ("Able", "Charlie", "Baker")),
    ],
)
async def test_every_directory_sort_direction_and_null_last(
    service_db: AsyncSession,
    sort: ContactSortKey,
    direction: SortDirection,
    expected_names: tuple[str, ...],
):
    contacts = [
        CRMContact(
            first_name="Synthetic",
            last_name=last_name,
            stage=stage,
            created_at=created_at,
            updated_at=updated_at,
        )
        for last_name, stage, created_at, updated_at in (
            ("Able", "zebra", NOW - timedelta(days=3), NOW),
            ("Baker", "alpha", NOW - timedelta(days=2), NOW - timedelta(days=2)),
            ("Charlie", "middle", NOW - timedelta(days=1), NOW - timedelta(days=1)),
        )
    ]
    service_db.add_all(contacts)
    await service_db.flush()
    service_db.add_all(
        [
            CRMContactProfile(
                contact_id=contacts[0].id,
                health_score=10,
                last_contacted_at=NOW - timedelta(days=3),
                last_interaction_at=NOW - timedelta(days=1),
                birth_year_quality="unknown",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[1].id,
                health_score=20,
                last_contacted_at=NOW - timedelta(days=1),
                last_interaction_at=NOW - timedelta(days=3),
                birth_year_quality="unknown",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[2].id,
                health_score=None,
                last_contacted_at=None,
                last_interaction_at=None,
                birth_year_quality="unknown",
                anniversary_year_quality="unknown",
            ),
        ]
    )
    await service_db.flush()

    filters = ContactDirectoryFilters(
        sort=sort,
        direction=direction,
        page_size=1,
    )
    page = await list_contacts(service_db, filters, now=NOW)
    all_rows = await list_contacts(
        service_db,
        ContactDirectoryFilters(
            sort=sort,
            direction=direction,
            page_size=100,
        ),
        now=NOW,
    )
    assert tuple(row.last_name for row in all_rows.rows) == expected_names
    assert page.rows[0].last_name == expected_names[0]
    middle_id = all_rows.rows[1].id
    neighbors = await get_contact_neighbors(
        service_db, middle_id, filters, now=NOW
    )
    assert neighbors.previous_contact_id == all_rows.rows[0].id
    assert neighbors.next_contact_id == all_rows.rows[2].id


@pytest.mark.asyncio
async def test_sort_ties_and_neighbor_ids_follow_requested_direction(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(first_name="Same", last_name="Name", stage="lead")
        for _ in range(3)
    ]
    service_db.add_all(contacts)
    await service_db.flush()
    for direction, expected in (
        (SortDirection.ASC, contacts),
        (SortDirection.DESC, tuple(reversed(contacts))),
    ):
        filters = ContactDirectoryFilters(
            sort=ContactSortKey.STAGE,
            direction=direction,
            page_size=1,
        )
        page = await list_contacts(
            service_db,
            ContactDirectoryFilters(
                sort=ContactSortKey.STAGE,
                direction=direction,
                page_size=100,
            ),
            now=NOW,
        )
        expected_ids = tuple(contact.id for contact in expected)
        assert tuple(row.id for row in page.rows) == expected_ids
        neighbors = await get_contact_neighbors(
            service_db, expected_ids[1], filters, now=NOW
        )
        assert (
            neighbors.previous_contact_id,
            neighbors.next_contact_id,
        ) == (expected_ids[0], expected_ids[2])


@pytest.mark.asyncio
async def test_neighbors_use_the_same_filtered_universe(service_db: AsyncSession):
    contacts = [
        CRMContact(first_name=first, last_name=last, stage=stage)
        for first, last, stage in (
            ("A", "Able", "lead"),
            ("B", "Baker", "lead"),
            ("C", "Charlie", "active"),
            ("D", "Delta", "lead"),
        )
    ]
    service_db.add_all(contacts)
    await service_db.flush()
    filters = ContactDirectoryFilters(stage="lead", page_size=2)

    middle = await get_contact_neighbors(
        service_db, contacts[1].id, filters, now=NOW
    )
    assert (middle.previous_contact_id, middle.next_contact_id) == (
        contacts[0].id,
        contacts[3].id,
    )
    with pytest.raises(ContactNotInDirectory):
        await get_contact_neighbors(service_db, contacts[2].id, filters, now=NOW)
    with pytest.raises(ContactNotFound):
        await get_contact_neighbors(service_db, 999_999, filters, now=NOW)
