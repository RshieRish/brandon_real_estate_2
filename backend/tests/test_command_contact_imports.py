"""Strict Task 5C-E4b tests for internal and archive contact imports."""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, func, insert, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import services.command_contacts as contacts_service
from database import Base
from models.command import CRMActivity, CRMContact
from models.command_contacts import CRMContactAuditEvent, CRMContactMethod
from models.lead import Lead
from services.command_contact_contracts import (
    ContactImportCommand,
    ContactImportResult,
    ContactImportRowCommand,
    canonical_contact_audit_json,
)
from services.command_contacts import ingest_archive_contacts

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


@pytest_asyncio.fixture()
async def import_db(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'contact-imports.sqlite'}"
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


def _row(
    index: int,
    *,
    email: str | None | object = ...,
    first_name: str | None = None,
) -> ContactImportRowCommand:
    resolved_email = (
        f"person{index}@example.test" if email is ... else email
    )
    return ContactImportRowCommand(
        first_name or f"Person{index}",
        "Import",
        resolved_email,
        f"+1555{index:07d}",
        "lead",
        date(1990, index % 12 + 1, index % 27 + 1),
        None,
    )


async def _existing_contact(
    db: AsyncSession,
    index: int,
    *,
    email: str,
    lead_backed: bool = False,
) -> CRMContact:
    lead_id = None
    if lead_backed:
        lead = Lead(
            name=f"Legacy{index} Person",
            email=f"legacy{index}@example.test",
            routing_status="legacy",
        )
        db.add(lead)
        await db.flush()
        lead_id = lead.id
    contact = CRMContact(
        lead_id=lead_id,
        first_name=f"Existing{index}",
        last_name="Private",
        email=email,
        phone=f"+1666{index:07d}",
        stage="active",
        birthday=date(1980, index % 12 + 1, index % 27 + 1),
        anniversary=date(2010, index % 12 + 1, index % 27 + 1),
    )
    db.add(contact)
    await db.flush()
    return contact


@pytest.mark.parametrize("actor_subject", INVALID_ACTORS)
@pytest.mark.parametrize("service_name", ("normal", "archive"))
@pytest.mark.asyncio
async def test_imports_reject_actor_before_any_sql(
    import_db, actor_subject, service_name
):
    db, engine = import_db
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises((TypeError, ValueError)):
            if service_name == "normal":
                await contacts_service.import_contacts(
                    db,
                    ContactImportCommand((_row(1),)),
                    actor_subject=actor_subject,
                )
            else:
                await contacts_service.ingest_archive_contacts(
                    db,
                    (_row(1),),
                    ("child@example.test",),
                    actor_subject=actor_subject,
                )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert statements == []


@pytest.mark.asyncio
async def test_normal_import_applies_exact_owner_and_input_order_rules(import_db):
    db, _engine = import_db
    sole = await _existing_contact(db, 1, email="sole@example.test")
    ambiguous = [
        await _existing_contact(db, index, email="ambiguous@example.test")
        for index in (2, 3, 4)
    ]
    rows = (
        _row(10, email=" SOLE@example.test "),
        _row(11, email="ambiguous@example.test"),
        _row(12, email="ＮＥＷ@example.test"),
        _row(13, email="new@example.test"),
        _row(14, email=None),
        _row(15, email=None),
        _row(16, email="not-an-email"),
        _row(17, email="not-an-email"),
    )

    result = await contacts_service.import_contacts(
        db, ContactImportCommand(rows), actor_subject="7"
    )

    assert result == ContactImportResult(created=5, skipped_duplicates=3)
    assert await db.get(CRMContact, sole.id) is sole
    for row in ambiguous:
        assert await db.get(CRMContact, row.id) is row
    created = (
        await db.scalars(
            select(CRMContact)
            .where(CRMContact.id.not_in([sole.id, *(row.id for row in ambiguous)]))
            .order_by(CRMContact.id)
        )
    ).all()
    assert [row.first_name for row in created] == [
        "Person12",
        "Person14",
        "Person15",
        "Person16",
        "Person17",
    ]
    assert created[0].normalized_email == "new@example.test"
    assert [row.normalized_email for row in created[1:]] == [None] * 4
    activities = (
        await db.scalars(select(CRMActivity).order_by(CRMActivity.id))
    ).all()
    assert len(activities) == 5
    assert all(
        row.kind == "contact_imported"
        and row.summary == "Imported through internal CRM import"
        and row.source_record_id is None
        and row.metadata_json == "{}"
        for row in activities
    )
    audits = (
        await db.scalars(
            select(CRMContactAuditEvent).order_by(CRMContactAuditEvent.id)
        )
    ).all()
    assert len(audits) == 5
    assert all(
        row.action == "contact.legacy_import_applied"
        and row.actor_subject == "7"
        for row in audits
    )
    for contact, audit in zip(created, audits, strict=True):
        assert audit.contact_id == contact.id
        assert audit.before_json == canonical_contact_audit_json(
            action="contact.legacy_import_applied",
            phase="before",
            payload={},
        )
        assert audit.after_json == canonical_contact_audit_json(
            action="contact.legacy_import_applied",
            phase="after",
            payload={
                "anniversary": contact.anniversary,
                "birthday": contact.birthday,
                "email": contact.email,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "phone": contact.phone,
                "stage": contact.stage,
            },
        )
    assert await db.scalar(select(func.count()).select_from(CRMContactMethod)) == 0


