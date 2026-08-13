"""Deterministic query and mutation services for Command Contacts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from models.command import CRMContact, CRMContactTag, CRMTag
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from models.lead import Lead  # noqa: F401 - registers the FK target in metadata
from services.command_contact_contracts import (
    ContactDirectoryFilters,
    ContactOriginFilter,
    ContactSourceFilter,
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
