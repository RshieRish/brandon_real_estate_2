from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from models.command import CRMContact
from models.command_contacts import (
    CRMContactCapturePosition,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
)
from models.command_provenance import (
    CaptureQuality,
    CRMEntitySource,
    CRMSourceRecord,
    EvidenceLevel,
)
from models.lead import Lead
from services.command_contact_occurrences import (
    ContactOccurrenceOwnershipError,
    ContactOccurrenceSyncResult,
    sync_contact_occurrence_ownership,
)
from services.command_provenance import SourceRecordDraft

SOURCE_CONTACT_ID = "a" * 24
BUNDLE = "b" * 64
PARSER_VERSION = "contacts-v1"
NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)

KIND_SECTIONS = (
    ("contact_timeline_event", "timeline"),
    ("contact_note", "notes"),
    ("contact_saved_search", "saved_searches"),
    ("contact_task", "tasks_to_do"),
    ("contact_task", "tasks_completed"),
    ("contact_task", "tasks_archived"),
    ("contact_smart_plan", "smart_plans"),
    ("contact_opportunity", "opportunities"),
)


def _draft(
    record_kind: str,
    source_key: str,
    payload: dict[str, object],
    *,
    parser_version: str = PARSER_VERSION,
) -> SourceRecordDraft:
    return SourceRecordDraft(
        source_system="kw_command",
        module="contacts",
        record_kind=record_kind,
        source_key=source_key,
        evidence_level=EvidenceLevel.RENDERED_OCCURRENCE,
        display_label="synthetic occurrence",
        payload=payload,
        artifact_paths=("synthetic/contact.json",),
        parser_version=parser_version,
        capture_quality=CaptureQuality.COMPLETE,
        captured_at=NOW,
    )


def _records() -> tuple[SourceRecordDraft, ...]:
    profile = _draft(
        "contact_profile",
        "contact:synthetic:profile",
        {
            "source_contact_id": SOURCE_CONTACT_ID,
            "capture_ordinal": 1,
            "identity_candidate": {"source_contact_id": SOURCE_CONTACT_ID},
        },
    )
    children = tuple(
        _draft(
            kind,
            f"contact:synthetic:{section}",
            {
                "source_contact_id": SOURCE_CONTACT_ID,
                "capture_ordinal": "0000001",
                "section_name": section,
                "occurrence_ordinal": 1,
                "state": section.removeprefix("tasks_") if section.startswith("tasks_") else None,
                "values": {},
            },
        )
        for kind, section in KIND_SECTIONS
    )
    return (profile, *children)


@pytest_asyncio.fixture()
async def occurrence_db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(
                sync,
                tables=(
                    Lead.__table__,
                    CRMContact.__table__,
                    CRMSourceRecord.__table__,
                    CRMEntitySource.__table__,
                    CRMContactCapturePosition.__table__,
                    CRMContactSectionCapture.__table__,
                    CRMContactSourceOccurrence.__table__,
                ),
            )
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _seed(
    db: AsyncSession,
    records: tuple[SourceRecordDraft, ...],
) -> dict[tuple[str, str, str, str, str], CRMSourceRecord]:
    contact = CRMContact(first_name="Synthetic", last_name="Contact", stage="lead")
    db.add(contact)
    await db.flush()
    persisted = {}
    for draft in records:
        row = CRMSourceRecord(
            source_system=draft.source_system,
            module=draft.module,
            record_kind=draft.record_kind,
            source_key=draft.source_key,
            evidence_level=draft.evidence_level.value,
            display_label=draft.display_label,
            payload_json=draft.payload_json,
            capture_quality=draft.capture_quality.value,
            captured_at=draft.captured_at,
            parser_version=draft.parser_version,
        )
        db.add(row)
        await db.flush()
        persisted[draft.identity] = row
    db.add(
        CRMEntitySource(
            entity_type="contact",
            entity_id=contact.id,
            source_record_id=persisted[records[0].identity].id,
        )
    )
    position = CRMContactCapturePosition(
        contact_id=contact.id,
        source_record_id=persisted[records[0].identity].id,
        bundle_fingerprint=BUNDLE,
        capture_ordinal=1,
        source_contact_id=SOURCE_CONTACT_ID,
        captured_at=NOW,
        capture_quality="complete",
        limitations_json="[]",
    )
    db.add(position)
    await db.flush()
    for ordinal, (_, section) in enumerate(KIND_SECTIONS, start=1):
        db.add(
            CRMContactSectionCapture(
                capture_position_id=position.id,
                source_record_id=persisted[records[ordinal].identity].id,
                section_name=section,
                captured_at=NOW,
                capture_quality="complete",
                is_empty=False,
                row_count=1,
                limitations_json="[]",
            )
        )
    await db.flush()
    return persisted


