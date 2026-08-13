"""Strict Task 5C-E tests for audited contact create/update services."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, func, insert, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
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
    ContactBulkAddTag,
    ContactBulkCommand,
    ContactBulkRemoveTag,
    ContactBulkResult,
    ContactBulkSetStage,
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


@pytest.mark.parametrize(
    ("entity_type", "section_name", "record_kind", "child_table"),
    (
        ("note", "notes", "contact_note", "crm_notes"),
        (
            "saved_search",
            "saved_searches",
            "contact_saved_search",
            "crm_saved_searches",
        ),
    ),
)
@pytest.mark.asyncio
async def test_materialized_child_flushes_link_delete_before_child_delete(
    mutation_db,
    entity_type,
    section_name,
    record_kind,
    child_table,
):
    db, engine = mutation_db
    contact = await _seed_contact(db)
    child = (
        CRMNote(contact_id=contact.id, body="private ordered child")
        if entity_type == "note"
        else CRMSavedSearch(
            contact_id=contact.id,
            name="private ordered child",
            criteria_json='{"a":1}',
        )
    )
    db.add(child)
    await db.flush()
    await _materialize_child_source(
        db,
        contact=contact,
        entity_type=entity_type,
        entity_id=child.id,
        section_name=section_name,
        record_kind=record_kind,
    )
    deletes: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("DELETE "):
            deletes.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        if entity_type == "note":
            await contacts_service.delete_contact_note(
                db, contact.id, child.id, actor_subject="7"
            )
        else:
            await contacts_service.delete_saved_search(
                db, child.id, actor_subject="7"
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    link_index = next(
        index
        for index, statement in enumerate(deletes)
        if "crm_entity_sources" in statement
    )
    child_index = next(
        index for index, statement in enumerate(deletes) if child_table in statement
    )
    assert link_index < child_index


@pytest.mark.parametrize(
    ("entity_type", "section_name", "record_kind", "child_table"),
    (
        ("note", "notes", "contact_note", "crm_notes"),
        (
            "saved_search",
            "saved_searches",
            "contact_saved_search",
            "crm_saved_searches",
        ),
    ),
)
@pytest.mark.asyncio
async def test_child_delete_failure_after_link_flush_restores_link_and_child(
    mutation_db,
    entity_type,
    section_name,
    record_kind,
    child_table,
):
    db, engine = mutation_db
    contact = await _seed_contact(db)
    child = (
        CRMNote(contact_id=contact.id, body="private rollback child")
        if entity_type == "note"
        else CRMSavedSearch(
            contact_id=contact.id,
            name="private rollback child",
            criteria_json='{"a":1}',
        )
    )
    db.add(child)
    await db.flush()
    link, _source = await _materialize_child_source(
        db,
        contact=contact,
        entity_type=entity_type,
        entity_id=child.id,
        section_name=section_name,
        record_kind=record_kind,
    )
    await db.execute(
        text(
            f"CREATE TRIGGER reject_ordered_child_delete BEFORE DELETE ON {child_table} "
            "BEGIN SELECT RAISE(FAIL, 'child delete rejected'); END"
        )
    )
    deletes: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("DELETE "):
            deletes.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(contacts_service.ContactDataIntegrityError):
            if entity_type == "note":
                await contacts_service.delete_contact_note(
                    db, contact.id, child.id, actor_subject="7"
                )
            else:
                await contacts_service.delete_saved_search(
                    db, child.id, actor_subject="7"
                )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert any("crm_entity_sources" in statement for statement in deletes)
    assert any(child_table in statement for statement in deletes)
    assert await db.get(CRMEntitySource, link.id) is not None
    assert await db.get(type(child), child.id) is not None


@pytest.mark.parametrize("invalid_name", ("", "P" * 256))
@pytest.mark.asyncio
async def test_global_saved_search_invalid_stored_name_is_safe_and_rolls_back(
    mutation_db, invalid_name
):
    db, _engine = mutation_db
    search = CRMSavedSearch(
        contact_id=None,
        name=invalid_name,
        criteria_json='{"a":1}',
    )
    db.add(search)
    await db.flush()
    with pytest.raises(
        contacts_service.ContactDataIntegrityError,
        match="saved search audit state is invalid",
    ) as caught:
        await contacts_service.delete_saved_search(
            db, search.id, actor_subject="7"
        )
    if invalid_name:
        assert invalid_name not in str(caught.value)
    assert caught.value.__cause__ is None
    assert await db.get(CRMSavedSearch, search.id) is not None
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0


@pytest.mark.asyncio
async def test_two_independent_sessions_assign_same_tag_once(
    mutation_db,
):
    seed_db, engine = mutation_db
    contact = await _seed_contact(seed_db)
    tag = CRMTag(name="Synthetic concurrent tag")
    seed_db.add(tag)
    await seed_db.flush()
    contact_id, tag_id = contact.id, tag.id
    await seed_db.commit()
    await seed_db.execute(text("PRAGMA journal_mode=WAL"))
    await seed_db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    start = asyncio.Event()
    winner_committed = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def assign_once(*, replay_after_winner: bool) -> ContactMutationResult:
        nonlocal ready
        async with factory() as session:
            await session.execute(text("PRAGMA busy_timeout=5000"))
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            if replay_after_winner:
                await winner_committed.wait()
            result = await contacts_service.assign_contact_tag(
                session, contact_id, tag_id, actor_subject="7"
            )
            await session.commit()
            if not replay_after_winner:
                winner_committed.set()
            return result

    # SQLite cannot upgrade a stale concurrent read snapshot through the
    # PostgreSQL FOR UPDATE/unique-race path. Keep two independent sessions
    # alive together, then replay the loser immediately after the winner's
    # externally owned commit. PostgreSQL locking is compiled below.
    first, second = await asyncio.gather(
        assign_once(replay_after_winner=False),
        assign_once(replay_after_winner=True),
    )
    assert sorted((first.changed, second.changed)) == [False, True]
    async with factory() as verify_db:
        assert (
            await verify_db.scalar(
                select(func.count()).select_from(CRMContactTag).where(
                    CRMContactTag.contact_id == contact_id,
                    CRMContactTag.tag_id == tag_id,
                )
            )
            == 1
        )
        audits = (
            await verify_db.scalars(
                select(CRMContactAuditEvent).where(
                    CRMContactAuditEvent.contact_id == contact_id,
                    CRMContactAuditEvent.action == "contact.tag_added",
                )
            )
        ).all()
        assert len(audits) == 1


@pytest.mark.asyncio
async def test_tag_assignment_compiles_postgresql_row_locks_and_named_unique_gate(
    mutation_db, monkeypatch
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    tag = CRMTag(name="Synthetic PostgreSQL tag")
    db.add(tag)
    await db.flush()
    statements = []
    original_scalars = db.scalars

    async def capture_scalars(statement, *args, **kwargs):
        statements.append(statement)
        return await original_scalars(statement, *args, **kwargs)

    monkeypatch.setattr(db, "scalars", capture_scalars)
    await contacts_service.assign_contact_tag(
        db, contact.id, tag.id, actor_subject="7"
    )
    compiled = [
        str(statement.compile(dialect=postgresql.dialect()))
        for statement in statements
    ]
    assert any(
        "FROM crm_contacts" in sql and "FOR UPDATE" in sql for sql in compiled
    )
    assert any(
        "FROM crm_tags" in sql and "FOR UPDATE" in sql for sql in compiled
    )
    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in CRMContactTag.__table__.constraints
        if constraint.name is not None
    }
    assert unique_constraints["uq_crm_contact_tag"] == ("contact_id", "tag_id")

    class PostgreSQLOrigin(Exception):
        def __init__(self, constraint_name: str):
            self.diag = type(
                "Diagnostic", (), {"constraint_name": constraint_name}
            )()

    exact = IntegrityError(
        "INSERT INTO crm_contact_tags",
        {},
        PostgreSQLOrigin("uq_crm_contact_tag"),
    )
    unrelated = IntegrityError(
        "INSERT INTO crm_contact_tags",
        {},
        PostgreSQLOrigin("other_constraint"),
    )
    assert contacts_service._is_contact_tag_uniqueness_error(exact) is True
    assert contacts_service._is_contact_tag_uniqueness_error(unrelated) is False


@pytest.mark.parametrize(
    ("constraint_name", "expected"),
    (("uq_crm_contact_tag", True), ("other_constraint", False)),
)
def test_tag_uniqueness_gate_reads_exact_asyncpg_wrapped_constraint(
    constraint_name, expected
):
    class AsyncpgDriverOrigin(Exception):
        def __init__(self, name: str):
            self.constraint_name = name

    wrapper = Exception("uq_crm_contact_tag text must not classify a race")
    wrapper.__cause__ = AsyncpgDriverOrigin(constraint_name)
    error = IntegrityError("INSERT INTO crm_contact_tags", {}, wrapper)

    assert contacts_service._is_contact_tag_uniqueness_error(error) is expected


@pytest.mark.asyncio
async def test_assign_tag_does_not_recover_unrelated_constraint_error(
    mutation_db, monkeypatch
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    tag = CRMTag(name="Synthetic unrelated constraint tag")
    db.add(tag)
    await db.flush()
    original_flush = db.flush

    class PostgreSQLOrigin(Exception):
        def __init__(self):
            self.diag = type(
                "Diagnostic", (), {"constraint_name": "other_constraint"}
            )()

    async def fail_assignment_flush(*args, **kwargs):
        if any(isinstance(row, CRMContactTag) for row in db.new):
            raise IntegrityError(
                "INSERT INTO crm_contact_tags",
                {},
                PostgreSQLOrigin(),
            )
        return await original_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", fail_assignment_flush)
    with pytest.raises(IntegrityError):
        await contacts_service.assign_contact_tag(
            db, contact.id, tag.id, actor_subject="7"
        )
    assert await db.scalar(select(func.count()).select_from(CRMContactTag)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.parametrize("actor_subject", INVALID_ACTORS)
@pytest.mark.parametrize(
    "action",
    (
        ContactBulkSetStage("set_stage", "active"),
        ContactBulkAddTag("add_tag", 1),
        ContactBulkRemoveTag("remove_tag", 1),
    ),
)
@pytest.mark.asyncio
async def test_bulk_rejects_actor_before_any_sql(mutation_db, actor_subject, action):
    db, engine = mutation_db
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises((TypeError, ValueError)):
            await contacts_service.apply_contact_bulk_action(
                db,
                ContactBulkCommand((1,), action),
                actor_subject=actor_subject,
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert statements == []


@pytest.mark.asyncio
async def test_bulk_stage_sorts_ids_changes_only_effective_rows_and_audits(
    mutation_db, monkeypatch
):
    db, _engine = mutation_db
    first = await _seed_contact(db, first_name="First", stage="lead")
    second = await _seed_contact(db, first_name="Second", stage="active")
    third = await _seed_contact(db, first_name="Third", stage="lead")

    async def forbidden_commit(_self):
        raise AssertionError("mutation services must not commit")

    monkeypatch.setattr(AsyncSession, "commit", forbidden_commit)
    result = await contacts_service.apply_contact_bulk_action(
        db,
        ContactBulkCommand(
            (third.id, first.id, second.id),
            ContactBulkSetStage("set_stage", "active"),
        ),
        actor_subject="7",
    )
    assert result == ContactBulkResult(
        requested_contact_ids=(first.id, second.id, third.id),
        actioned_contact_ids=(first.id, third.id),
        action="set_stage",
    )
    rows = (await db.scalars(select(CRMContact).order_by(CRMContact.id))).all()
    assert [row.stage for row in rows] == ["active", "active", "active"]
    audits = (
        await db.scalars(
            select(CRMContactAuditEvent).order_by(CRMContactAuditEvent.contact_id)
        )
    ).all()
    assert [row.contact_id for row in audits] == [first.id, third.id]
    assert all(row.action == "contact.bulk_stage_set" for row in audits)
    assert all(
        row.before_json
        == canonical_contact_audit_json(
            action="contact.bulk_stage_set",
            phase="before",
            payload={"stage": "lead"},
        )
        for row in audits
    )
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0


@pytest.mark.asyncio
async def test_bulk_add_and_remove_tag_preserve_mixed_noops_and_exact_audits(
    mutation_db,
):
    db, _engine = mutation_db
    contacts = [
        await _seed_contact(db, first_name=f"Contact{index}") for index in range(3)
    ]
    tag = CRMTag(name="Synthetic bulk tag")
    db.add(tag)
    await db.flush()
    existing = CRMContactTag(contact_id=contacts[1].id, tag_id=tag.id)
    db.add(existing)
    await db.flush()
    requested = tuple(row.id for row in reversed(contacts))

    added = await contacts_service.apply_contact_bulk_action(
        db,
        ContactBulkCommand(requested, ContactBulkAddTag("add_tag", tag.id)),
        actor_subject="7",
    )
    assert added == ContactBulkResult(
        requested_contact_ids=tuple(row.id for row in contacts),
        actioned_contact_ids=(contacts[0].id, contacts[2].id),
        action="add_tag",
    )
    replay = await contacts_service.apply_contact_bulk_action(
        db,
        ContactBulkCommand(requested, ContactBulkAddTag("add_tag", tag.id)),
        actor_subject="7",
    )
    assert replay.actioned_contact_ids == ()

    await db.delete(
        (
            await db.scalars(
                select(CRMContactTag).where(
                    CRMContactTag.contact_id == contacts[1].id,
                    CRMContactTag.tag_id == tag.id,
                )
            )
        ).one()
    )
    await db.flush()
    removed = await contacts_service.apply_contact_bulk_action(
        db,
        ContactBulkCommand(requested, ContactBulkRemoveTag("remove_tag", tag.id)),
        actor_subject="7",
    )
    assert removed == ContactBulkResult(
        requested_contact_ids=tuple(row.id for row in contacts),
        actioned_contact_ids=(contacts[0].id, contacts[2].id),
        action="remove_tag",
    )
    audits = (
        await db.scalars(select(CRMContactAuditEvent).order_by(CRMContactAuditEvent.id))
    ).all()
    assert [row.action for row in audits] == [
        "contact.bulk_tag_added",
        "contact.bulk_tag_added",
        "contact.bulk_tag_removed",
        "contact.bulk_tag_removed",
    ]
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0


async def _capture_bulk_selects(
    db: AsyncSession,
    engine,
    payload: ContactBulkCommand,
) -> tuple[ContactBulkResult, list[str]]:
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT "):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await contacts_service.apply_contact_bulk_action(
            db, payload, actor_subject="7"
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    return result, statements


@pytest.mark.parametrize(
    ("action_name", "expected_selects"),
    (("set_stage", 1), ("add_tag", 3), ("remove_tag", 3)),
)
@pytest.mark.asyncio
async def test_bulk_select_count_is_fixed_for_one_vs_two_hundred(
    mutation_db, action_name, expected_selects
):
    db, engine = mutation_db
    contacts = [
        CRMContact(
            first_name=f"Bulk{index}",
            last_name="Contact",
            stage="lead",
        )
        for index in range(200)
    ]
    db.add_all(contacts)
    await db.flush()
    one_id = (contacts[0].id,)
    all_ids = tuple(contact.id for contact in contacts)
    if action_name == "set_stage":
        one_action = ContactBulkSetStage("set_stage", "active")
        all_action = ContactBulkSetStage("set_stage", "qualified")
    else:
        one_tag = CRMTag(name=f"one-{action_name}")
        all_tag = CRMTag(name=f"all-{action_name}")
        db.add_all([one_tag, all_tag])
        await db.flush()
        if action_name == "remove_tag":
            db.add(CRMContactTag(contact_id=contacts[0].id, tag_id=one_tag.id))
            db.add_all(
                [
                    CRMContactTag(contact_id=contact.id, tag_id=all_tag.id)
                    for contact in contacts
                ]
            )
            await db.flush()
            one_action = ContactBulkRemoveTag("remove_tag", one_tag.id)
            all_action = ContactBulkRemoveTag("remove_tag", all_tag.id)
        else:
            one_action = ContactBulkAddTag("add_tag", one_tag.id)
            all_action = ContactBulkAddTag("add_tag", all_tag.id)

    one_result, one_selects = await _capture_bulk_selects(
        db, engine, ContactBulkCommand(one_id, one_action)
    )
    all_result, all_selects = await _capture_bulk_selects(
        db, engine, ContactBulkCommand(all_ids, all_action)
    )
    assert len(one_selects) == len(all_selects) == expected_selects
    assert one_result.requested_contact_ids == one_id
    assert all_result.requested_contact_ids == all_ids
    assert "ORDER BY crm_contacts.id" in one_selects[0]
    assert "ORDER BY crm_contacts.id" in all_selects[0]


@pytest.mark.asyncio
async def test_bulk_tag_locks_compile_in_binding_order_for_postgresql(
    mutation_db,
):
    db, _engine = mutation_db
    contacts = [
        await _seed_contact(db, first_name=f"Lock{index}") for index in range(3)
    ]
    tag = CRMTag(name="Synthetic lock order tag")
    db.add(tag)
    await db.flush()
    compiled_selects: list[str] = []

    def capture(execute_state):
        if execute_state.is_select:
            compiled_selects.append(
                str(execute_state.statement.compile(dialect=postgresql.dialect()))
            )

    event.listen(db.sync_session, "do_orm_execute", capture)
    try:
        await contacts_service.apply_contact_bulk_action(
            db,
            ContactBulkCommand(
                tuple(contact.id for contact in reversed(contacts)),
                ContactBulkAddTag("add_tag", tag.id),
            ),
            actor_subject="7",
        )
    finally:
        event.remove(db.sync_session, "do_orm_execute", capture)

    assert len(compiled_selects) == 3
    assert "FROM crm_contacts" in compiled_selects[0]
    assert "ORDER BY crm_contacts.id FOR UPDATE" in compiled_selects[0]
    assert "FROM crm_tags" in compiled_selects[1]
    assert compiled_selects[1].endswith("FOR UPDATE")
    assert "FROM crm_contact_tags" in compiled_selects[2]
    assert "ORDER BY crm_contact_tags.contact_id FOR UPDATE" in compiled_selects[2]


@pytest.mark.asyncio
async def test_bulk_add_race_rereads_all_losers_once(mutation_db, monkeypatch):
    db, engine = mutation_db
    contacts = [
        await _seed_contact(db, first_name=f"Race{index}") for index in range(3)
    ]
    tag = CRMTag(name="Synthetic bulk race tag")
    db.add(tag)
    await db.flush()
    original_begin_nested = db.begin_nested
    nested_calls = 0

    def raced_begin_nested():
        nonlocal nested_calls
        nested_calls += 1
        if nested_calls != 2:
            return original_begin_nested()

        @asynccontextmanager
        async def inject_competing_assignments():
            await db.execute(
                insert(CRMContactTag),
                [{"contact_id": contact.id, "tag_id": tag.id} for contact in contacts],
            )
            async with original_begin_nested() as transaction:
                yield transaction

        return inject_competing_assignments()

    monkeypatch.setattr(db, "begin_nested", raced_begin_nested)
    tag_selects: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if (
            statement.lstrip().upper().startswith("SELECT ")
            and "FROM crm_contact_tags" in statement
        ):
            tag_selects.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await contacts_service.apply_contact_bulk_action(
            db,
            ContactBulkCommand(
                tuple(contact.id for contact in contacts),
                ContactBulkAddTag("add_tag", tag.id),
            ),
            actor_subject="7",
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert result.actioned_contact_ids == ()
    # Initial batch plus exactly one set-based loser reread.
    assert len(tag_selects) == 2
    assert await db.scalar(select(func.count()).select_from(CRMContactTag)) == 3
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0


@pytest.mark.parametrize("action_name", ("set_stage", "add_tag", "remove_tag"))
@pytest.mark.asyncio
async def test_bulk_second_audit_failure_rolls_back_every_action(
    mutation_db, action_name
):
    db, _engine = mutation_db
    contacts = [
        await _seed_contact(db, first_name=f"Rollback{index}", stage="lead")
        for index in range(3)
    ]
    tag = CRMTag(name=f"Synthetic rollback {action_name}")
    db.add(tag)
    await db.flush()
    if action_name == "set_stage":
        action = ContactBulkSetStage("set_stage", "active")
    elif action_name == "add_tag":
        action = ContactBulkAddTag("add_tag", tag.id)
    else:
        db.add_all(
            [
                CRMContactTag(contact_id=contact.id, tag_id=tag.id)
                for contact in contacts
            ]
        )
        await db.flush()
        action = ContactBulkRemoveTag("remove_tag", tag.id)
    await db.execute(
        text(
            "CREATE TRIGGER reject_second_bulk_audit BEFORE INSERT ON "
            "crm_contact_audit_events WHEN NEW.contact_id = "
            f"{contacts[1].id} BEGIN SELECT RAISE(FAIL, 'audit rejected'); END"
        )
    )
    with pytest.raises(contacts_service.ContactDataIntegrityError):
        await contacts_service.apply_contact_bulk_action(
            db,
            ContactBulkCommand(tuple(contact.id for contact in contacts), action),
            actor_subject="7",
        )
    for contact in contacts:
        await db.refresh(contact)
        assert contact.stage == "lead"
    assignment_count = await db.scalar(
        select(func.count())
        .select_from(CRMContactTag)
        .where(CRMContactTag.tag_id == tag.id)
    )
    assert assignment_count == (3 if action_name == "remove_tag" else 0)
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMActivity)) == 0


@pytest.mark.parametrize("missing_kind", ("contact", "tag"))
@pytest.mark.asyncio
async def test_bulk_missing_contact_or_tag_fails_before_dml(mutation_db, missing_kind):
    db, engine = mutation_db
    contact = await _seed_contact(db)
    tag = CRMTag(name="Synthetic validation tag")
    db.add(tag)
    await db.flush()
    payload = ContactBulkCommand(
        (contact.id, 999) if missing_kind == "contact" else (contact.id,),
        ContactBulkAddTag("add_tag", tag.id if missing_kind == "contact" else 999),
    )
    dml: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")):
            dml.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(contacts_service.ContactNotFound):
            await contacts_service.apply_contact_bulk_action(
                db, payload, actor_subject="7"
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert dml == []


@pytest.mark.parametrize("action_name", ("add_tag", "remove_tag"))
@pytest.mark.asyncio
async def test_bulk_tag_writes_and_audits_follow_ascending_contact_order(
    mutation_db, action_name
):
    db, engine = mutation_db
    contacts = [
        await _seed_contact(db, first_name=f"Ordered{index}") for index in range(3)
    ]
    tag = CRMTag(name=f"Synthetic ordered {action_name}")
    db.add(tag)
    await db.flush()
    if action_name == "remove_tag":
        db.add_all(
            [
                CRMContactTag(contact_id=contact.id, tag_id=tag.id)
                for contact in contacts
            ]
        )
        await db.flush()
        assignment_id_to_contact = {
            assignment.id: assignment.contact_id
            for assignment in (
                await db.scalars(
                    select(CRMContactTag).where(CRMContactTag.tag_id == tag.id)
                )
            ).all()
        }
        action = ContactBulkRemoveTag("remove_tag", tag.id)
    else:
        assignment_id_to_contact = {}
        action = ContactBulkAddTag("add_tag", tag.id)

    tag_write_contact_ids: list[int] = []

    def capture(_conn, _cursor, statement, parameters, _context, executemany):
        normalized = statement.casefold()
        if action_name == "add_tag" and normalized.startswith(
            "insert into crm_contact_tags"
        ):
            rows = parameters if executemany else [parameters]
            tag_write_contact_ids.extend(int(row[0]) for row in rows)
        if action_name == "remove_tag" and normalized.startswith(
            "delete from crm_contact_tags"
        ):
            rows = parameters if executemany else [parameters]
            tag_write_contact_ids.extend(
                assignment_id_to_contact[int(row[0])] for row in rows
            )

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await contacts_service.apply_contact_bulk_action(
            db,
            ContactBulkCommand(
                tuple(contact.id for contact in reversed(contacts)), action
            ),
            actor_subject="7",
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    expected = [contact.id for contact in contacts]
    assert result.actioned_contact_ids == tuple(expected)
    assert tag_write_contact_ids == expected
    audits = (
        await db.scalars(select(CRMContactAuditEvent).order_by(CRMContactAuditEvent.id))
    ).all()
    assert [row.contact_id for row in audits] == expected


@pytest.mark.asyncio
async def test_bulk_remove_deletes_in_contact_order_when_link_ids_are_scrambled(
    mutation_db,
):
    db, engine = mutation_db
    contacts = [
        await _seed_contact(db, first_name=f"Scrambled{index}") for index in range(3)
    ]
    tag = CRMTag(name="Synthetic scrambled removal")
    db.add(tag)
    await db.flush()
    db.add_all(
        [
            CRMContactTag(contact_id=contact.id, tag_id=tag.id)
            for contact in reversed(contacts)
        ]
    )
    await db.flush()
    assignments = (
        await db.scalars(select(CRMContactTag).order_by(CRMContactTag.id))
    ).all()
    assert [assignment.contact_id for assignment in assignments] == [
        contact.id for contact in reversed(contacts)
    ]
    assignment_id_to_contact = {
        assignment.id: assignment.contact_id for assignment in assignments
    }

    deleted_contact_ids: list[int] = []

    def capture(_conn, _cursor, statement, parameters, _context, executemany):
        if statement.casefold().startswith("delete from crm_contact_tags"):
            rows = parameters if executemany else [parameters]
            deleted_contact_ids.extend(
                assignment_id_to_contact[int(row[0])] for row in rows
            )

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await contacts_service.apply_contact_bulk_action(
            db,
            ContactBulkCommand(
                tuple(contact.id for contact in reversed(contacts)),
                ContactBulkRemoveTag("remove_tag", tag.id),
            ),
            actor_subject="7",
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    expected = [contact.id for contact in contacts]
    assert deleted_contact_ids == expected
    audits = (
        await db.scalars(select(CRMContactAuditEvent).order_by(CRMContactAuditEvent.id))
    ).all()
    assert [row.contact_id for row in audits] == expected


@pytest.mark.asyncio
async def test_bulk_add_reraises_unrelated_assignment_constraint_error(
    mutation_db, monkeypatch
):
    db, _engine = mutation_db
    contact = await _seed_contact(db)
    tag = CRMTag(name="Synthetic unrelated bulk constraint")
    db.add(tag)
    await db.flush()
    original_flush = db.flush

    class PostgreSQLOrigin(Exception):
        def __init__(self):
            self.diag = type(
                "Diagnostic", (), {"constraint_name": "other_constraint"}
            )()

    async def fail_assignment_flush(*args, **kwargs):
        if any(isinstance(row, CRMContactTag) for row in db.new):
            raise IntegrityError(
                "INSERT INTO crm_contact_tags",
                {},
                PostgreSQLOrigin(),
            )
        return await original_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", fail_assignment_flush)
    with pytest.raises(IntegrityError):
        await contacts_service.apply_contact_bulk_action(
            db,
            ContactBulkCommand((contact.id,), ContactBulkAddTag("add_tag", tag.id)),
            actor_subject="7",
        )
    assert await db.scalar(select(func.count()).select_from(CRMContactTag)) == 0
    assert await db.scalar(select(func.count()).select_from(CRMContactAuditEvent)) == 0
