"""Strict Task 5C-E4a tests for legacy-lead synchronization."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import services.command_contacts as contacts_service
from database import Base
from models.command import CRMActivity, CRMContact
from models.command_contacts import CRMContactAuditEvent, CRMContactProfile
from models.command_provenance import CRMSourceRecord
from models.lead import Lead
from services.command_contact_contracts import (
    ContactLegacySyncResult,
    canonical_contact_audit_json,
)

INVALID_ACTORS = (
    None,
    "",
    " ",
    "+1",
    "-1",
    "0",
    "01",
    "١",
    " 1",
    "1 ",
    1,
    True,
    "1" * 256,
)
MARKER_SUMMARY = "Imported from internal lead source"


@pytest_asyncio.fixture()
async def sync_db(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'contact-legacy-sync.sqlite'}"
    )

    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine.sync_engine, "connect", enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session, engine
    await engine.dispose()


async def _lead(
    db: AsyncSession,
    index: int,
    *,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    stage: str | None = None,
) -> Lead:
    lead = Lead(
        name=name if name is not None else f"Lead{index} Person",
        email=email if email is not None else f"lead{index}@example.test",
        phone=phone if phone is not None else f"+1555{index:07d}",
        source="synthetic private source",
        routing_status=stage if stage is not None else "new",
    )
    db.add(lead)
    await db.flush()
    return lead


def _marker(contact_id: int, **overrides) -> CRMActivity:
    values = {
        "contact_id": contact_id,
        "kind": "lead_imported",
        "summary": MARKER_SUMMARY,
        "source_record_id": None,
        "metadata_json": "{}",
    }
    values.update(overrides)
    return CRMActivity(**values)


@pytest.mark.parametrize("actor_subject", INVALID_ACTORS)
@pytest.mark.asyncio
async def test_sync_rejects_actor_before_any_sql(sync_db, actor_subject):
    db, engine = sync_db
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises((TypeError, ValueError)):
            await contacts_service.sync_legacy_leads(db, actor_subject=actor_subject)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert statements == []


@pytest.mark.asyncio
async def test_sync_creates_new_contact_and_backfills_exact_missing_marker(
    sync_db, monkeypatch
):
    db, _engine = sync_db
    new_lead = await _lead(
        db,
        1,
        name="  Private   New Lead  ",
        email=" private.new@example.test ",
        phone=" +15550000001 ",
        stage=" qualified ",
    )
    linked_lead = await _lead(db, 2)
    linked = CRMContact(
        lead_id=linked_lead.id,
        first_name="Existing",
        last_name="Untouched",
        email="existing@example.test",
        phone="+15550000002",
        stage="active",
        birthday=date(1980, 1, 2),
        anniversary=date(2020, 3, 4),
    )
    db.add(linked)
    await db.flush()
    profile = CRMContactProfile(
        contact_id=linked.id,
        legal_name="Recovered private name",
        preferred_name="Recovered",
        description="Recovered private description",
        company="Recovered company",
        title="Recovered title",
    )
    db.add(profile)
    await db.flush()
    linked_snapshot = {
        column.name: getattr(linked, column.name)
        for column in CRMContact.__table__.columns
    }
    profile_snapshot = {
        column.name: getattr(profile, column.name)
        for column in CRMContactProfile.__table__.columns
    }

    async def forbidden_commit(_self):
        raise AssertionError("sync service must not commit")

    monkeypatch.setattr(AsyncSession, "commit", forbidden_commit)
    result = await contacts_service.sync_legacy_leads(db, actor_subject="7")

    assert result == ContactLegacySyncResult(
        created=1, timeline_backfilled=1, total_legacy_leads=2
    )
    created = (
        await db.scalars(select(CRMContact).where(CRMContact.lead_id == new_lead.id))
    ).one()
    assert (
        created.first_name,
        created.last_name,
        created.email,
        created.phone,
        created.stage,
        created.birthday,
        created.anniversary,
    ) == (
        "Private",
        "New Lead",
        "private.new@example.test",
        "+15550000001",
        "qualified",
        None,
        None,
    )
    await db.refresh(linked)
    await db.refresh(profile)
    assert {
        column.name: getattr(linked, column.name)
        for column in CRMContact.__table__.columns
    } == linked_snapshot
    assert {
        column.name: getattr(profile, column.name)
        for column in CRMContactProfile.__table__.columns
    } == profile_snapshot

    markers = (
        await db.scalars(
            select(CRMActivity)
            .where(CRMActivity.kind == "lead_imported")
            .order_by(CRMActivity.contact_id)
        )
    ).all()
    assert len(markers) == 2
    assert all(
        row.summary == MARKER_SUMMARY
        and row.source_record_id is None
        and row.metadata_json == "{}"
        for row in markers
    )
    audits = (
        await db.scalars(
            select(CRMContactAuditEvent).order_by(CRMContactAuditEvent.contact_id)
        )
    ).all()
    assert len(audits) == 2
    assert all(row.actor_subject == "7" for row in audits)
    assert audits[0].action == audits[1].action == "contact.legacy_sync_applied"
    created_audit = next(row for row in audits if row.contact_id == created.id)
    assert created_audit.before_json == canonical_contact_audit_json(
        action="contact.legacy_sync_applied", phase="before", payload={}
    )
    assert created_audit.after_json == canonical_contact_audit_json(
        action="contact.legacy_sync_applied",
        phase="after",
        payload={
            "email": created.email,
            "first_name": created.first_name,
            "last_name": created.last_name,
            "phone": created.phone,
            "stage": created.stage,
            "lead_id": created.lead_id,
        },
    )
    backfill_marker = next(row for row in markers if row.contact_id == linked.id)
    backfill_audit = next(row for row in audits if row.contact_id == linked.id)
    assert json.loads(backfill_audit.before_json) == {
        "action": "contact.legacy_sync_applied",
        "activity_present": False,
        "lead_id": linked_lead.id,
    }
    assert json.loads(backfill_audit.after_json) == {
        "action": "contact.legacy_sync_applied",
        "activity_id": backfill_marker.id,
        "activity_present": True,
        "lead_id": linked_lead.id,
    }
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 2


@pytest.mark.asyncio
async def test_sync_recognizes_only_all_five_exact_marker_fields_and_replays_noop(
    sync_db,
):
    db, _engine = sync_db
    source = CRMSourceRecord(
        source_system="synthetic",
        module="test",
        record_kind="marker",
        source_key="synthetic:marker",
        evidence_level="observed_record",
        capture_quality="complete",
        parser_version="test-v1",
    )
    db.add(source)
    await db.flush()
    variants = (
        {},
        {"kind": "contact_imported"},
        {"summary": f"{MARKER_SUMMARY} "},
        {"source_record_id": source.id},
        {"metadata_json": '{"extra":true}'},
    )
    contacts: list[CRMContact] = []
    for index, overrides in enumerate(variants, start=1):
        lead = await _lead(db, index)
        contact = CRMContact(
            lead_id=lead.id,
            first_name=f"Existing{index}",
            last_name="Person",
            stage="lead",
        )
        db.add(contact)
        await db.flush()
        contacts.append(contact)
        db.add(_marker(contact.id, **overrides))
    await db.flush()

    first = await contacts_service.sync_legacy_leads(db, actor_subject="7")
    assert first == ContactLegacySyncResult(0, 4, 5)
    second = await contacts_service.sync_legacy_leads(db, actor_subject="7")
    assert second == ContactLegacySyncResult(0, 0, 5)
    exact_markers = (
        await db.scalars(
            select(CRMActivity).where(
                CRMActivity.contact_id.in_([row.id for row in contacts]),
                CRMActivity.kind == "lead_imported",
                CRMActivity.summary == MARKER_SUMMARY,
                CRMActivity.source_record_id.is_(None),
                CRMActivity.metadata_json == "{}",
            )
        )
    ).all()
    assert len(exact_markers) == 5
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 4


@pytest.mark.parametrize("lead_count", (1, 501, 1001))
@pytest.mark.asyncio
async def test_sync_uses_exact_bounded_three_queries_per_nonempty_batch(
    sync_db, lead_count
):
    db, engine = sync_db
    await db.execute(
        insert(Lead),
        [
            {
                "name": f"Scale{index} Person",
                "email": f"scale{index}@example.test",
                "phone": None,
                "source": "synthetic",
                "lead_type": None,
                "routing_status": "lead",
                "notes": "",
                "metadata_json": "{}",
            }
            for index in range(lead_count)
        ],
    )
    await db.flush()
    selects: list[tuple[str, object]] = []

    def capture(_conn, _cursor, statement, parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT "):
            selects.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await contacts_service.sync_legacy_leads(db, actor_subject="7")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    batches = (lead_count + 499) // 500
    assert result == ContactLegacySyncResult(lead_count, 0, lead_count)
    assert len(selects) == 3 * batches + 1
    lead_selects = [row for row in selects if "FROM leads" in row[0]]
    contact_selects = [row for row in selects if "FROM crm_contacts" in row[0]]
    marker_selects = [row for row in selects if "FROM crm_activities" in row[0]]
    assert len(lead_selects) == batches + 1
    assert len(contact_selects) == len(marker_selects) == batches
    assert all("leads.id >" in statement for statement, _ in lead_selects)
    assert all("ORDER BY leads.id" in statement for statement, _ in lead_selects)
    assert all("LIMIT" in statement for statement, _ in lead_selects)
    assert all(
        "crm_contacts.lead_id IN" in statement for statement, _ in contact_selects
    )
    assert all(
        "ORDER BY crm_contacts.id" in statement for statement, _ in contact_selects
    )
    assert all(
        "crm_activities.contact_id IN" in statement for statement, _ in marker_selects
    )
    assert all("crm_activities.kind =" in statement for statement, _ in marker_selects)
    assert all(
        "crm_activities.summary =" in statement for statement, _ in marker_selects
    )
    assert all(
        "crm_activities.source_record_id IS NULL" in statement
        for statement, _ in marker_selects
    )
    assert all(
        "crm_activities.metadata =" in statement for statement, _ in marker_selects
    )


@pytest.mark.asyncio
async def test_sync_preserves_all_fifty_one_linked_contact_base_rows(sync_db):
    db, _engine = sync_db
    contacts: list[CRMContact] = []
    for index in range(51):
        lead = await _lead(db, index)
        contact = CRMContact(
            lead_id=lead.id,
            first_name=f"Existing{index}",
            last_name=f"Private{index}",
            email=f"existing{index}@example.test",
            phone=f"+1666{index:07d}",
            stage=f"stage-{index}",
            birthday=date(1980 + index % 20, index % 12 + 1, index % 27 + 1),
            anniversary=date(2000 + index % 20, index % 12 + 1, index % 27 + 1),
        )
        db.add(contact)
        await db.flush()
        db.add(_marker(contact.id))
        contacts.append(contact)
    await db.flush()
    snapshots = {
        contact.id: tuple(
            getattr(contact, column.name) for column in CRMContact.__table__.columns
        )
        for contact in contacts
    }

    result = await contacts_service.sync_legacy_leads(db, actor_subject="7")

    assert result == ContactLegacySyncResult(0, 0, 51)
    for contact in contacts:
        await db.refresh(contact)
        assert (
            tuple(
                getattr(contact, column.name) for column in CRMContact.__table__.columns
            )
            == snapshots[contact.id]
        )
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.parametrize("failed_table", ("crm_activities", "crm_contact_audit_events"))
@pytest.mark.asyncio
async def test_sync_activity_or_audit_failure_rolls_back_all_rows(
    sync_db, failed_table
):
    db, _engine = sync_db
    await _lead(db, 1)
    await _lead(db, 2)
    await db.execute(
        text(
            f"CREATE TRIGGER reject_sync_write BEFORE INSERT ON {failed_table} "
            "BEGIN SELECT RAISE(FAIL, 'private sync rejection'); END"
        )
    )

    with pytest.raises(contacts_service.ContactDataIntegrityError) as caught:
        await contacts_service.sync_legacy_leads(db, actor_subject="7")

    assert "private sync rejection" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_sync_backfill_failure_restores_existing_contact_and_marker(
    sync_db,
):
    db, _engine = sync_db
    lead = await _lead(db, 1)
    contact = CRMContact(
        lead_id=lead.id,
        first_name="Private",
        last_name="Existing",
        email="private.existing@example.test",
        stage="active",
    )
    db.add(contact)
    await db.flush()
    snapshot = tuple(
        getattr(contact, column.name) for column in CRMContact.__table__.columns
    )
    await db.execute(
        text(
            "CREATE TRIGGER reject_sync_backfill BEFORE INSERT ON "
            "crm_contact_audit_events BEGIN SELECT RAISE(FAIL, "
            "'private backfill rejection'); END"
        )
    )

    with pytest.raises(contacts_service.ContactDataIntegrityError) as caught:
        await contacts_service.sync_legacy_leads(db, actor_subject="7")

    assert "private" not in str(caught.value).casefold()
    await db.refresh(contact)
    assert (
        tuple(getattr(contact, column.name) for column in CRMContact.__table__.columns)
        == snapshot
    )
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_sync_invalid_lead_in_second_batch_rolls_back_first_batch(sync_db):
    db, _engine = sync_db
    await db.execute(
        insert(Lead),
        [
            {
                "name": f"Valid{index} Person",
                "email": None,
                "phone": None,
                "source": "synthetic",
                "lead_type": None,
                "routing_status": "lead",
                "notes": "",
                "metadata_json": "{}",
            }
            for index in range(500)
        ]
        + [
            {
                "name": "Private" * 30,
                "email": None,
                "phone": None,
                "source": "synthetic",
                "lead_type": None,
                "routing_status": "lead",
                "notes": "",
                "metadata_json": "{}",
            }
        ],
    )
    await db.flush()

    with pytest.raises(contacts_service.ContactDataIntegrityError) as caught:
        await contacts_service.sync_legacy_leads(db, actor_subject="7")

    assert "Private" not in str(caught.value)
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.parametrize(
    "factory",
    (
        lambda: ContactLegacySyncResult(-1, 0, 0),
        lambda: ContactLegacySyncResult(0, -1, 0),
        lambda: ContactLegacySyncResult(0, 0, -1),
        lambda: ContactLegacySyncResult(True, 0, 0),
        lambda: ContactLegacySyncResult(0, 0, 1.0),
        lambda: ContactLegacySyncResult(2, 0, 1),
        lambda: ContactLegacySyncResult(0, 2, 1),
    ),
)
def test_legacy_sync_result_rejects_invalid_or_contradictory_counts(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


@pytest.mark.asyncio
async def test_sync_empty_workspace_executes_only_terminal_lead_query(sync_db):
    db, engine = sync_db
    selects: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT "):
            selects.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await contacts_service.sync_legacy_leads(db, actor_subject="1" * 255)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    assert result == ContactLegacySyncResult(0, 0, 0)
    assert len(selects) == 1
    assert "FROM leads" in selects[0]


@pytest.mark.asyncio
async def test_sync_owns_exactly_one_top_level_nested_savepoint(sync_db):
    db, engine = sync_db
    await _lead(db, 1)
    transaction_sql: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lstrip().upper()
        if normalized.startswith(("SAVEPOINT ", "RELEASE SAVEPOINT ")):
            transaction_sql.append(normalized)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await contacts_service.sync_legacy_leads(db, actor_subject="7")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    assert sum(row.startswith("SAVEPOINT ") for row in transaction_sql) == 1
    assert sum(row.startswith("RELEASE SAVEPOINT ") for row in transaction_sql) == 1


@pytest.mark.asyncio
async def test_sync_queries_compile_exact_postgresql_keyset_and_locks(
    sync_db, monkeypatch
):
    db, _engine = sync_db
    await _lead(db, 1)
    statements = []
    original_scalars = db.scalars

    async def capture_scalars(statement, *args, **kwargs):
        statements.append(statement)
        return await original_scalars(statement, *args, **kwargs)

    monkeypatch.setattr(db, "scalars", capture_scalars)
    await contacts_service.sync_legacy_leads(db, actor_subject="7")
    compiled = [
        str(statement.compile(dialect=postgresql.dialect())) for statement in statements
    ]

    assert len(compiled) == 4
    assert "WHERE leads.id >" in compiled[0]
    assert "ORDER BY leads.id" in compiled[0]
    assert "LIMIT %(param_1)s FOR UPDATE" in compiled[0]
    assert "FROM crm_contacts" in compiled[1]
    assert "ORDER BY crm_contacts.id FOR UPDATE" in compiled[1]
    assert "FROM crm_activities" in compiled[2]
    assert "crm_activities.contact_id IN" in compiled[2]
    assert compiled[2].endswith("FOR UPDATE")
    assert "WHERE leads.id >" in compiled[3]


@pytest.mark.asyncio
async def test_sync_processes_reverse_inserted_leads_in_id_order(sync_db):
    db, _engine = sync_db
    for lead_id in (30, 10, 20):
        db.add(
            Lead(
                id=lead_id,
                name=f"Ordered{lead_id} Person",
                routing_status="lead",
            )
        )
    await db.flush()

    result = await contacts_service.sync_legacy_leads(db, actor_subject="7")

    assert result == ContactLegacySyncResult(3, 0, 3)
    contacts = (await db.scalars(select(CRMContact).order_by(CRMContact.id))).all()
    assert [row.lead_id for row in contacts] == [10, 20, 30]
    audits = (
        await db.scalars(select(CRMContactAuditEvent).order_by(CRMContactAuditEvent.id))
    ).all()
    assert [row.contact_id for row in audits] == [row.id for row in contacts]