@pytest.mark.asyncio
async def test_sync_owns_all_eight_current_occurrences_and_is_idempotent(occurrence_db):
    records = _records()
    persisted = await _seed(occurrence_db, records)
    select_statements: list[str] = []

    def _capture_selects(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    assert occurrence_db.bind is not None
    event.listen(occurrence_db.bind.sync_engine, "before_cursor_execute", _capture_selects)
    try:
        first = await sync_contact_occurrence_ownership(
            occurrence_db,
            records=records,
            persisted_by_identity=persisted,
            bundle_fingerprint=BUNDLE,
            parser_version=PARSER_VERSION,
        )
    finally:
        event.remove(occurrence_db.bind.sync_engine, "before_cursor_execute", _capture_selects)
    assert len(select_statements) == 4
    assert first == ContactOccurrenceSyncResult(observed=8, created=8, unchanged=0)
    assert await occurrence_db.scalar(
        select(func.count()).select_from(CRMContactSourceOccurrence)
    ) == 8

    second = await sync_contact_occurrence_ownership(
        occurrence_db,
        records=tuple(reversed(records)),
        persisted_by_identity=persisted,
        bundle_fingerprint=BUNDLE,
        parser_version=PARSER_VERSION,
    )
    assert second == ContactOccurrenceSyncResult(observed=8, created=0, unchanged=8)


@pytest.mark.asyncio
async def test_sync_rejects_missing_or_extra_current_persisted_snapshot(occurrence_db):
    records = _records()
    persisted = await _seed(occurrence_db, records)
    missing = dict(persisted)
    missing.pop(records[-1].identity)
    with pytest.raises(ContactOccurrenceOwnershipError, match="snapshot"):
        await sync_contact_occurrence_ownership(
            occurrence_db,
            records=records,
            persisted_by_identity=missing,
            bundle_fingerprint=BUNDLE,
            parser_version=PARSER_VERSION,
        )
    extra = dict(persisted)
    extra[("kw_command", "contacts", "contact_note", "historical", PARSER_VERSION)] = next(iter(persisted.values()))
    with pytest.raises(ContactOccurrenceOwnershipError, match="snapshot"):
        await sync_contact_occurrence_ownership(
            occurrence_db,
            records=records,
            persisted_by_identity=extra,
            bundle_fingerprint=BUNDLE,
            parser_version=PARSER_VERSION,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_contact_id", "c" * 24),
        ("capture_ordinal", "0000000"),
        ("section_name", "notes"),
        ("occurrence_ordinal", 0),
    ],
)
async def test_sync_rejects_malformed_or_cross_section_child_context(
    occurrence_db, field, value
):
    original = _records()
    child = original[1]
    payload = dict(child.payload)
    payload[field] = value
    replacement = _draft(child.record_kind, child.source_key, payload)
    records = (original[0], replacement, *original[2:])
    persisted = await _seed(occurrence_db, records)
    with pytest.raises(ContactOccurrenceOwnershipError):
        await sync_contact_occurrence_ownership(
            occurrence_db,
            records=records,
            persisted_by_identity=persisted,
            bundle_fingerprint=BUNDLE,
            parser_version=PARSER_VERSION,
        )


@pytest.mark.asyncio
async def test_sync_rejects_parser_drift_and_changed_existing_owner(occurrence_db):
    records = _records()
    persisted = await _seed(occurrence_db, records)
    persisted[records[1].identity].parser_version = "contacts-v0"
    with pytest.raises(ContactOccurrenceOwnershipError, match="parser"):
        await sync_contact_occurrence_ownership(
            occurrence_db,
            records=records,
            persisted_by_identity=persisted,
            bundle_fingerprint=BUNDLE,
            parser_version=PARSER_VERSION,
        )
    persisted[records[1].identity].parser_version = PARSER_VERSION
    await sync_contact_occurrence_ownership(
        occurrence_db,
        records=records,
        persisted_by_identity=persisted,
        bundle_fingerprint=BUNDLE,
        parser_version=PARSER_VERSION,
    )
    row = await occurrence_db.scalar(select(CRMContactSourceOccurrence).limit(1))
    assert row is not None
    row.occurrence_ordinal = 2
    await occurrence_db.flush()
    with pytest.raises(ContactOccurrenceOwnershipError, match="conflict"):
        await sync_contact_occurrence_ownership(
            occurrence_db,
            records=records,
            persisted_by_identity=persisted,
            bundle_fingerprint=BUNDLE,
            parser_version=PARSER_VERSION,
        )


@pytest.mark.asyncio
async def test_sync_rejects_duplicate_section_occurrence_ordinal(occurrence_db):
    original = _records()
    duplicate = _draft(
        "contact_timeline_event",
        "contact:synthetic:timeline:duplicate",
        dict(original[1].payload),
    )
    records = (*original, duplicate)
    persisted = await _seed(occurrence_db, records)
    with pytest.raises(ContactOccurrenceOwnershipError, match="ambiguous"):
        await sync_contact_occurrence_ownership(
            occurrence_db,
            records=records,
            persisted_by_identity=persisted,
            bundle_fingerprint=BUNDLE,
            parser_version=PARSER_VERSION,
        )
