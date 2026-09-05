"""Deterministic query and mutation services for Command Contacts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from models.booking import Booking
from models.command import (
    CRMActivity,
    CRMContact,
    CRMContactTag,
    CRMNote,
    CRMOpportunity,
    CRMOpportunityContact,
    CRMSavedSearch,
    CRMSmartPlan,
    CRMSmartPlanEnrollment,
    CRMTag,
    CRMTask,
)
from models.command_contacts import (
    CRMContactAddress,
    CRMContactCapturePosition,
    CRMContactMethod,
    CRMContactOwnership,
    CRMContactProfile,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
    CRMContactTimelineEvent,
)
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from models.lead import Lead
from services.command_contact_contracts import (
    CONTACT_TOUCH_ACTIVITY_KINDS,
    ContactCelebrations,
    ContactDirectoryFilters,
    ContactOriginFilter,
    ContactSmartView,
    ContactSortKey,
    ContactSourceFilter,
    ContactWorkspaceCounts,
    ContactWorkspaceSummary,
    SortDirection,
)
from services.command_contacts import (
    ContactDataIntegrityError,
    ContactDirectoryError,
    ContactLinkConflict,
    ContactNotFound,
    ContactNotInDirectory,
    ContactSectionUnsupported,
    get_contact_detail,
    get_contact_neighbors,
    get_contact_workspace_summary,
    list_contact_celebrations,
    list_contacts,
    list_contacts_cursor,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
EMPTY_WORKSPACE_COUNTS = ContactWorkspaceCounts(
    active_tasks=0, completed_tasks=0, cancelled_tasks=0, archived_tasks=0,
    active_smart_plans=0, opportunities=0, notes=0, saved_searches=0, bookings=0,
)


@pytest.mark.asyncio
async def test_cursor_directory_uses_stable_id_snapshot_across_insert_and_reorder(
    service_db: AsyncSession,
) -> None:
    contacts = [
        CRMContact(
            first_name=name,
            last_name="Cursor",
            email=f"{name.casefold()}@example.com",
            phone=None,
            stage="lead",
        )
        for name in ("Zulu", "Yankee", "Xray", "Whiskey")
    ]
    service_db.add_all(contacts)
    await service_db.flush()

    first = await list_contacts_cursor(
        service_db,
        ContactDirectoryFilters(page_size=2),
        after_id=None,
        upper_bound_id=None,
        now=NOW,
    )
    original_ids = [contact.id for contact in contacts]
    assert [row.id for row in first.rows] == original_ids[:2]
    assert first.next_after_id == original_ids[1]
    assert first.upper_bound_id == original_ids[-1]

    contacts[0].first_name = "Alpha"
    inserted = CRMContact(
        first_name="New",
        last_name="Cursor",
        email="new.cursor@example.com",
        phone=None,
        stage="lead",
    )
    service_db.add(inserted)
    await service_db.flush()

    second = await list_contacts_cursor(
        service_db,
        ContactDirectoryFilters(page_size=2),
        after_id=first.next_after_id,
        upper_bound_id=first.upper_bound_id,
        now=NOW,
    )

    assert [row.id for row in second.rows] == original_ids[2:]
    assert inserted.id not in {row.id for row in second.rows}
    assert second.has_more is False


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


async def _add_contact_occurrence(
    db: AsyncSession,
    contact: CRMContact,
    index: int,
    *,
    section_name: str,
    record_kind: str,
    values: dict[str, object],
    linked_entity: tuple[str, int] | None = None,
) -> CRMContactSourceOccurrence:
    position_source = _source_record(index * 10)
    position_source.record_kind = "contact_capture_position"
    position_source.source_key = f"synthetic:summary:position:{index}"
    section_source = _source_record(index * 10 + 1)
    section_source.record_kind = "contact_section_capture"
    section_source.source_key = (
        f"synthetic:summary:position:{index}:section:{section_name}"
    )
    child_source = _source_record(index * 10 + 2)
    child_source.record_kind = record_kind
    child_source.evidence_level = "rendered_occurrence"
    child_source.source_key = f"synthetic:summary:child:{index}"
    child_source.payload_json = json.dumps(
        {
            "capture_ordinal": f"{index:07d}",
            "source_contact_id": f"{index:024x}",
            "section_name": section_name,
            "occurrence_ordinal": 1,
            "values": values,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    db.add_all([position_source, section_source, child_source])
    await db.flush()
    position = CRMContactCapturePosition(
        contact_id=contact.id,
        source_record_id=position_source.id,
        bundle_fingerprint=f"{index:064x}",
        capture_ordinal=index,
        source_contact_id=f"{index:024x}",
        captured_at=NOW,
        capture_quality="complete",
        limitations_json="[]",
    )
    db.add(position)
    await db.flush()
    section = CRMContactSectionCapture(
        capture_position_id=position.id,
        source_record_id=section_source.id,
        section_name=section_name,
        captured_at=NOW,
        capture_quality="complete",
        is_empty=False,
        row_count=1,
        limitations_json="[]",
    )
    db.add(section)
    await db.flush()
    occurrence = CRMContactSourceOccurrence(
        contact_id=contact.id,
        section_capture_id=section.id,
        source_record_id=child_source.id,
        occurrence_ordinal=1,
    )
    db.add(occurrence)
    await db.flush()
    if linked_entity is not None:
        db.add(
            CRMEntitySource(
                entity_type=linked_entity[0],
                entity_id=linked_entity[1],
                source_record_id=child_source.id,
            )
        )
        await db.flush()
    return occurrence


@pytest.mark.asyncio
async def test_contact_detail_hydrates_profile_addresses_actors_and_tags(
    service_db: AsyncSession,
):
    contact = CRMContact(
        first_name="Synthetic",
        last_name="Detail",
        email="detail@example.test",
        phone="+15550120000",
        stage="lead",
        birthday=date(1988, 8, 13),
    )
    service_db.add(contact)
    await service_db.flush()
    profile_source = _source_record(80_001)
    service_db.add(profile_source)
    await service_db.flush()
    service_db.add_all(
        [
            CRMEntitySource(
                entity_type="contact",
                entity_id=contact.id,
                source_record_id=profile_source.id,
            ),
            CRMContactProfile(
                contact_id=contact.id,
                legal_name="Synthetic Legal",
                preferred_name="Synthetic Preferred",
                description="Synthetic description",
                company="Synthetic Company",
                title="Synthetic Title",
                lead_source="Synthetic Source",
                account_name="Synthetic Account",
                health_score=72,
                birth_year_quality="unknown",
                anniversary_month=4,
                anniversary_day=5,
                anniversary_year_quality="yearless",
            ),
            CRMContactAddress(
                contact_id=contact.id,
                source_record_id=profile_source.id,
                source_key="synthetic:address:secondary",
                address_type="work",
                formatted="2 Synthetic Street",
                latitude=Decimal("40.1000000"),
                longitude=Decimal("-73.2000000"),
                is_primary=False,
            ),
            CRMContactAddress(
                contact_id=contact.id,
                source_key="synthetic:address:primary",
                address_type="home",
                formatted="1 Synthetic Street",
                is_primary=True,
            ),
            CRMContactOwnership(
                contact_id=contact.id,
                source_key="synthetic:owner",
                role="owner",
                provider_actor_id="synthetic-owner",
                display_name="Synthetic Owner",
                is_primary=True,
            ),
            CRMContactOwnership(
                contact_id=contact.id,
                source_key="synthetic:collaborator",
                role="collaborator",
                provider_actor_id=None,
                display_name="Synthetic Collaborator",
                is_primary=False,
            ),
            CRMTag(name="Synthetic A"),
            CRMTag(name="Synthetic B"),
        ]
    )
    await service_db.flush()
    tags = (await service_db.scalars(select(CRMTag).order_by(CRMTag.name))).all()
    service_db.add_all(
        CRMContactTag(contact_id=contact.id, tag_id=tag.id) for tag in reversed(tags)
    )
    await service_db.flush()

    detail = await get_contact_detail(service_db, contact.id)

    assert detail.contact.id == contact.id
    assert detail.contact.primary_email == "detail@example.test"
    assert detail.contact.health_score == 72
    assert detail.contact.birthday is not None
    assert detail.contact.birthday.origin == "internal_crm"
    assert detail.lead_id is None
    assert detail.recovered_profile is not None
    assert detail.recovered_profile.legal_name == "Synthetic Legal"
    assert detail.recovered_profile.anniversary is not None
    assert detail.recovered_profile.anniversary.year_quality == "yearless"
    assert tuple(address.formatted for address in detail.addresses) == (
        "1 Synthetic Street",
        "2 Synthetic Street",
    )
    assert detail.addresses[1].source_record_id == profile_source.id
    assert tuple(actor.role for actor in detail.ownership) == (
        "owner",
        "collaborator",
    )
    assert tuple(tag.name for tag in detail.tags) == (
        "Synthetic A",
        "Synthetic B",
    )


@pytest.mark.asyncio
async def test_contact_detail_missing_and_query_count_are_bounded(
    service_db: AsyncSession,
):
    with pytest.raises(ContactNotFound, match="contact does not exist"):
        await get_contact_detail(service_db, 999_999)

    contact = CRMContact(first_name="Bounded", last_name="Detail", stage="lead")
    service_db.add(contact)
    await service_db.flush()
    pending = CRMContact(first_name="Pending", last_name="Caller", stage="lead")
    service_db.add(pending)
    selects = 0
    flushes = 0

    def capture(_connection, _cursor, statement, _params, _context, _many):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    def before_flush(_session, _flush_context, _instances):
        nonlocal flushes
        flushes += 1

    assert service_db.bind is not None
    event.listen(service_db.bind.sync_engine, "before_cursor_execute", capture)
    event.listen(service_db.sync_session, "before_flush", before_flush)
    try:
        await get_contact_detail(service_db, contact.id)
    finally:
        event.remove(service_db.bind.sync_engine, "before_cursor_execute", capture)
        event.remove(service_db.sync_session, "before_flush", before_flush)
    assert selects <= 8
    assert flushes == 0
    assert pending in service_db.new
    assert pending.id is None


@pytest.mark.asyncio
async def test_contact_detail_rejects_profile_link_mismatches_and_bad_domains(
    service_db: AsyncSession,
):
    profile_only = CRMContact(
        first_name="Profile",
        last_name="Only",
        stage="lead",
    )
    link_only = CRMContact(first_name="Link", last_name="Only", stage="lead")
    wrong_domain = CRMContact(
        first_name="Wrong",
        last_name="Domain",
        stage="lead",
    )
    wrong_domain_without_profile = CRMContact(
        first_name="Wrong",
        last_name="Domain Without Profile",
        stage="lead",
    )
    ambiguous = CRMContact(
        first_name="Ambiguous",
        last_name="Links",
        stage="lead",
    )
    cross_profile = CRMContact(
        first_name="Cross",
        last_name="Profile",
        stage="lead",
    )
    cross_link = CRMContact(
        first_name="Cross",
        last_name="Link",
        stage="lead",
    )
    conflicting = CRMContact(
        first_name="Conflicting",
        last_name="Targets",
        stage="lead",
    )
    service_db.add_all(
        [
            profile_only,
            link_only,
            wrong_domain,
            wrong_domain_without_profile,
            ambiguous,
            cross_profile,
            cross_link,
            conflicting,
        ]
    )
    await service_db.flush()
    service_db.add_all(
        CRMContactProfile(contact_id=contact.id)
        for contact in (
            profile_only,
            wrong_domain,
            ambiguous,
            cross_profile,
            conflicting,
        )
    )
    valid_link_only = _source_record(80_101)
    invalid_domain = _source_record(80_102)
    invalid_domain.source_system = "synthetic_other_system"
    invalid_domain_without_profile = _source_record(80_107)
    invalid_domain_without_profile.module = "synthetic_other_module"
    ambiguous_one = _source_record(80_103)
    ambiguous_two = _source_record(80_104)
    cross_source = _source_record(80_105)
    conflicting_source = _source_record(80_106)
    service_db.add_all(
        [
            valid_link_only,
            invalid_domain,
            invalid_domain_without_profile,
            ambiguous_one,
            ambiguous_two,
            cross_source,
            conflicting_source,
        ]
    )
    await service_db.flush()
    service_db.add_all(
        [
            CRMEntitySource(
                entity_type="contact",
                entity_id=link_only.id,
                source_record_id=valid_link_only.id,
            ),
            CRMEntitySource(
                entity_type="contact",
                entity_id=wrong_domain.id,
                source_record_id=invalid_domain.id,
            ),
            CRMEntitySource(
                entity_type="contact",
                entity_id=wrong_domain_without_profile.id,
                source_record_id=invalid_domain_without_profile.id,
            ),
            CRMEntitySource(
                entity_type="contact",
                entity_id=ambiguous.id,
                source_record_id=ambiguous_one.id,
            ),
            CRMEntitySource(
                entity_type="contact",
                entity_id=ambiguous.id,
                source_record_id=ambiguous_two.id,
            ),
            CRMEntitySource(
                entity_type="contact",
                entity_id=cross_link.id,
                source_record_id=cross_source.id,
            ),
            CRMEntitySource(
                entity_type="contact",
                entity_id=conflicting.id,
                source_record_id=conflicting_source.id,
            ),
            CRMEntitySource(
                entity_type="note",
                entity_id=999_999,
                source_record_id=conflicting_source.id,
            ),
        ]
    )
    await service_db.flush()

    for contact in (
        profile_only,
        link_only,
        wrong_domain,
        wrong_domain_without_profile,
        cross_profile,
        cross_link,
        conflicting,
    ):
        with pytest.raises(
            ContactDataIntegrityError,
            match="recovered profile ownership is invalid",
        ) as error:
            await get_contact_detail(service_db, contact.id)
        assert contact.first_name not in str(error.value)

    assert (await get_contact_detail(service_db, ambiguous.id)).contact.sources == (
        "kw_command",
    )


@pytest.mark.asyncio
async def test_contact_detail_profile_link_validation_is_bounded(
    service_db: AsyncSession,
):
    contact = CRMContact(
        first_name="Bounded",
        last_name="Profile Links",
        stage="lead",
    )
    service_db.add(contact)
    await service_db.flush()
    service_db.add(CRMContactProfile(contact_id=contact.id))
    sources = [_source_record(80_200 + index) for index in range(100)]
    service_db.add_all(sources)
    await service_db.flush()
    service_db.add_all(
        CRMEntitySource(
            entity_type="contact",
            entity_id=contact.id,
            source_record_id=source.id,
        )
        for source in sources
    )
    await service_db.flush()
    selects = 0

    def capture(_connection, _cursor, statement, _params, _context, _many):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    assert service_db.bind is not None
    event.listen(service_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        assert (
            await get_contact_detail(service_db, contact.id)
        ).contact.id == contact.id
    finally:
        event.remove(service_db.bind.sync_engine, "before_cursor_execute", capture)
    assert selects <= 8


@pytest.mark.asyncio
async def test_workspace_summary_counts_internal_and_source_only_union_once(
    service_db: AsyncSession,
):
    contact = CRMContact(
        first_name="Synthetic",
        last_name="Workspace",
        email="workspace@example.test",
        stage="lead",
    )
    service_db.add(contact)
    await service_db.flush()
    tasks = [
        CRMTask(contact_id=contact.id, title="Open", status="open"),
        CRMTask(contact_id=contact.id, title="In progress", status="in_progress"),
        CRMTask(contact_id=contact.id, title="Completed", status="completed"),
        CRMTask(contact_id=contact.id, title="Cancelled", status="cancelled"),
        CRMTask(
            contact_id=contact.id,
            title="Archived open",
            status="open",
            archived_at=NOW,
        ),
        CRMTask(
            contact_id=contact.id,
            title="Archived completed",
            status="completed",
            archived_at=NOW,
        ),
    ]
    plans = [
        CRMSmartPlan(name="Active Plan", status="active"),
        CRMSmartPlan(name="Paused Plan", status="active"),
    ]
    opportunity = CRMOpportunity(name="Synthetic Opportunity")
    note = CRMNote(contact_id=contact.id, body="Internal note")
    search = CRMSavedSearch(contact_id=contact.id, name="Internal search")
    service_db.add_all([*tasks, *plans, opportunity, note, search])
    await service_db.flush()
    active_enrollment = CRMSmartPlanEnrollment(
        id=91_001,
        smart_plan_id=plans[0].id,
        contact_id=contact.id,
        status=" ACTIVE ",
    )
    paused_enrollment = CRMSmartPlanEnrollment(
        id=91_002,
        smart_plan_id=plans[1].id,
        contact_id=contact.id,
        status="paused",
    )
    service_db.add_all(
        [
            active_enrollment,
            paused_enrollment,
            CRMOpportunityContact(
                opportunity_id=opportunity.id,
                contact_id=contact.id,
                role="client",
            ),
        ]
    )
    await service_db.flush()
    occurrence_specs: tuple[tuple[int, str, str, dict[str, object]], ...] = (
        (81_001, "tasks_to_do", "contact_task", {"title": "Recovered open"}),
        (
            81_002,
            "tasks_completed",
            "contact_task",
            {"title": "Recovered complete"},
        ),
        (
            81_003,
            "tasks_archived",
            "contact_task",
            {"title": "Recovered archive"},
        ),
        (
            81_004,
            "smart_plans",
            "contact_smart_plan",
            {"title": "Recovered active", "status": " ACTIVE "},
        ),
        (
            81_005,
            "smart_plans",
            "contact_smart_plan",
            {"title": "Recovered inactive", "status": None},
        ),
        (
            81_006,
            "opportunities",
            "contact_opportunity",
            {"title": "Recovered opportunity"},
        ),
        (
            81_007,
            "notes",
            "contact_note",
            {"body": "Recovered note"},
        ),
        (
            81_008,
            "saved_searches",
            "contact_saved_search",
            {"name": "Recovered search"},
        ),
    )
    for index, section, record_kind, values in occurrence_specs:
        await _add_contact_occurrence(
            service_db,
            contact,
            index,
            section_name=section,
            record_kind=record_kind,
            values=values,
        )
    await _add_contact_occurrence(
        service_db,
        contact,
        81_009,
        section_name="notes",
        record_kind="contact_note",
        values={"body": "Internal note"},
        linked_entity=("note", note.id),
    )
    materialized: tuple[
        tuple[int, str, str, dict[str, object], tuple[str, int]], ...
    ] = (
        (
            81_010,
            "tasks_to_do",
            "contact_task",
            {"title": "Open"},
            ("task", tasks[0].id),
        ),
        (
            81_011,
            "smart_plans",
            "contact_smart_plan",
            {"title": "Active Plan", "status": "active"},
            ("smart_plan", active_enrollment.id),
        ),
        (
            81_012,
            "opportunities",
            "contact_opportunity",
            {"title": "Synthetic Opportunity"},
            ("opportunity", opportunity.id),
        ),
        (
            81_013,
            "saved_searches",
            "contact_saved_search",
            {"name": "Internal search"},
            ("saved_search", search.id),
        ),
        (
            81_014,
            "tasks_archived",
            "contact_task",
            {"title": "Archived open"},
            ("task", tasks[4].id),
        ),
    )
    for index, section, record_kind, values, link in materialized:
        await _add_contact_occurrence(
            service_db,
            contact,
            index,
            section_name=section,
            record_kind=record_kind,
            values=values,
            linked_entity=link,
        )
    for offset in range(16):
        await _add_contact_occurrence(
            service_db,
            contact,
            81_100 + offset,
            section_name="notes",
            record_kind="contact_note",
            values={"body": f"Recovered note {offset}"},
        )
    service_db.add(
        Booking(
            name="Workspace booking",
            email="WORKSPACE@example.test",
            meeting_type="phone",
            scheduled_at=NOW,
        )
    )
    await service_db.flush()

    selects = 0

    def capture(_connection, _cursor, statement, _params, _context, _many):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    assert service_db.bind is not None
    event.listen(service_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        summary = await get_contact_workspace_summary(service_db, contact.id)
    finally:
        event.remove(service_db.bind.sync_engine, "before_cursor_execute", capture)

    assert summary == ContactWorkspaceSummary(
        open_tasks=3,
        active_tasks=3,
        completed_tasks=2,
        cancelled_tasks=1,
        archived_tasks=3,
        archived_mutable_tasks=2,
        archived_recovered_evidence=1,
        active_smart_plans=2,
        opportunities=2,
        notes=18,
        saved_searches=2,
        bookings=1,
        internal_counts=ContactWorkspaceCounts(
            active_tasks=2, completed_tasks=1, cancelled_tasks=1, archived_tasks=2,
            active_smart_plans=1, opportunities=1, notes=1, saved_searches=1, bookings=1,
        ),
        recovered_counts=ContactWorkspaceCounts(
            active_tasks=1, completed_tasks=1, cancelled_tasks=0, archived_tasks=1,
            active_smart_plans=1, opportunities=1, notes=17, saved_searches=1, bookings=0,
        ),
    )
    assert selects <= 14


@pytest.mark.asyncio
async def test_workspace_summary_smart_plan_link_targets_enrollment_id(
    service_db: AsyncSession,
):
    contact = CRMContact(first_name="Plan", last_name="Owner", stage="lead")
    plan = CRMSmartPlan(name="Synthetic linked plan", status="active")
    service_db.add_all([contact, plan])
    await service_db.flush()
    enrollment = CRMSmartPlanEnrollment(
        id=92_001,
        smart_plan_id=plan.id,
        contact_id=contact.id,
        status="active",
    )
    service_db.add(enrollment)
    await service_db.flush()
    await _add_contact_occurrence(
        service_db,
        contact,
        81_501,
        section_name="smart_plans",
        record_kind="contact_smart_plan",
        values={"title": "Synthetic linked plan", "status": "active"},
        linked_entity=("smart_plan", enrollment.id),
    )

    summary = await get_contact_workspace_summary(service_db, contact.id)
    assert summary.active_smart_plans == 1


@pytest.mark.asyncio
async def test_workspace_summary_strips_internal_and_source_plan_statuses(
    service_db: AsyncSession,
):
    contact = CRMContact(first_name="Trimmed", last_name="Plans", stage="lead")
    plan = CRMSmartPlan(name="Synthetic spaced plan", status="active")
    service_db.add_all([contact, plan])
    await service_db.flush()
    service_db.add(
        CRMSmartPlanEnrollment(
            id=92_101,
            smart_plan_id=plan.id,
            contact_id=contact.id,
            status=" ACTIVE ",
        )
    )
    await service_db.flush()
    await _add_contact_occurrence(
        service_db,
        contact,
        81_502,
        section_name="smart_plans",
        record_kind="contact_smart_plan",
        values={"title": "Recovered spaced plan", "status": " ACTIVE "},
    )

    summary = await get_contact_workspace_summary(service_db, contact.id)
    assert summary.active_smart_plans == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("section_name", "record_kind", "payload"),
    (
        ("notes", "contact_note", {}),
        ("saved_searches", "contact_saved_search", {"values": []}),
        ("tasks_to_do", "contact_task", {"values": None}),
        ("opportunities", "contact_opportunity", {"values": "scalar"}),
        (
            "smart_plans",
            "contact_smart_plan",
            {"values": {"status": "x" * 121}},
        ),
    ),
)
async def test_workspace_summary_rejects_invalid_source_only_payload_values(
    service_db: AsyncSession,
    section_name: str,
    record_kind: str,
    payload: dict[str, object],
):
    contact = CRMContact(
        first_name="Invalid",
        last_name="Source Payload",
        stage="lead",
    )
    service_db.add(contact)
    await service_db.flush()
    occurrence = await _add_contact_occurrence(
        service_db,
        contact,
        81_600,
        section_name=section_name,
        record_kind=record_kind,
        values={"title": "Synthetic placeholder"},
    )
    source = await service_db.get(CRMSourceRecord, occurrence.source_record_id)
    assert source is not None
    source.payload_json = json.dumps(payload)
    await service_db.flush()

    with pytest.raises(
        ContactDataIntegrityError,
        match="contact occurrence payload is invalid",
    ):
        await get_contact_workspace_summary(service_db, contact.id)


@pytest.mark.asyncio
async def test_workspace_summary_fails_closed_on_unknown_state_and_bad_link(
    service_db: AsyncSession,
):
    contact = CRMContact(first_name="Integrity", last_name="Owner", stage="lead")
    other = CRMContact(first_name="Wrong", last_name="Owner", stage="lead")
    service_db.add_all([contact, other])
    await service_db.flush()
    invalid = CRMTask(
        contact_id=contact.id,
        title="Unknown",
        status="private-invalid-status",
    )
    wrong = CRMNote(contact_id=other.id, body="Wrong owner")
    service_db.add_all([invalid, wrong])
    await service_db.flush()

    with pytest.raises(ContactDataIntegrityError, match="contact task status"):
        await get_contact_workspace_summary(service_db, contact.id)

    invalid.status = "open"
    await service_db.flush()
    await _add_contact_occurrence(
        service_db,
        contact,
        82_001,
        section_name="notes",
        record_kind="contact_note",
        values={"body": "Wrong owner"},
        linked_entity=("note", wrong.id),
    )
    with pytest.raises(ContactDataIntegrityError, match="source link"):
        await get_contact_workspace_summary(service_db, contact.id)


@pytest.mark.asyncio
async def test_workspace_summary_missing_contact_is_safe(
    service_db: AsyncSession,
):
    with pytest.raises(ContactNotFound, match="contact does not exist"):
        await get_contact_workspace_summary(service_db, 999_999)


@pytest.mark.asyncio
async def test_workspace_summary_ignores_valid_timeline_source_links(
    service_db: AsyncSession,
):
    contact = CRMContact(
        first_name="Timeline",
        last_name="Isolated",
        stage="lead",
    )
    source = _source_record(82_501)
    source.record_kind = "contact_timeline_event"
    source.evidence_level = "rendered_occurrence"
    service_db.add_all([contact, source])
    await service_db.flush()
    timeline_event = CRMContactTimelineEvent(
        contact_id=contact.id,
        source_record_id=source.id,
        source_system="kw_command",
        source_event_key="synthetic-timeline-isolation",
        kind="note",
        title="Synthetic timeline event",
        occurred_at=NOW,
    )
    service_db.add(timeline_event)
    await service_db.flush()
    service_db.add(
        CRMEntitySource(
            entity_type="contact_timeline_event",
            entity_id=timeline_event.id,
            source_record_id=source.id,
        )
    )
    await service_db.flush()

    assert await get_contact_workspace_summary(
        service_db, contact.id
    ) == ContactWorkspaceSummary(
        open_tasks=0,
        active_tasks=0,
        completed_tasks=0,
        cancelled_tasks=0,
        archived_tasks=0,
        archived_mutable_tasks=0,
        archived_recovered_evidence=0,
        active_smart_plans=0,
        opportunities=0,
        notes=0,
        saved_searches=0,
        bookings=0,
        internal_counts=EMPTY_WORKSPACE_COUNTS,
        recovered_counts=EMPTY_WORKSPACE_COUNTS,
    )


@pytest.mark.asyncio
async def test_workspace_summary_rejects_dangling_and_wrong_domain_links(
    service_db: AsyncSession,
):
    contact = CRMContact(first_name="Dangling", last_name="Link", stage="lead")
    service_db.add(contact)
    await service_db.flush()
    occurrence = await _add_contact_occurrence(
        service_db,
        contact,
        83_001,
        section_name="tasks_to_do",
        record_kind="contact_task",
        values={"title": "Dangling task"},
        linked_entity=("task", 999_999),
    )
    with pytest.raises(ContactDataIntegrityError, match="source link"):
        await get_contact_workspace_summary(service_db, contact.id)

    link = await service_db.scalar(
        select(CRMEntitySource).where(
            CRMEntitySource.source_record_id == occurrence.source_record_id
        )
    )
    assert link is not None
    link.entity_type = "note"
    await service_db.flush()
    with pytest.raises(ContactDataIntegrityError, match="source link"):
        await get_contact_workspace_summary(service_db, contact.id)


@pytest.mark.asyncio
async def test_workspace_summary_rejects_reverse_cross_contact_source_link(
    service_db: AsyncSession,
):
    requested = CRMContact(first_name="Requested", last_name="Owner", stage="lead")
    wrong = CRMContact(first_name="Wrong", last_name="Occurrence", stage="lead")
    service_db.add_all([requested, wrong])
    await service_db.flush()
    task = CRMTask(contact_id=requested.id, title="Requested task", status="open")
    service_db.add(task)
    await service_db.flush()
    await _add_contact_occurrence(
        service_db,
        wrong,
        83_101,
        section_name="tasks_to_do",
        record_kind="contact_task",
        values={"title": "Wrong occurrence owner"},
        linked_entity=("task", task.id),
    )

    with pytest.raises(ContactDataIntegrityError, match="ownership"):
        await get_contact_workspace_summary(service_db, requested.id)


@pytest.mark.asyncio
async def test_workspace_summary_rejects_internal_link_without_occurrence(
    service_db: AsyncSession,
):
    contact = CRMContact(first_name="Missing", last_name="Occurrence", stage="lead")
    service_db.add(contact)
    await service_db.flush()
    task = CRMTask(contact_id=contact.id, title="Linked task", status="open")
    source = _source_record(83_201)
    source.record_kind = "contact_task"
    source.evidence_level = "rendered_occurrence"
    service_db.add_all([task, source])
    await service_db.flush()
    service_db.add(
        CRMEntitySource(
            entity_type="task",
            entity_id=task.id,
            source_record_id=source.id,
        )
    )
    await service_db.flush()

    with pytest.raises(ContactDataIntegrityError, match="ownership"):
        await get_contact_workspace_summary(service_db, contact.id)


@pytest.mark.asyncio
async def test_workspace_summary_empty_lead_booking_and_query_work_are_bounded(
    service_db: AsyncSession,
):
    lead = Lead(id=91_001, name="Synthetic workspace lead")
    service_db.add(lead)
    await service_db.flush()
    contact = CRMContact(
        first_name="Lead",
        last_name="Workspace",
        lead_id=lead.id,
        stage="lead",
    )
    service_db.add(contact)
    await service_db.flush()
    service_db.add_all(
        Booking(
            lead_id=lead.id,
            name=f"Synthetic booking {index}",
            email=f"booking-{index}@example.test",
            meeting_type="phone",
            scheduled_at=NOW,
        )
        for index in range(2)
    )
    await service_db.flush()
    pending = CRMContact(first_name="Pending", last_name="Summary", stage="lead")
    service_db.add(pending)
    selects = 0
    flushes = 0

    def capture(_connection, _cursor, statement, _params, _context, _many):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    def before_flush(_session, _flush_context, _instances):
        nonlocal flushes
        flushes += 1

    assert service_db.bind is not None
    event.listen(service_db.bind.sync_engine, "before_cursor_execute", capture)
    event.listen(service_db.sync_session, "before_flush", before_flush)
    try:
        summary = await get_contact_workspace_summary(service_db, contact.id)
    finally:
        event.remove(service_db.bind.sync_engine, "before_cursor_execute", capture)
        event.remove(service_db.sync_session, "before_flush", before_flush)

    assert summary == ContactWorkspaceSummary(
        open_tasks=0,
        active_tasks=0,
        completed_tasks=0,
        cancelled_tasks=0,
        archived_tasks=0,
        archived_mutable_tasks=0,
        archived_recovered_evidence=0,
        active_smart_plans=0,
        opportunities=0,
        notes=0,
        saved_searches=0,
        bookings=2,
        internal_counts=replace(EMPTY_WORKSPACE_COUNTS, bookings=2),
        recovered_counts=EMPTY_WORKSPACE_COUNTS,
    )
    assert selects <= 15
    assert flushes == 0
    assert pending in service_db.new
    assert pending.id is None


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
    assert (
        await total(
            sources=(ContactSourceFilter.KW_COMMAND, ContactSourceFilter.LEGACY_LEAD)
        )
        == 366
    )
    assert (
        await total(
            sources=(ContactSourceFilter.KW_COMMAND,),
            origins=(ContactOriginFilter.LEAD_BACKED,),
        )
        == 2
    )

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
                    provider_actor_id=("assignee-2" if index == 3 else "assignee-1"),
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
        row.id: row.birthday for row in all_rows.rows if row.birthday is not None
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
    await _add_timeline_capture(service_db, contacts[3], 4, is_empty=False, row_count=1)
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
    _position, missing_cell = await _add_timeline_capture(service_db, contacts[1], 20)
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
        (
            ContactSortKey.LAST_CONTACTED_AT,
            SortDirection.ASC,
            ("Able", "Baker", "Charlie"),
        ),
        (
            ContactSortKey.LAST_CONTACTED_AT,
            SortDirection.DESC,
            ("Baker", "Able", "Charlie"),
        ),
        (
            ContactSortKey.LAST_INTERACTION_AT,
            SortDirection.ASC,
            ("Baker", "Able", "Charlie"),
        ),
        (
            ContactSortKey.LAST_INTERACTION_AT,
            SortDirection.DESC,
            ("Able", "Baker", "Charlie"),
        ),
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
    neighbors = await get_contact_neighbors(service_db, middle_id, filters, now=NOW)
    assert neighbors.previous_contact_id == all_rows.rows[0].id
    assert neighbors.next_contact_id == all_rows.rows[2].id


@pytest.mark.asyncio
async def test_sort_ties_and_neighbor_ids_follow_requested_direction(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(first_name="Same", last_name="Name", stage="lead") for _ in range(3)
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
async def test_contact_celebrations_merge_precedence_dual_kind_and_order_read_only(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(first_name=first, last_name=last, stage="lead")
        for first, last in (
            ("Zulu", "Same"),
            ("alpha", "same"),
            ("Alpha", "Same"),
            ("Dual", "Kind"),
            ("Internal", "Wins"),
            ("Other Month", "Internal"),
            ("Nineteen", "Hundred"),
            ("Anniversary", "Verified"),
            ("Anniversary", "Yearless"),
            ("Anniversary", "Sentinel"),
        )
    ]
    contacts[3].birthday = date(1985, 8, 20)
    contacts[3].anniversary = date(2015, 8, 22)
    contacts[4].birthday = date(1990, 8, 21)
    contacts[5].birthday = date(1980, 7, 4)
    contacts[6].birthday = date(1900, 8, 23)
    service_db.add_all(contacts)
    await service_db.flush()
    service_db.add_all(
        [
            CRMContactProfile(
                contact_id=contacts[0].id,
                birth_month=8,
                birth_day=19,
                birth_year=None,
                birth_year_quality="sentinel",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[1].id,
                birth_month=8,
                birth_day=19,
                birth_year=None,
                birth_year_quality="yearless",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[2].id,
                birth_month=8,
                birth_day=19,
                birth_year=2000,
                birth_year_quality="verified",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[3].id,
                birth_month=8,
                birth_day=1,
                birth_year=None,
                birth_year_quality="yearless",
                anniversary_month=8,
                anniversary_day=1,
                anniversary_year=None,
                anniversary_year_quality="sentinel",
            ),
            CRMContactProfile(
                contact_id=contacts[4].id,
                birth_month=8,
                birth_day=1,
                birth_year=None,
                birth_year_quality="sentinel",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[5].id,
                birth_month=8,
                birth_day=24,
                birth_year=None,
                birth_year_quality="yearless",
                anniversary_month=8,
                anniversary_day=17,
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[6].id,
                birth_month=8,
                birth_day=1,
                birth_year=None,
                birth_year_quality="sentinel",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[7].id,
                birth_year_quality="unknown",
                anniversary_month=8,
                anniversary_day=18,
                anniversary_year=2018,
                anniversary_year_quality="verified",
            ),
            CRMContactProfile(
                contact_id=contacts[8].id,
                birth_year_quality="unknown",
                anniversary_month=8,
                anniversary_day=18,
                anniversary_year=None,
                anniversary_year_quality="yearless",
            ),
            CRMContactProfile(
                contact_id=contacts[9].id,
                birth_year_quality="unknown",
                anniversary_month=8,
                anniversary_day=19,
                anniversary_year=None,
                anniversary_year_quality="sentinel",
            ),
        ]
    )
    await service_db.flush()
    before_dates = tuple((row.birthday, row.anniversary) for row in contacts)
    before_identity = set(service_db.identity_map)
    selects: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        selects.append(statement.lstrip().split(None, 1)[0].upper())

    assert service_db.bind is not None
    event.listen(service_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        result = await list_contact_celebrations(service_db, month=8)
    finally:
        event.remove(service_db.bind.sync_engine, "before_cursor_execute", capture)

    assert tuple(
        (row.day, row.display_name, row.contact_id) for row in result.birthdays
    ) == (
        (19, "alpha same", contacts[1].id),
        (19, "Alpha Same", contacts[2].id),
        (19, "Zulu Same", contacts[0].id),
        (20, "Dual Kind", contacts[3].id),
        (21, "Internal Wins", contacts[4].id),
        (23, "Nineteen Hundred", contacts[6].id),
    )
    by_id = {row.contact_id: row for row in result.birthdays}
    assert (by_id[contacts[0].id].year, by_id[contacts[0].id].year_quality) == (
        None,
        "sentinel",
    )
    assert (by_id[contacts[1].id].year, by_id[contacts[1].id].year_quality) == (
        None,
        "yearless",
    )
    assert (by_id[contacts[2].id].year, by_id[contacts[2].id].year_quality) == (
        2000,
        "verified",
    )
    assert by_id[contacts[3].id].origin == "internal_crm"
    assert by_id[contacts[3].id].year == 1985
    assert by_id[contacts[4].id].origin == "internal_crm"
    assert contacts[5].id not in by_id
    assert by_id[contacts[6].id].origin == "internal_crm"
    assert by_id[contacts[6].id].year == 1900
    assert by_id[contacts[6].id].year_quality == "verified"
    assert tuple(row.contact_id for row in result.anniversaries) == (
        contacts[7].id,
        contacts[8].id,
        contacts[9].id,
        contacts[3].id,
    )
    anniversary_by_id = {row.contact_id: row for row in result.anniversaries}
    assert anniversary_by_id[contacts[7].id].year == 2018
    assert anniversary_by_id[contacts[7].id].year_quality == "verified"
    assert anniversary_by_id[contacts[8].id].year is None
    assert anniversary_by_id[contacts[8].id].year_quality == "yearless"
    assert anniversary_by_id[contacts[9].id].year is None
    assert anniversary_by_id[contacts[9].id].year_quality == "sentinel"
    assert contacts[5].id not in anniversary_by_id
    assert result.anniversaries[0].kind == "anniversary"
    assert anniversary_by_id[contacts[3].id].year == 2015
    assert all(row.kind == "birthday" for row in result.birthdays)
    assert selects == ["SELECT"]
    assert tuple((row.birthday, row.anniversary) for row in contacts) == before_dates
    assert set(service_db.identity_map) == before_identity
    assert not service_db.new
    assert not service_db.dirty
    assert not service_db.deleted


@pytest.mark.asyncio
async def test_contact_celebrations_never_autoflushes_unrelated_pending_state(
    service_db: AsyncSession,
):
    stored = CRMContact(
        first_name="Stored",
        last_name="Celebration",
        stage="lead",
        birthday=date(2000, 8, 8),
    )
    service_db.add(stored)
    await service_db.flush()
    pending = CRMContact(first_name="Pending", last_name="Caller", stage="lead")
    service_db.add(pending)
    flushes: list[bool] = []

    def before_flush(_session, _flush_context, _instances):
        flushes.append(True)

    event.listen(service_db.sync_session, "before_flush", before_flush)
    try:
        result = await list_contact_celebrations(service_db, month=8)
    finally:
        event.remove(service_db.sync_session, "before_flush", before_flush)

    assert tuple(row.contact_id for row in result.birthdays) == (stored.id,)
    assert flushes == []
    assert pending in service_db.new
    assert pending.id is None


@pytest.mark.asyncio
async def test_contact_celebrations_uses_one_select_for_366_rows(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(
            first_name=f"Synthetic {index:03d}",
            last_name="Scale",
            stage="lead",
            birthday=date(2000, 8, (index % 28) + 1),
        )
        for index in range(366)
    ]
    service_db.add_all(contacts)
    await service_db.flush()
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    assert service_db.bind is not None
    event.listen(service_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        result = await list_contact_celebrations(service_db, month=8)
    finally:
        event.remove(service_db.bind.sync_engine, "before_cursor_execute", capture)

    assert len(result.birthdays) == 366
    assert result.anniversaries == ()
    assert statements == ["SELECT"]


@pytest.mark.asyncio
async def test_contact_celebrations_reject_invalid_or_unknown_and_never_fabricate(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(first_name=label, last_name="No Fabrication", stage="lead")
        for label in (
            "Unknown",
            "Impossible",
            "Missing month",
            "Verified missing year",
            "Birthday text only",
        )
    ]
    service_db.add_all(contacts)
    await service_db.flush()
    service_db.add_all(
        [
            CRMContactProfile(
                contact_id=contacts[0].id,
                birth_month=8,
                birth_day=10,
                birth_year_quality="unknown",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[1].id,
                birth_month=4,
                birth_day=31,
                birth_year_quality="yearless",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[2].id,
                birth_month=None,
                birth_day=10,
                birth_year_quality="yearless",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[3].id,
                birth_month=8,
                birth_day=11,
                birth_year=None,
                birth_year_quality="verified",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[4].id,
                birth_year_quality="unknown",
                anniversary_year_quality="unknown",
            ),
        ]
    )
    tag = CRMTag(name="August Birthday")
    service_db.add(tag)
    await service_db.flush()
    service_db.add_all(
        [
            CRMContactTag(contact_id=contacts[4].id, tag_id=tag.id),
            CRMTask(
                contact_id=contacts[4].id,
                title="Celebrate birthday August 12",
            ),
        ]
    )
    await service_db.flush()

    assert await list_contact_celebrations(service_db, month=8) == ContactCelebrations(
        birthdays=(), anniversaries=()
    )
    assert await list_contact_celebrations(service_db, month=4) == ContactCelebrations(
        birthdays=(), anniversaries=()
    )


@pytest.mark.asyncio
async def test_contact_celebrations_leap_day_and_empty_month(
    service_db: AsyncSession,
):
    contacts = [
        CRMContact(first_name=label, last_name="Leap", stage="lead")
        for label in ("Verified", "Yearless", "Common year")
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
                birth_year_quality="yearless",
                anniversary_year_quality="unknown",
            ),
            CRMContactProfile(
                contact_id=contacts[2].id,
                birth_month=2,
                birth_day=29,
                birth_year=1900,
                birth_year_quality="verified",
                anniversary_year_quality="unknown",
            ),
        ]
    )
    await service_db.flush()

    result = await list_contact_celebrations(service_db, month=2)
    assert tuple(row.contact_id for row in result.birthdays) == (
        contacts[0].id,
        contacts[1].id,
    )
    assert result.anniversaries == ()
    assert await list_contact_celebrations(service_db, month=3) == type(result)(
        birthdays=(), anniversaries=()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("month", (True, 0, 13, 1.0, "8"))
async def test_contact_celebrations_reject_invalid_month_without_query(
    service_db: AsyncSession,
    month: object,
):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    assert service_db.bind is not None
    event.listen(service_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises((TypeError, ValueError)):
            await list_contact_celebrations(service_db, month=month)  # type: ignore[arg-type]
    finally:
        event.remove(service_db.bind.sync_engine, "before_cursor_execute", capture)
    assert statements == []


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

    middle = await get_contact_neighbors(service_db, contacts[1].id, filters, now=NOW)
    assert (middle.previous_contact_id, middle.next_contact_id) == (
        contacts[0].id,
        contacts[3].id,
    )
    with pytest.raises(ContactNotInDirectory):
        await get_contact_neighbors(service_db, contacts[2].id, filters, now=NOW)
    with pytest.raises(ContactNotFound):
        await get_contact_neighbors(service_db, 999_999, filters, now=NOW)
