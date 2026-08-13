"""Strict Task 5C-E tests for audited contact create/update services."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import services.command_contacts as contacts_service
from database import Base
from models.command import CRMActivity, CRMContact
from models.command_contacts import CRMContactAuditEvent, CRMContactProfile
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from models.lead import Lead
from services.command_contact_contracts import (
    ContactCreateCommand,
    ContactDetail,
    ContactUpdateCommand,
    canonical_contact_audit_json,
)


@pytest_asyncio.fixture()
async def mutation_db(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'contact-mutations.sqlite'}"
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
        yield session, engine
    await engine.dispose()


def _create_payload(**overrides) -> ContactCreateCommand:
    values = {
        "first_name": "Private",
        "last_name": "Person",
        "email": "private@example.test",
        "phone": "+15550000000",
        "stage": "lead",
        "birthday": date(1990, 3, 4),
        "anniversary": date(2020, 1, 2),
    }
    values.update(overrides)
    return ContactCreateCommand(**values)


async def _seed_contact(
    db: AsyncSession,
    *,
    first_name: str = "Existing",
    stage: str = "lead",
    lead_backed: bool = False,
) -> CRMContact:
    lead_id = None
    if lead_backed:
        lead = Lead(
            name="Legacy Person",
            email="legacy@example.test",
            routing_status="lead",
        )
        db.add(lead)
        await db.flush()
        lead_id = lead.id
    contact = CRMContact(
        lead_id=lead_id,
        first_name=first_name,
        last_name="Person",
        email="existing@example.test",
        phone="+15550000001",
        stage=stage,
        birthday=date(1985, 5, 6),
        anniversary=None,
    )
    db.add(contact)
    await db.flush()
    return contact


async def _add_valid_recovered_profile(
    db: AsyncSession, contact: CRMContact
) -> CRMContactProfile:
    source = CRMSourceRecord(
        source_system="kw_command",
        module="contacts",
        record_kind="contact_profile",
        source_key=f"synthetic:profile:{contact.id}",
        evidence_level="observed_record",
        display_label="Synthetic profile",
        payload_json=json.dumps({"source_contact_id": f"{contact.id:024x}"}),
        capture_quality="complete",
        captured_at=datetime(2026, 8, 13, tzinfo=UTC),
        parser_version="task5c-e1-tests-v1",
    )
    profile = CRMContactProfile(
        contact_id=contact.id,
        legal_name="Recovered Legal Name",
        birth_year_quality="unknown",
        anniversary_year_quality="unknown",
    )
    db.add_all([source, profile])
    await db.flush()
    db.add(
        CRMEntitySource(
            source_record_id=source.id,
            entity_type="contact",
            entity_id=contact.id,
        )
    )
    await db.flush()
    return profile


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
VALID_LONG_ACTOR = "1" * 255


@pytest.mark.parametrize("service_name", ("create_contact", "update_contact"))
@pytest.mark.parametrize("actor_subject", INVALID_ACTORS)
@pytest.mark.asyncio
async def test_create_and_update_reject_actor_before_any_sql(
    mutation_db, service_name, actor_subject
):
    db, engine = mutation_db
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        service = getattr(contacts_service, service_name)
        with pytest.raises((TypeError, ValueError)):
            if service_name == "create_contact":
                await service(db, _create_payload(), actor_subject=actor_subject)
            else:
                await service(
                    db,
                    999,
                    ContactUpdateCommand(stage="active"),
                    actor_subject=actor_subject,
                )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert statements == []


@pytest.mark.asyncio
async def test_create_contact_writes_exact_activity_audit_and_detail_in_one_savepoint(
    mutation_db, monkeypatch
):
    db, engine = mutation_db
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    async def forbidden_commit(_self):
        raise AssertionError("mutation services must not commit")

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    monkeypatch.setattr(AsyncSession, "commit", forbidden_commit)
    payload = _create_payload()
    try:
        result = await contacts_service.create_contact(
            db, payload, actor_subject=VALID_LONG_ACTOR
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    assert isinstance(result, ContactDetail)
    assert result.contact.first_name == "Private"
    assert result.contact.primary_email == "private@example.test"
    contact = await db.get(CRMContact, result.contact.id)
    assert contact is not None
    assert contact.lead_id is None
    assert contact.normalized_email == "private@example.test"
    activity = (
        await db.scalars(
            select(CRMActivity).where(CRMActivity.contact_id == contact.id)
        )
    ).one()
    assert (
        activity.kind,
        activity.summary,
        activity.source_record_id,
        activity.metadata_json,
    ) == (
        "contact_created",
        "Contact created in Command workspace",
        None,
        "{}",
    )
    audit = (
        await db.scalars(
            select(CRMContactAuditEvent).where(
                CRMContactAuditEvent.contact_id == contact.id
            )
        )
    ).one()
    expected_after = canonical_contact_audit_json(
        action="contact.created",
        phase="after",
        payload={
            "anniversary": payload.anniversary,
            "birthday": payload.birthday,
            "email": payload.email,
            "first_name": payload.first_name,
            "last_name": payload.last_name,
            "phone": payload.phone,
            "stage": payload.stage,
        },
    )
    assert (
        audit.actor_subject,
        audit.action,
        audit.before_json,
        audit.after_json,
    ) == (VALID_LONG_ACTOR, "contact.created", "{}", expected_after)
    assert sum(statement.startswith("SAVEPOINT ") for statement in statements) == 1
    assert sum(statement.startswith("RELEASE SAVEPOINT ") for statement in statements) == 1


@pytest.mark.asyncio
async def test_create_contact_audit_failure_rolls_back_contact_and_activity_safely(
    mutation_db,
):
    db, _engine = mutation_db
    await db.execute(
        text(
            "CREATE TRIGGER reject_contact_audit BEFORE INSERT ON "
            "crm_contact_audit_events BEGIN SELECT RAISE(FAIL, 'audit rejected'); END"
        )
    )
    payload = _create_payload(first_name="PrivateRollback")
    with pytest.raises(contacts_service.ContactDataIntegrityError) as caught:
        await contacts_service.create_contact(db, payload, actor_subject="7")
    assert "PrivateRollback" not in str(caught.value)
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 0


@pytest.mark.asyncio
async def test_create_contact_translates_audit_builder_failure_safely(
    mutation_db, monkeypatch
):
    db, _engine = mutation_db
    original_builder = contacts_service.canonical_contact_audit_json

    def fail_after(*, action, phase, payload):
        if phase == "after":
            raise ValueError("private audit value rejected")
        return original_builder(action=action, phase=phase, payload=payload)

    monkeypatch.setattr(
        contacts_service, "canonical_contact_audit_json", fail_after
    )
    with pytest.raises(contacts_service.ContactDataIntegrityError) as caught:
        await contacts_service.create_contact(
            db,
            _create_payload(first_name="PrivateAfter"),
            actor_subject="7",
        )
    assert "private audit value" not in str(caught.value)
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_update_stage_only_locks_and_writes_exact_fixed_activity_and_audit(
    mutation_db, monkeypatch
):
    db, _engine = mutation_db
    async def forbidden_commit(_self):
        raise AssertionError("mutation services must not commit")

    monkeypatch.setattr(AsyncSession, "commit", forbidden_commit)
    contact = await _seed_contact(db, lead_backed=True)
    original_lead_id = contact.lead_id
    result = await contacts_service.update_contact(
        db,
        contact.id,
        ContactUpdateCommand(stage="active"),
        actor_subject="1",
    )
    assert result.contact.stage == "active"
    await db.refresh(contact)
    assert contact.lead_id == original_lead_id
    activity = (
        await db.scalars(
            select(CRMActivity).where(CRMActivity.contact_id == contact.id)
        )
    ).one()
    assert (
        activity.kind,
        activity.summary,
        activity.source_record_id,
        activity.metadata_json,
    ) == ("stage_changed", "Contact stage changed", None, "{}")
    audit = (
        await db.scalars(
            select(CRMContactAuditEvent).where(
                CRMContactAuditEvent.contact_id == contact.id
            )
        )
    ).one()
    assert audit.actor_subject == "1"
    assert audit.action == "contact.updated"
    assert audit.before_json == canonical_contact_audit_json(
        action="contact.updated",
        phase="before",
        payload={"changed_fields": ("stage",), "stage": "lead"},
    )
    assert audit.after_json == canonical_contact_audit_json(
        action="contact.updated",
        phase="after",
        payload={"changed_fields": ("stage",), "stage": "active"},
    )


@pytest.mark.asyncio
async def test_update_lock_refreshes_the_snapshot_before_auditing(
    mutation_db,
):
    db, _engine = mutation_db
    contact = await _seed_contact(db, stage="lead")
    await db.execute(
        update(CRMContact)
        .where(CRMContact.id == contact.id)
        .values(stage="externally_changed")
        .execution_options(synchronize_session=False)
    )
    assert contact.stage == "lead"
    await contacts_service.update_contact(
        db,
        contact.id,
        ContactUpdateCommand(stage="active"),
        actor_subject="7",
    )
    audit = (
        await db.scalars(
            select(CRMContactAuditEvent).where(
                CRMContactAuditEvent.contact_id == contact.id
            )
        )
    ).one()
    assert json.loads(audit.before_json)["stage"] == "externally_changed"


@pytest.mark.asyncio
async def test_update_translates_invalid_stored_audit_state_to_safe_integrity_error(
    mutation_db,
):
    db, _engine = mutation_db
    contact = await _seed_contact(db, first_name="Before")
    private_value = "P" * 121
    await db.execute(
        update(CRMContact)
        .where(CRMContact.id == contact.id)
        .values(first_name=private_value)
        .execution_options(synchronize_session=False)
    )
    with pytest.raises(contacts_service.ContactDataIntegrityError) as caught:
        await contacts_service.update_contact(
            db,
            contact.id,
            ContactUpdateCommand(first_name="After"),
            actor_subject="7",
        )
    assert private_value not in str(caught.value)
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_update_multiple_fields_preserves_recovered_profile_and_uses_one_activity(
    mutation_db,
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    profile = await _add_valid_recovered_profile(db, contact)
    result = await contacts_service.update_contact(
        db,
        contact.id,
        ContactUpdateCommand(first_name="Changed", email=None, anniversary=date(2024, 2, 3)),
        actor_subject="7",
    )
    assert result.contact.first_name == "Changed"
    assert result.contact.primary_email is None
    assert result.recovered_profile is not None
    assert result.recovered_profile.legal_name == "Recovered Legal Name"
    await db.refresh(profile)
    assert profile.legal_name == "Recovered Legal Name"
    activities = (
        await db.scalars(
            select(CRMActivity).where(CRMActivity.contact_id == contact.id)
        )
    ).all()
    assert [(row.kind, row.summary) for row in activities] == [
        ("contact_updated", "Updated contact profile")
    ]
    audit = (
        await db.scalars(
            select(CRMContactAuditEvent).where(
                CRMContactAuditEvent.contact_id == contact.id
            )
        )
    ).one()
    decoded = json.loads(audit.after_json)
    assert decoded["changed_fields"] == ["anniversary", "email", "first_name"]
    assert "Changed" not in audit.after_json
    assert "existing@example.test" not in audit.before_json


@pytest.mark.parametrize(
    ("field_name", "value", "expected_activity"),
    (
        ("first_name", "Changed", "contact_updated"),
        ("last_name", "Changed", "contact_updated"),
        ("email", "CHANGED@example.test", "contact_updated"),
        ("phone", None, "contact_updated"),
        ("stage", "active", "stage_changed"),
        ("birthday", None, "contact_updated"),
        ("anniversary", date(2024, 2, 3), "contact_updated"),
    ),
)
@pytest.mark.asyncio
async def test_update_each_editable_field_uses_exact_effective_audit(
    mutation_db, field_name, value, expected_activity
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    result = await contacts_service.update_contact(
        db,
        contact.id,
        ContactUpdateCommand(**{field_name: value}),
        actor_subject="7",
    )
    result_field = {
        "email": "primary_email",
        "phone": "primary_phone",
    }.get(field_name, field_name)
    projected_value = getattr(result.contact, result_field)
    if type(value) is date:
        assert (
            projected_value.year,
            projected_value.month,
            projected_value.day,
        ) == (value.year, value.month, value.day)
    else:
        assert projected_value == value
    audit = (
        await db.scalars(
            select(CRMContactAuditEvent).where(
                CRMContactAuditEvent.contact_id == contact.id
            )
        )
    ).one()
    assert json.loads(audit.after_json)["changed_fields"] == [field_name]
    activity = (
        await db.scalars(
            select(CRMActivity).where(CRMActivity.contact_id == contact.id)
        )
    ).one()
    assert activity.kind == expected_activity
    if field_name == "email":
        await db.refresh(contact)
        assert contact.normalized_email == "changed@example.test"


@pytest.mark.asyncio
async def test_update_all_editable_fields_writes_one_mixed_activity_and_sorted_audit(
    mutation_db,
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    payload = ContactUpdateCommand(
        first_name="All",
        last_name="Changed",
        email=None,
        phone=None,
        stage="active",
        birthday=None,
        anniversary=date(2024, 2, 3),
    )
    await contacts_service.update_contact(
        db, contact.id, payload, actor_subject="7"
    )
    activities = (
        await db.scalars(
            select(CRMActivity).where(CRMActivity.contact_id == contact.id)
        )
    ).all()
    assert [(row.kind, row.summary) for row in activities] == [
        ("contact_updated", "Updated contact profile")
    ]
    audit = (
        await db.scalars(
            select(CRMContactAuditEvent).where(
                CRMContactAuditEvent.contact_id == contact.id
            )
        )
    ).one()
    assert json.loads(audit.after_json)["changed_fields"] == sorted(
        {
            "anniversary",
            "birthday",
            "email",
            "first_name",
            "last_name",
            "phone",
            "stage",
        }
    )


@pytest.mark.asyncio
async def test_equal_effective_update_is_noop_with_no_activity_or_audit(
    mutation_db,
):
    db, engine = mutation_db
    contact = await _seed_contact(db)
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await contacts_service.update_contact(
            db,
            contact.id,
            ContactUpdateCommand(
                first_name=contact.first_name,
                email=contact.email,
                birthday=contact.birthday,
            ),
            actor_subject="7",
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert result.contact.id == contact.id
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0
    assert sum(statement.startswith("SAVEPOINT ") for statement in statements) == 1
    assert not any(
        statement.lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE "))
        for statement in statements
    )


@pytest.mark.asyncio
async def test_update_audit_failure_restores_contact_and_writes_nothing(
    mutation_db,
):
    db, _engine = mutation_db
    contact = await _seed_contact(db, first_name="Before")
    await db.execute(
        text(
            "CREATE TRIGGER reject_contact_audit BEFORE INSERT ON "
            "crm_contact_audit_events BEGIN SELECT RAISE(FAIL, 'audit rejected'); END"
        )
    )
    with pytest.raises(contacts_service.ContactDataIntegrityError) as caught:
        await contacts_service.update_contact(
            db,
            contact.id,
            ContactUpdateCommand(first_name="PrivateAfter"),
            actor_subject="7",
        )
    assert "PrivateAfter" not in str(caught.value)
    await db.refresh(contact)
    assert contact.first_name == "Before"
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.parametrize("service_name", ("create_contact", "update_contact"))
@pytest.mark.asyncio
async def test_compatibility_activity_failure_rolls_back_entire_mutation_safely(
    mutation_db, service_name
):
    db, _engine = mutation_db
    contact = None
    if service_name == "update_contact":
        contact = await _seed_contact(db, first_name="Before")
    await db.execute(
        text(
            "CREATE TRIGGER reject_contact_activity BEFORE INSERT ON "
            "crm_activities BEGIN SELECT RAISE(FAIL, 'activity rejected'); END"
        )
    )
    with pytest.raises(contacts_service.ContactDataIntegrityError):
        if service_name == "create_contact":
            await contacts_service.create_contact(
                db,
                _create_payload(first_name="PrivateAfter"),
                actor_subject="7",
            )
        else:
            assert contact is not None
            await contacts_service.update_contact(
                db,
                contact.id,
                ContactUpdateCommand(first_name="PrivateAfter"),
                actor_subject="7",
            )
    if contact is None:
        assert await db.scalar(select(func.count()).select_from(CRMContact)) == 0
    else:
        await db.refresh(contact)
        assert contact.first_name == "Before"
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_create_detail_failure_rolls_back_contact_activity_and_audit(
    mutation_db, monkeypatch
):
    db, _engine = mutation_db

    async def fail_detail(_db, _contact_id):
        raise contacts_service.ContactDataIntegrityError(
            "recovered profile ownership is invalid"
        )

    monkeypatch.setattr(contacts_service, "get_contact_detail", fail_detail)
    with pytest.raises(contacts_service.ContactDataIntegrityError):
        await contacts_service.create_contact(
            db,
            _create_payload(first_name="PrivateAfter"),
            actor_subject="7",
        )
    assert await db.scalar(select(func.count()).select_from(CRMContact)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_update_detail_integrity_failure_rolls_back_business_activity_and_audit(
    mutation_db,
):
    db, _engine = mutation_db
    contact = await _seed_contact(db, first_name="Before")
    db.add(
        CRMContactProfile(
            contact_id=contact.id,
            legal_name="Unlinked recovered profile",
            birth_year_quality="unknown",
            anniversary_year_quality="unknown",
        )
    )
    await db.flush()
    with pytest.raises(contacts_service.ContactDataIntegrityError):
        await contacts_service.update_contact(
            db,
            contact.id,
            ContactUpdateCommand(first_name="PrivateAfter"),
            actor_subject="7",
        )
    await db.refresh(contact)
    assert contact.first_name == "Before"
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.parametrize("contact_id", (0, -1, True, 999))
@pytest.mark.asyncio
async def test_update_missing_or_invalid_contact_is_safe_not_found_without_writes(
    mutation_db, contact_id
):
    db, _engine = mutation_db
    with pytest.raises(contacts_service.ContactNotFound, match="contact does not exist"):
        await contacts_service.update_contact(
            db,
            contact_id,
            ContactUpdateCommand(stage="active"),
            actor_subject="7",
        )
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0
