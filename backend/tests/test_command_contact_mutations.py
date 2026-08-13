"""Strict Task 5C-E tests for audited contact create/update services."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import services.command_contacts as contacts_service
from database import Base
from models.command import (
    CRMActivity,
    CRMContact,
    CRMContactTag,
    CRMNote,
    CRMSavedSearch,
    CRMTag,
)
from models.command_contacts import (
    CRMContactAuditEvent,
    CRMContactCapturePosition,
    CRMContactProfile,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
)
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from models.lead import Lead
from services.command_contact_contracts import (
    ContactCreateCommand,
    ContactDetail,
    ContactMutationResult,
    ContactNoteCreateCommand,
    ContactSavedSearchCreateCommand,
    ContactSavedSearchValue,
    ContactUpdateCommand,
    WorkspaceMutationResult,
    canonical_contact_audit_json,
    canonical_workspace_saved_search_activity_json,
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


E2_MUTATION_CALLS = (
    "assign_contact_tag",
    "remove_contact_tag",
    "create_contact_note",
    "delete_contact_note",
    "create_contact_saved_search",
    "delete_saved_search",
)


@pytest.mark.parametrize("service_name", E2_MUTATION_CALLS)
@pytest.mark.parametrize("actor_subject", INVALID_ACTORS)
@pytest.mark.asyncio
async def test_e2_mutations_reject_actor_before_any_sql(
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
            if service_name in {"assign_contact_tag", "remove_contact_tag"}:
                await service(db, 1, 1, actor_subject=actor_subject)
            elif service_name == "create_contact_note":
                await service(
                    db,
                    1,
                    ContactNoteCreateCommand("private note"),
                    actor_subject=actor_subject,
                )
            elif service_name == "delete_contact_note":
                await service(db, 1, 1, actor_subject=actor_subject)
            elif service_name == "create_contact_saved_search":
                await service(
                    db,
                    1,
                    ContactSavedSearchCreateCommand("private search", {}),
                    actor_subject=actor_subject,
                )
            else:
                await service(db, 1, actor_subject=actor_subject)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert statements == []


@pytest.mark.asyncio
async def test_assign_and_remove_tag_write_exact_audits_and_explicit_noops(
    mutation_db, monkeypatch
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    tag = CRMTag(name="Synthetic tag")
    db.add(tag)
    await db.flush()

    async def forbidden_commit(_self):
        raise AssertionError("mutation services must not commit")

    monkeypatch.setattr(AsyncSession, "commit", forbidden_commit)
    assigned = await contacts_service.assign_contact_tag(
        db, contact.id, tag.id, actor_subject="7"
    )
    assert isinstance(assigned, ContactMutationResult)
    assert assigned.changed is True and assigned.record_id is not None
    replay = await contacts_service.assign_contact_tag(
        db, contact.id, tag.id, actor_subject="7"
    )
    assert replay == ContactMutationResult(
        contact_id=contact.id,
        record_id=assigned.record_id,
        changed=False,
        audit_entity_type=None,
        audit_event_id=None,
    )
    removed = await contacts_service.remove_contact_tag(
        db, contact.id, tag.id, actor_subject="7"
    )
    assert removed.changed is True and removed.record_id == assigned.record_id
    absent = await contacts_service.remove_contact_tag(
        db, contact.id, tag.id, actor_subject="7"
    )
    assert absent == ContactMutationResult(
        contact_id=contact.id,
        record_id=None,
        changed=False,
        audit_entity_type=None,
        audit_event_id=None,
    )
    audits = (
        await db.scalars(
            select(CRMContactAuditEvent)
            .where(CRMContactAuditEvent.contact_id == contact.id)
            .order_by(CRMContactAuditEvent.id)
        )
    ).all()
    assert [row.action for row in audits] == [
        "contact.tag_added",
        "contact.tag_removed",
    ]
    assert audits[0].before_json == canonical_contact_audit_json(
        action="contact.tag_added",
        phase="before",
        payload={"present": False, "tag_id": tag.id},
    )
    assert audits[1].after_json == canonical_contact_audit_json(
        action="contact.tag_removed",
        phase="after",
        payload={"present": False, "tag_id": tag.id},
    )
    activities = (await db.scalars(select(CRMActivity))).all()
    assert [(row.kind, row.summary) for row in activities] == [
        ("tag_removed", "Removed a contact tag")
    ]


@pytest.mark.asyncio
async def test_assign_tag_exact_uniqueness_race_returns_existing_link_noop(
    mutation_db, monkeypatch
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    tag = CRMTag(name="Synthetic race tag")
    db.add(tag)
    await db.flush()
    original_begin_nested = db.begin_nested
    nested_calls = 0

    def raced_begin_nested():
        nonlocal nested_calls
        nested_calls += 1
        if nested_calls == 1:
            return original_begin_nested()

        @asynccontextmanager
        async def inject_competing_assignment():
            await db.execute(
                insert(CRMContactTag).values(
                    contact_id=contact.id,
                    tag_id=tag.id,
                )
            )
            async with original_begin_nested() as transaction:
                yield transaction

        return inject_competing_assignment()

    monkeypatch.setattr(db, "begin_nested", raced_begin_nested)
    result = await contacts_service.assign_contact_tag(
        db, contact.id, tag.id, actor_subject="7"
    )
    assert result.changed is False
    assert result.record_id is not None
    assert nested_calls == 2
    assert (
        await db.scalar(select(func.count()).select_from(CRMContactTag)) == 1
    )
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_note_create_delete_audits_activity_and_wrong_owner_is_not_found(
    mutation_db,
):
    db, _engine = mutation_db
    contact = await _seed_contact(db, first_name="One")
    other = await _seed_contact(db, first_name="Two")
    body = "private note body"
    created = await contacts_service.create_contact_note(
        db,
        contact.id,
        ContactNoteCreateCommand(body),
        actor_subject="7",
    )
    assert created.changed is True and created.record_id is not None
    with pytest.raises(contacts_service.ContactNotFound, match="contact does not exist"):
        await contacts_service.delete_contact_note(
            db, other.id, created.record_id, actor_subject="7"
        )
    deleted = await contacts_service.delete_contact_note(
        db, contact.id, created.record_id, actor_subject="7"
    )
    assert deleted.changed is True
    assert await db.get(CRMNote, created.record_id) is None
    activities = (
        await db.scalars(
            select(CRMActivity)
            .where(CRMActivity.contact_id == contact.id)
            .order_by(CRMActivity.id)
        )
    ).all()
    assert [(row.kind, row.summary) for row in activities] == [
        ("note", "Added a contact note"),
        ("note_removed", "Removed a contact note"),
    ]
    audits = (
        await db.scalars(
            select(CRMContactAuditEvent)
            .where(CRMContactAuditEvent.contact_id == contact.id)
            .order_by(CRMContactAuditEvent.id)
        )
    ).all()
    assert [row.action for row in audits] == [
        "contact.note_created",
        "contact.note_deleted",
    ]
    assert body not in audits[0].after_json
    assert body not in audits[1].before_json


async def _materialize_child_source(
    db: AsyncSession,
    *,
    contact: CRMContact,
    entity_type: str,
    entity_id: int,
    section_name: str,
    record_kind: str,
) -> tuple[CRMEntitySource, CRMSourceRecord]:
    position_source = CRMSourceRecord(
        source_system="kw_command",
        module="contacts",
        record_kind="contact_capture_position",
        source_key=f"synthetic:position:{contact.id}:{entity_type}",
        evidence_level="displayed_aggregate",
        display_label="Synthetic position",
        payload_json="{}",
        capture_quality="complete",
        parser_version="task5c-e2-tests-v1",
    )
    section_source = CRMSourceRecord(
        source_system="kw_command",
        module="contacts",
        record_kind=f"contact_{section_name}_section",
        source_key=f"synthetic:section:{contact.id}:{entity_type}",
        evidence_level="displayed_aggregate",
        display_label="Synthetic section",
        payload_json="{}",
        capture_quality="complete",
        parser_version="task5c-e2-tests-v1",
    )
    child_source = CRMSourceRecord(
        source_system="kw_command",
        module="contacts",
        record_kind=record_kind,
        source_key=f"synthetic:child:{contact.id}:{entity_type}",
        evidence_level="rendered_occurrence",
        display_label="Synthetic child",
        payload_json='{"values":{}}',
        capture_quality="complete",
        parser_version="task5c-e2-tests-v1",
    )
    db.add_all([position_source, section_source, child_source])
    await db.flush()
    position = CRMContactCapturePosition(
        contact_id=contact.id,
        source_record_id=position_source.id,
        bundle_fingerprint=f"{contact.id:064x}",
        capture_ordinal=1,
        source_contact_id=f"{contact.id:024x}",
        capture_quality="complete",
        limitations_json="[]",
    )
    db.add(position)
    await db.flush()
    section = CRMContactSectionCapture(
        capture_position_id=position.id,
        source_record_id=section_source.id,
        section_name=section_name,
        capture_quality="complete",
        is_empty=False,
        row_count=1,
        limitations_json="[]",
    )
    db.add(section)
    await db.flush()
    db.add(
        CRMContactSourceOccurrence(
            contact_id=contact.id,
            section_capture_id=section.id,
            source_record_id=child_source.id,
            occurrence_ordinal=1,
        )
    )
    link = CRMEntitySource(
        source_record_id=child_source.id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(link)
    await db.flush()
    return link, child_source


@pytest.mark.parametrize(
    ("child_kind", "section_name", "record_kind"),
    (
        ("note", "notes", "contact_note"),
        ("saved_search", "saved_searches", "contact_saved_search"),
    ),
)
@pytest.mark.asyncio
async def test_materialized_child_delete_removes_only_target_link(
    mutation_db, child_kind, section_name, record_kind
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    if child_kind == "note":
        child = CRMNote(contact_id=contact.id, body="private body")
    else:
        child = CRMSavedSearch(
            contact_id=contact.id,
            name="private name",
            criteria_json='{"stage":"lead"}',
        )
    db.add(child)
    await db.flush()
    link, source = await _materialize_child_source(
        db,
        contact=contact,
        entity_type=child_kind,
        entity_id=child.id,
        section_name=section_name,
        record_kind=record_kind,
    )
    if child_kind == "note":
        await contacts_service.delete_contact_note(
            db, contact.id, child.id, actor_subject="7"
        )
    else:
        await contacts_service.delete_saved_search(
            db, child.id, actor_subject="7"
        )
    assert await db.get(CRMEntitySource, link.id) is None
    assert await db.get(CRMSourceRecord, source.id) is not None
    occurrence_count = await db.scalar(
        select(func.count())
        .select_from(CRMContactSourceOccurrence)
        .where(CRMContactSourceOccurrence.source_record_id == source.id)
    )
    assert occurrence_count == 1


@pytest.mark.asyncio
async def test_saved_search_create_list_and_contact_global_delete_are_exact(
    mutation_db,
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    payload = ContactSavedSearchCreateCommand(
        "private search", {"z": 1, "nested": {"b": True, "a": [2, 1]}}
    )
    created = await contacts_service.create_contact_saved_search(
        db, contact.id, payload, actor_subject="7"
    )
    global_search = CRMSavedSearch(
        contact_id=None,
        name="private global",
        criteria_json='{"stage":"lead"}',
    )
    db.add(global_search)
    await db.flush()
    rows = await contacts_service.list_saved_searches(db)
    assert all(isinstance(row, ContactSavedSearchValue) for row in rows)
    assert {row.id for row in rows} == {created.record_id, global_search.id}
    contact_row = next(row for row in rows if row.id == created.record_id)
    assert contact_row.criteria == payload.criteria
    contact_deleted = await contacts_service.delete_saved_search(
        db, created.record_id, actor_subject="7"
    )
    global_deleted = await contacts_service.delete_saved_search(
        db, global_search.id, actor_subject=VALID_LONG_ACTOR
    )
    assert isinstance(contact_deleted, ContactMutationResult)
    assert isinstance(global_deleted, WorkspaceMutationResult)
    assert global_deleted.record_id == global_search.id
    audits = (await db.scalars(select(CRMContactAuditEvent))).all()
    assert [row.action for row in audits] == [
        "contact.saved_search_created",
        "contact.saved_search_deleted",
    ]
    for audit in audits:
        assert "private search" not in audit.before_json + audit.after_json
    activity = (
        await db.scalars(
            select(CRMActivity).where(CRMActivity.contact_id.is_(None))
        )
    ).one()
    assert (
        activity.kind,
        activity.summary,
        activity.source_record_id,
        activity.metadata_json,
    ) == (
        "workspace.saved_search_deleted",
        "Saved search deleted",
        None,
        canonical_workspace_saved_search_activity_json(
            actor_subject=VALID_LONG_ACTOR,
            search_id=global_search.id,
            name="private global",
        ),
    )
    assert "private global" not in activity.metadata_json


@pytest.mark.asyncio
async def test_list_saved_searches_is_read_only_strict_and_deterministic(
    mutation_db,
):
    db, engine = mutation_db
    contact = await _seed_contact(db)
    db.add_all(
        [
            CRMSavedSearch(
                contact_id=contact.id,
                name="first",
                criteria_json='{"a":1}',
                updated_at=datetime(2026, 8, 12, tzinfo=UTC),
            ),
            CRMSavedSearch(
                contact_id=None,
                name="second",
                criteria_json='{"b":2}',
                updated_at=datetime(2026, 8, 13, tzinfo=UTC),
            ),
        ]
    )
    await db.flush()
    pending = CRMTag(name="must not flush")
    db.add(pending)
    statements: list[str] = []
    flushes = 0

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    def before_flush(*_args):
        nonlocal flushes
        flushes += 1

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    event.listen(db.sync_session, "before_flush", before_flush)
    try:
        rows = await contacts_service.list_saved_searches(db)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        event.remove(db.sync_session, "before_flush", before_flush)
    assert [row.name for row in rows] == ["second", "first"]
    assert flushes == 0
    assert sum(statement.lstrip().upper().startswith("SELECT ") for statement in statements) == 1
    assert not any(
        statement.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE "))
        for statement in statements
    )

    await db.execute(
        update(CRMSavedSearch)
        .where(CRMSavedSearch.name == "first")
        .values(criteria_json='{ "a": 1 }')
        .execution_options(synchronize_session=False)
    )
    reparsed = await contacts_service.list_saved_searches(db)
    assert next(row for row in reparsed if row.name == "first").criteria == {
        "a": 1
    }


@pytest.mark.parametrize(
    "criteria_json",
    (
        "not-json",
        "null",
        "[]",
        '{"a":NaN}',
        '{"a":Infinity}',
        '{"a":1,"a":2}',
    ),
)
@pytest.mark.asyncio
async def test_list_saved_searches_rejects_noncanonical_or_ambiguous_criteria(
    mutation_db, criteria_json
):
    db, _engine = mutation_db
    db.add(
        CRMSavedSearch(
            contact_id=None,
            name="private invalid search",
            criteria_json=criteria_json,
        )
    )
    await db.flush()
    with pytest.raises(
        contacts_service.ContactDataIntegrityError,
        match="saved search criteria is invalid",
    ) as caught:
        await contacts_service.list_saved_searches(db)
    assert criteria_json not in str(caught.value)


@pytest.mark.parametrize(
    ("entity_type", "record_kind", "section_name", "corruption"),
    (
        ("note", "contact_note", "notes", "wrong-domain"),
        ("note", "contact_note", "notes", "wrong-kind"),
        ("note", "contact_note", "notes", "wrong-contact"),
        ("saved_search", "contact_saved_search", "saved_searches", "wrong-section"),
    ),
)
@pytest.mark.asyncio
async def test_child_delete_rejects_invalid_provenance_without_partial_writes(
    mutation_db, entity_type, record_kind, section_name, corruption
):
    db, _engine = mutation_db
    contact = await _seed_contact(db, first_name="Owner")
    other = await _seed_contact(db, first_name="Other")
    if entity_type == "note":
        child = CRMNote(contact_id=contact.id, body="private child")
    else:
        child = CRMSavedSearch(
            contact_id=contact.id,
            name="private child",
            criteria_json='{"a":1}',
        )
    db.add(child)
    await db.flush()
    link, source = await _materialize_child_source(
        db,
        contact=contact,
        entity_type=entity_type,
        entity_id=child.id,
        section_name=section_name,
        record_kind=record_kind,
    )
    if corruption == "wrong-domain":
        source.source_system = "other"
    elif corruption == "wrong-kind":
        source.record_kind = "wrong_kind"
    elif corruption == "wrong-contact":
        occurrence = (
            await db.scalars(
                select(CRMContactSourceOccurrence).where(
                    CRMContactSourceOccurrence.source_record_id == source.id
                )
            )
        ).one()
        occurrence.contact_id = other.id
    else:
        occurrence = (
            await db.scalars(
                select(CRMContactSourceOccurrence).where(
                    CRMContactSourceOccurrence.source_record_id == source.id
                )
            )
        ).one()
        section = await db.get(
            CRMContactSectionCapture, occurrence.section_capture_id
        )
        assert section is not None
        section.section_name = "notes"
    await db.flush()
    with pytest.raises(
        contacts_service.ContactDataIntegrityError,
        match="contact source link is invalid",
    ):
        if entity_type == "note":
            await contacts_service.delete_contact_note(
                db, contact.id, child.id, actor_subject="7"
            )
        else:
            await contacts_service.delete_saved_search(
                db, child.id, actor_subject="7"
            )
    assert await db.get(type(child), child.id) is not None
    assert await db.get(CRMEntitySource, link.id) is not None
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.parametrize(
    ("service_name", "table_name"),
    (
        ("create_contact_note", "crm_contact_audit_events"),
        ("delete_contact_note", "crm_contact_audit_events"),
        ("create_contact_saved_search", "crm_contact_audit_events"),
        ("delete_saved_search", "crm_contact_audit_events"),
    ),
)
@pytest.mark.asyncio
async def test_e2_audit_failure_rolls_back_business_and_activity(
    mutation_db, service_name, table_name
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    record_id = None
    if service_name == "delete_contact_note":
        row = CRMNote(contact_id=contact.id, body="private existing note")
        db.add(row)
        await db.flush()
        record_id = row.id
    elif service_name == "delete_saved_search":
        row = CRMSavedSearch(
            contact_id=contact.id,
            name="private existing search",
            criteria_json='{"a":1}',
        )
        db.add(row)
        await db.flush()
        record_id = row.id
    await db.execute(
        text(
            f"CREATE TRIGGER reject_e2_audit BEFORE INSERT ON {table_name} "
            "BEGIN SELECT RAISE(FAIL, 'audit rejected'); END"
        )
    )
    with pytest.raises(contacts_service.ContactDataIntegrityError):
        if service_name == "create_contact_note":
            await contacts_service.create_contact_note(
                db,
                contact.id,
                ContactNoteCreateCommand("private new note"),
                actor_subject="7",
            )
        elif service_name == "delete_contact_note":
            await contacts_service.delete_contact_note(
                db, contact.id, record_id, actor_subject="7"
            )
        elif service_name == "create_contact_saved_search":
            await contacts_service.create_contact_saved_search(
                db,
                contact.id,
                ContactSavedSearchCreateCommand("private new search", {}),
                actor_subject="7",
            )
        else:
            await contacts_service.delete_saved_search(
                db, record_id, actor_subject="7"
            )
    if service_name == "create_contact_note":
        assert await db.scalar(select(func.count()).select_from(CRMNote)) == 0
    elif service_name == "delete_contact_note":
        assert await db.get(CRMNote, record_id) is not None
    elif service_name == "create_contact_saved_search":
        assert await db.scalar(select(func.count()).select_from(CRMSavedSearch)) == 0
    else:
        assert await db.get(CRMSavedSearch, record_id) is not None
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.parametrize("service_name", ("assign_contact_tag", "remove_contact_tag"))
@pytest.mark.asyncio
async def test_tag_audit_failure_rolls_back_assignment_change(
    mutation_db, service_name
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    tag = CRMTag(name="Synthetic rollback tag")
    db.add(tag)
    await db.flush()
    if service_name == "remove_contact_tag":
        db.add(CRMContactTag(contact_id=contact.id, tag_id=tag.id))
        await db.flush()
    await db.execute(
        text(
            "CREATE TRIGGER reject_tag_audit BEFORE INSERT ON "
            "crm_contact_audit_events BEGIN SELECT RAISE(FAIL, 'audit rejected'); END"
        )
    )
    with pytest.raises(contacts_service.ContactDataIntegrityError):
        await getattr(contacts_service, service_name)(
            db, contact.id, tag.id, actor_subject="7"
        )
    assignment_count = await db.scalar(
        select(func.count())
        .select_from(CRMContactTag)
        .where(
            CRMContactTag.contact_id == contact.id,
            CRMContactTag.tag_id == tag.id,
        )
    )
    assert assignment_count == (1 if service_name == "remove_contact_tag" else 0)
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.parametrize(
    "service_name",
    ("remove_contact_tag", "create_contact_note", "delete_contact_note"),
)
@pytest.mark.asyncio
async def test_e2_compatibility_activity_failure_rolls_back_business_and_audit(
    mutation_db, service_name
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    tag = CRMTag(name="Synthetic activity rollback tag")
    note = CRMNote(contact_id=contact.id, body="private existing note")
    db.add_all([tag, note])
    await db.flush()
    assignment = CRMContactTag(contact_id=contact.id, tag_id=tag.id)
    db.add(assignment)
    await db.flush()
    await db.execute(
        text(
            "CREATE TRIGGER reject_e2_activity BEFORE INSERT ON "
            "crm_activities BEGIN SELECT RAISE(FAIL, 'activity rejected'); END"
        )
    )
    with pytest.raises(contacts_service.ContactDataIntegrityError):
        if service_name == "remove_contact_tag":
            await contacts_service.remove_contact_tag(
                db, contact.id, tag.id, actor_subject="7"
            )
        elif service_name == "create_contact_note":
            await contacts_service.create_contact_note(
                db,
                contact.id,
                ContactNoteCreateCommand("private new note"),
                actor_subject="7",
            )
        else:
            await contacts_service.delete_contact_note(
                db, contact.id, note.id, actor_subject="7"
            )
    assert await db.get(CRMContactTag, assignment.id) is not None
    assert await db.get(CRMNote, note.id) is not None
    assert (
        await db.scalar(
            select(func.count()).select_from(CRMNote).where(
                CRMNote.body == "private new note"
            )
        )
        == 0
    )
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.asyncio
async def test_global_saved_search_activity_failure_restores_search(
    mutation_db,
):
    db, _engine = mutation_db
    search = CRMSavedSearch(
        contact_id=None,
        name="private global rollback",
        criteria_json='{"a":1}',
    )
    db.add(search)
    await db.flush()
    await db.execute(
        text(
            "CREATE TRIGGER reject_workspace_activity BEFORE INSERT ON "
            "crm_activities BEGIN SELECT RAISE(FAIL, 'activity rejected'); END"
        )
    )
    with pytest.raises(contacts_service.ContactDataIntegrityError) as caught:
        await contacts_service.delete_saved_search(
            db, search.id, actor_subject="7"
        )
    assert "private global rollback" not in str(caught.value)
    assert await db.get(CRMSavedSearch, search.id) is not None
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0