@pytest.mark.asyncio
async def test_archive_ingest_returns_private_immutable_request_owner_map(
    import_db,
):
    db, _engine = import_db
    sole = await _existing_contact(db, 1, email="sole@example.test")
    await _existing_contact(db, 2, email="ambiguous@example.test")
    await _existing_contact(db, 3, email="ambiguous@example.test")
    contacts = (
        _row(10, email="new@example.test"),
        _row(11, email="ＮＥＷ@example.test"),
        _row(12, email=None),
    )

    result = await contacts_service.ingest_archive_contacts(
        db,
        contacts,
        (
            "sole@example.test",
            "ambiguous@example.test",
            "unresolved@example.test",
            None,
        ),
        actor_subject="7",
    )

    assert type(result).__name__ == "_ArchiveContactIngestResult"
    assert tuple(field.name for field in dataclasses.fields(result)) == (
        "created",
        "skipped_duplicates",
        "owner_contact_ids_by_normalized_email",
    )
    assert result.created == 2
    assert result.skipped_duplicates == 1
    created = (
        await db.scalars(
            select(CRMContact)
            .where(CRMContact.id > sole.id)
            .order_by(CRMContact.id)
        )
    ).all()
    new_contact = next(row for row in created if row.normalized_email == "new@example.test")
    assert dict(result.owner_contact_ids_by_normalized_email) == {
        "ambiguous@example.test": None,
        "new@example.test": new_contact.id,
        "sole@example.test": sole.id,
        "unresolved@example.test": None,
    }
    with pytest.raises(TypeError):
        result.owner_contact_ids_by_normalized_email["new@example.test"] = 999
    with pytest.raises(TypeError):
        json.dumps(result)
    with pytest.raises((TypeError, ValueError)):
        dataclasses.asdict(result)
    assert "new@example.test" not in repr(result)
    assert "_ArchiveContactIngestResult" not in contacts_service.__all__
    assert "ingest_archive_contacts" in contacts_service.__all__
    assert ingest_archive_contacts is contacts_service.ingest_archive_contacts
    activities = (
        await db.scalars(
            select(CRMActivity).where(
                CRMActivity.kind == "archive_contact_imported"
            )
        )
    ).all()
    assert len(activities) == 2
    assert all(
        row.summary == "Imported from permitted archive bundle"
        and row.source_record_id is None
        and row.metadata_json == "{}"
        for row in activities
    )
    audits = (
        await db.scalars(
            select(CRMContactAuditEvent).where(
                CRMContactAuditEvent.action
                == "contact.archive_import_applied"
            )
        )
    ).all()
    assert len(audits) == 2
    archive_created = (
        await db.scalars(
            select(CRMContact)
            .where(CRMContact.id.in_([row.contact_id for row in audits]))
            .order_by(CRMContact.id)
        )
    ).all()
    for contact, audit in zip(archive_created, audits, strict=True):
        assert audit.actor_subject == "7"
        assert audit.before_json == canonical_contact_audit_json(
            action="contact.archive_import_applied",
            phase="before",
            payload={},
        )
        assert audit.after_json == canonical_contact_audit_json(
            action="contact.archive_import_applied",
            phase="after",
            payload={
                "anniversary": contact.anniversary,
                "birthday": contact.birthday,
                "email": contact.email,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "phone": contact.phone,
                "stage": contact.stage,
            },
        )


@pytest.mark.parametrize(
    "factory",
    (
        lambda: ContactImportResult(-1, 0),
        lambda: ContactImportResult(0, -1),
        lambda: ContactImportResult(True, 0),
        lambda: ContactImportResult(0, 1.0),
    ),
)
def test_contact_import_result_rejects_invalid_counts(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


@pytest.mark.asyncio
async def test_owner_resolution_rejects_sole_raw_normalized_drift_privately(
    import_db,
):
    db, _engine = import_db
    contact = await _existing_contact(
        db, 1, email="private-original@example.test"
    )
    await db.execute(
        update(CRMContact)
        .where(CRMContact.id == contact.id)
        .values(normalized_email="requested@example.test")
    )
    await db.flush()

    with pytest.raises(contacts_service.ContactDataIntegrityError) as caught:
        await contacts_service.import_contacts(
            db,
            ContactImportCommand(
                (_row(1, email="requested@example.test"),)
            ),
            actor_subject="7",
        )

    assert str(caught.value) == "contact email normalization is invalid"
    assert "private-original" not in str(caught.value)
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 1
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_owner_query_returns_at_most_two_rows_for_ambiguous_key(
    import_db, monkeypatch
):
    db, _engine = import_db
    for index in range(7):
        await _existing_contact(db, index, email="crowded@example.test")
    owner_row_counts: list[int] = []
    owner_statements: list[object] = []
    original_execute = db.execute

    async def capture_execute(statement, *args, **kwargs):
        result = await original_execute(statement, *args, **kwargs)
        sql = str(statement)
        if "row_number() OVER" not in sql:
            return result
        rows = result.all()
        owner_row_counts.append(len(rows))
        owner_statements.append(statement)

        class ResultProxy:
            def all(self):
                return rows

        return ResultProxy()

    monkeypatch.setattr(db, "execute", capture_execute)
    result = await contacts_service.import_contacts(
        db,
        ContactImportCommand((_row(10, email="crowded@example.test"),)),
        actor_subject="7",
    )

    assert result == ContactImportResult(0, 1)
    assert owner_row_counts == [2]
    assert len(owner_statements) == 1
    sql = str(owner_statements[0])
    assert "row_number() OVER" in sql
    assert "<= :" in sql
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 7


@pytest.mark.asyncio
async def test_normal_import_thousand_distinct_keys_use_two_bounded_key_batches(
    import_db,
):
    db, engine = import_db
    payload = ContactImportCommand(
        tuple(_row(index) for index in range(1_000))
    )
    selects: list[tuple[str, object]] = []

    def capture(_conn, _cursor, statement, parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT "):
            selects.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await contacts_service.import_contacts(
            db, payload, actor_subject="7"
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    assert result == ContactImportResult(1_000, 0)
    assert len(selects) == 2
    aggregate_selects = [row for row in selects if "row_number() OVER" in row[0]]
    lock_selects = [row for row in selects if "FROM crm_contacts" in row[0] and row not in aggregate_selects]
    assert len(aggregate_selects) == 2
    assert lock_selects == []
    assert all("<=" in statement for statement, _ in aggregate_selects)
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 1_000
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 1_000
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 1_000


@pytest.mark.parametrize("service_name", ("normal", "archive"))
@pytest.mark.parametrize(
    "failed_table", ("crm_activities", "crm_contact_audit_events")
)
@pytest.mark.asyncio
async def test_import_late_activity_or_audit_failure_rolls_back_every_row(
    import_db, service_name, failed_table
):
    db, _engine = import_db
    await db.execute(
        text(
            f"CREATE TRIGGER reject_second_import BEFORE INSERT ON {failed_table} "
            "WHEN NEW.contact_id = 2 BEGIN SELECT RAISE(FAIL, "
            "'private import rejection'); END"
        )
    )
    rows = (_row(1), _row(2))

    with pytest.raises(contacts_service.ContactDataIntegrityError) as caught:
        if service_name == "normal":
            await contacts_service.import_contacts(
                db, ContactImportCommand(rows), actor_subject="7"
            )
        else:
            await contacts_service.ingest_archive_contacts(
                db, rows, (), actor_subject="7"
            )

    assert "private import rejection" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_import_preserves_all_fifty_one_lead_backed_rows_and_replays(
    import_db,
):
    db, _engine = import_db
    contacts = [
        await _existing_contact(
            db,
            index,
            email=f"legacy-owner-{index}@example.test",
            lead_backed=True,
        )
        for index in range(51)
    ]
    snapshots = {
        contact.id: tuple(
            getattr(contact, column.name)
            for column in CRMContact.__table__.columns
        )
        for contact in contacts
    }
    payload = ContactImportCommand(
        (
            _row(1, email="legacy-owner-1@example.test"),
            _row(999, email="new-owner@example.test"),
        )
    )

    first = await contacts_service.import_contacts(
        db, payload, actor_subject="7"
    )
    second = await contacts_service.import_contacts(
        db, payload, actor_subject="7"
    )

    assert first == ContactImportResult(1, 1)
    assert second == ContactImportResult(0, 2)
    for contact in contacts:
        await db.refresh(contact)
        assert tuple(
            getattr(contact, column.name)
            for column in CRMContact.__table__.columns
        ) == snapshots[contact.id]
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 1
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 1


@pytest.mark.asyncio
async def test_archive_ingest_resolves_child_only_keys_with_zero_contact_rows(
    import_db,
):
    db, _engine = import_db
    sole = await _existing_contact(db, 1, email="child-owner@example.test")

    result = await contacts_service.ingest_archive_contacts(
        db,
        (),
        ("child-owner@example.test", "missing-child@example.test", None),
        actor_subject="7",
    )

    assert result.created == result.skipped_duplicates == 0
    assert dict(result.owner_contact_ids_by_normalized_email) == {
        "child-owner@example.test": sole.id,
        "missing-child@example.test": None,
    }
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_archive_ingest_released_savepoint_is_rolled_back_by_outer_request(
    import_db,
):
    db, _engine = import_db
    db.add(Lead(name="Outer request sentinel", routing_status="lead"))
    await db.flush()
    await contacts_service.ingest_archive_contacts(
        db, (_row(1),), (), actor_subject="7"
    )
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 1

    await db.rollback()

    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_owner_resolver_ignores_contact_methods(import_db):
    db, _engine = import_db
    contact = await _existing_contact(db, 1, email="owner@example.test")
    db.add(
        CRMContactMethod(
            contact_id=contact.id,
            source_key="synthetic:method",
            kind="email",
            raw_value="method-only@example.test",
            normalized_value="method-only@example.test",
            is_primary=True,
        )
    )
    await db.flush()

    result = await contacts_service.import_contacts(
        db,
        ContactImportCommand((_row(2, email="method-only@example.test"),)),
        actor_subject="7",
    )

    assert result == ContactImportResult(1, 0)
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 2


@pytest.mark.asyncio
async def test_import_null_canonical_replay_creates_again(import_db):
    db, _engine = import_db
    payload = ContactImportCommand((_row(1, email="not-an-email"),))

    first = await contacts_service.import_contacts(
        db, payload, actor_subject="7"
    )
    second = await contacts_service.import_contacts(
        db, payload, actor_subject="7"
    )

    assert first == second == ContactImportResult(1, 0)
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 2
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 2
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 2


@pytest.mark.asyncio
async def test_owner_resolver_batches_sole_keys_and_compiles_postgresql_locks(
    import_db, monkeypatch
):
    db, _engine = import_db
    await db.execute(
        insert(CRMContact),
        [
            {
                "first_name": f"Owner{index}",
                "last_name": "Synthetic",
                "email": f"owner{index}@example.test",
                "normalized_email": f"owner{index}@example.test",
                "phone": None,
                "stage": "lead",
                "birthday": None,
                "anniversary": None,
            }
            for index in range(501)
        ],
    )
    await db.flush()
    statements: list[object] = []

    def capture(execute_state):
        if execute_state.is_select:
            statements.append(execute_state.statement)

    event.listen(db.sync_session, "do_orm_execute", capture)
    try:
        result = await contacts_service.import_contacts(
            db,
            ContactImportCommand(
                tuple(
                    _row(index, email=f"owner{index}@example.test")
                    for index in range(501)
                )
            ),
            actor_subject="7",
        )
    finally:
        event.remove(db.sync_session, "do_orm_execute", capture)

    assert result == ContactImportResult(0, 501)
    assert len(statements) == 4
    compiled = [
        str(statement.compile(dialect=postgresql.dialect()))
        for statement in statements
    ]
    assert sum("row_number() OVER" in sql for sql in compiled) == 2
    lock_sql = [sql for sql in compiled if "row_number() OVER" not in sql]
    assert len(lock_sql) == 2
    assert all("ORDER BY crm_contacts.id FOR UPDATE" in sql for sql in lock_sql)


@pytest.mark.asyncio
async def test_archive_accepts_ten_thousand_contacts_and_rejects_more_before_sql(
    import_db,
):
    db, engine = import_db
    repeated = _row(1, email="archive-bound@example.test")

    result = await contacts_service.ingest_archive_contacts(
        db, (repeated,) * 10_000, (), actor_subject="7"
    )

    assert result.created == 1
    assert result.skipped_duplicates == 9_999
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(TypeError):
            await contacts_service.ingest_archive_contacts(
                db, (repeated,) * 10_001, (), actor_subject="7"
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert statements == []


def test_archive_result_defensively_copies_owner_map_and_redacts_repr():
    owners = {"private@example.test": 7}
    result = contacts_service._ArchiveContactIngestResult(1, 0, owners)
    owners["private@example.test"] = 99

    assert result.owner_contact_ids_by_normalized_email[
        "private@example.test"
    ] == 7
    assert "private@example.test" not in repr(result)


@pytest.mark.parametrize("service_name", ("normal", "archive"))
@pytest.mark.asyncio
async def test_import_services_use_one_savepoint_and_never_commit(
    import_db, service_name, monkeypatch
):
    db, engine = import_db
    transaction_sql: list[str] = []

    async def forbidden_commit(_self):
        raise AssertionError("import services must not commit")

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lstrip().upper()
        if normalized.startswith(("SAVEPOINT ", "RELEASE SAVEPOINT ")):
            transaction_sql.append(normalized)

    monkeypatch.setattr(AsyncSession, "commit", forbidden_commit)
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        if service_name == "normal":
            await contacts_service.import_contacts(
                db,
                ContactImportCommand((_row(1),)),
                actor_subject="1" * 255,
            )
        else:
            await contacts_service.ingest_archive_contacts(
                db, (_row(1),), (), actor_subject="1" * 255
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    assert sum(row.startswith("SAVEPOINT ") for row in transaction_sql) == 1
    assert sum(
        row.startswith("RELEASE SAVEPOINT ") for row in transaction_sql
    ) == 1


@pytest.mark.asyncio
async def test_archive_import_preserves_fifty_one_lead_backed_rows_and_replays(
    import_db,
):
    db, _engine = import_db
    contacts = [
        await _existing_contact(
            db,
            index,
            email=f"archive-legacy-{index}@example.test",
            lead_backed=True,
        )
        for index in range(51)
    ]
    snapshots = {
        contact.id: tuple(
            getattr(contact, column.name)
            for column in CRMContact.__table__.columns
        )
        for contact in contacts
    }
    rows = (
        _row(1, email="archive-legacy-1@example.test"),
        _row(999, email="archive-new@example.test"),
    )

    first = await contacts_service.ingest_archive_contacts(
        db, rows, (), actor_subject="7"
    )
    second = await contacts_service.ingest_archive_contacts(
        db, rows, (), actor_subject="7"
    )

    assert (first.created, first.skipped_duplicates) == (1, 1)
    assert (second.created, second.skipped_duplicates) == (0, 2)
    for contact in contacts:
        await db.refresh(contact)
        assert tuple(
            getattr(contact, column.name)
            for column in CRMContact.__table__.columns
        ) == snapshots[contact.id]
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 1
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 1


@pytest.mark.parametrize(
    ("contacts", "references"),
    (
        ([], ()),
        ((object(),), ()),
        ((), []),
        ((), (7,)),
        ((), (True,)),
    ),
)
@pytest.mark.asyncio
async def test_archive_rejects_wrong_container_or_element_types_before_sql(
    import_db, contacts, references
):
    db, engine = import_db
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(TypeError):
            await contacts_service.ingest_archive_contacts(
                db, contacts, references, actor_subject="7"
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert statements == []
