"""Synthetic regressions for immutable, owner-scoped note presentation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base, get_db
from middleware.auth import require_admin_subject
from models.command import CRMContact, CRMNote
from models.command_contacts import (
    CRMContactCapturePosition,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
)
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from routers import command_contacts as contact_router
from schemas.command_contacts import LegacyContactWorkspaceOut
from services.command_contact_notes import (
    ContactNoteContentError,
    read_contact_note_content,
)

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
RAW_LINES = [
    "2:16 PM",
    "Updated",
    "By Example Agent",
    "Lake open house",
    "Requested a follow-up.",
    "Delete",
    "Edit",
]
CLEAN_BODY = "Lake open house\n\nRequested a follow-up."


@pytest_asyncio.fixture
async def note_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine.sync_engine, "connect", enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@dataclass
class CapturedNote:
    note: CRMNote
    source: CRMSourceRecord
    occurrence: CRMContactSourceOccurrence
    section: CRMContactSectionCapture
    position: CRMContactCapturePosition
    link: CRMEntitySource


async def add_captured_note(
    db: AsyncSession,
    owner: CRMContact,
    index: int,
    *,
    raw_lines: list[str] | None = None,
) -> CapturedNote:
    lines = RAW_LINES if raw_lines is None else raw_lines
    sources = [
        CRMSourceRecord(
            source_system="kw_command",
            module="contacts",
            record_kind=kind,
            source_key=f"synthetic:{index}:{kind}",
            parser_version="note-read-regression-v1",
            display_label="Updated",
            evidence_level="rendered_occurrence",
            payload_json=json.dumps({"values": {"raw_lines": lines}}),
            captured_at=NOW,
            capture_quality="complete",
        )
        for kind in (
            "contact_capture_position",
            "contact_section_capture",
            "contact_note",
        )
    ]
    note = CRMNote(
        contact_id=owner.id, body="\n".join(lines), created_at=NOW, updated_at=NOW
    )
    db.add_all([*sources, note])
    await db.flush()
    position = CRMContactCapturePosition(
        contact_id=owner.id,
        source_record_id=sources[0].id,
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
        source_record_id=sources[1].id,
        section_name="notes",
        captured_at=NOW,
        capture_quality="complete",
        is_empty=False,
        row_count=1,
        limitations_json="[]",
    )
    db.add(section)
    await db.flush()
    occurrence = CRMContactSourceOccurrence(
        contact_id=owner.id,
        section_capture_id=section.id,
        source_record_id=sources[2].id,
        occurrence_ordinal=1,
    )
    link = CRMEntitySource(
        entity_type="note", entity_id=note.id, source_record_id=sources[2].id
    )
    db.add_all([occurrence, link])
    await db.flush()
    return CapturedNote(note, sources[2], occurrence, section, position, link)


async def workspace_notes(db: AsyncSession, owner: CRMContact):
    raw = await contact_router._legacy_contact_workspace(db, contact_id=owner.id)
    output = LegacyContactWorkspaceOut.model_validate(raw)
    return raw["notes"], {note.id: note for note in output.notes}


@pytest.mark.parametrize(
    "payload_json",
    (
        None,
        "not json",
        "[]",
        "null",
        "{}",
        '{"values":[]}',
        '{"values":null}',
        '{"values":{"title":"Synthetic","extra":NaN}}',
    ),
)
def test_note_reader_rejects_malformed_payload_without_private_values(payload_json):
    with pytest.raises(
        ContactNoteContentError, match="^contact occurrence payload is invalid$"
    ):
        read_contact_note_content(payload_json, display_label="Private fallback")


@pytest.mark.parametrize("suffix", ([], ["Welcome to KWIQ"], ["3/5/2026"]))
def test_note_reader_accepts_maximum_newline_body_with_optional_capture_suffix(suffix):
    raw_lines = [*RAW_LINES[:4], *([""] * 20_001), "Delete", "Edit", *suffix]

    content = read_contact_note_content(
        json.dumps({"values": {"raw_lines": raw_lines}}), display_label="Updated"
    )

    assert content.title == "Lake open house"
    assert content.body == "\n" * 20_000


@pytest.mark.parametrize(
    ("lines", "expected"),
    (
        (RAW_LINES, CLEAN_BODY),
        ([*RAW_LINES[:1], "Created", *RAW_LINES[2:]], CLEAN_BODY),
        ([*RAW_LINES[:4], "Delete", "Edit"], "Lake open house"),
        ([*RAW_LINES[:4], "Delete", "Edit", "Welcome to KWIQ"], "Lake open house"),
        ([*RAW_LINES[:4], "Delete", "Edit", "3/5/2026"], "Lake open house"),
    ),
)
async def test_workspace_note_content_cleans_only_the_response(
    note_db, lines, expected
):
    owner = CRMContact(first_name="Synthetic", last_name="Owner", stage="lead")
    note_db.add(owner)
    await note_db.flush()
    captured = await add_captured_note(note_db, owner, 1, raw_lines=lines)
    await note_db.commit()
    original_payload = captured.source.payload_json
    original_times = (captured.note.created_at, captured.note.updated_at)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(note_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        raw, notes = await workspace_notes(note_db, owner)
        await note_db.flush()
    finally:
        event.remove(note_db.bind.sync_engine, "before_cursor_execute", capture)

    assert notes[captured.note.id].body == expected
    assert isinstance(raw[0], dict)
    assert set(raw[0]) == {"id", "contact_id", "body", "created_at", "updated_at"}
    assert notes[captured.note.id].created_at == original_times[0]
    assert notes[captured.note.id].updated_at == original_times[1]
    assert not note_db.dirty
    assert all(
        statement.lstrip().upper().startswith("SELECT") for statement in statements
    )
    assert captured.note.body == "\n".join(lines)
    assert captured.source.payload_json == original_payload
    assert await note_db.scalar(
        select(CRMNote.body).where(CRMNote.id == captured.note.id)
    ) == "\n".join(lines)
    assert (
        await note_db.scalar(
            select(CRMSourceRecord.payload_json).where(
                CRMSourceRecord.id == captured.source.id
            )
        )
        == original_payload
    )


@pytest.mark.parametrize(
    "change",
    (
        "user_edit",
        "unlinked",
        "wrong_system",
        "wrong_module",
        "wrong_kind",
        "wrong_section",
        "foreign_occurrence",
        "foreign_position",
        "missing_occurrence",
        "wrong_link_type",
        "source_conflict",
        "note_conflict",
        "malformed_payload",
        "incomplete_capture",
    ),
)
async def test_workspace_note_content_preserves_unproven_and_edited_notes(
    note_db, change
):
    owner = CRMContact(first_name="Synthetic", last_name="Owner", stage="lead")
    foreign = CRMContact(first_name="Synthetic", last_name="Foreign", stage="lead")
    note_db.add_all([owner, foreign])
    await note_db.flush()
    good = await add_captured_note(note_db, owner, 1)
    disputed = await add_captured_note(note_db, owner, 2)
    foreign_note = await add_captured_note(note_db, foreign, 3)

    if change == "user_edit":
        disputed.note.body += "\nOwner added a new detail."
    elif change == "unlinked":
        await note_db.delete(disputed.link)
    elif change == "wrong_system":
        disputed.source.source_system = "other_provider"
    elif change == "wrong_module":
        disputed.source.module = "tasks"
    elif change == "wrong_kind":
        disputed.source.record_kind = "contact_task"
    elif change == "wrong_section":
        disputed.section.section_name = "tasks_to_do"
    elif change == "foreign_occurrence":
        disputed.occurrence.contact_id = foreign.id
    elif change == "foreign_position":
        disputed.position.contact_id = foreign.id
    elif change == "missing_occurrence":
        await note_db.delete(disputed.occurrence)
    elif change == "wrong_link_type":
        disputed.link.entity_type = "task"
    elif change == "source_conflict":
        note_db.add(
            CRMEntitySource(
                entity_type="task", entity_id=99, source_record_id=disputed.source.id
            )
        )
    elif change == "note_conflict":
        foreign_note.link.entity_id = disputed.note.id
    elif change == "malformed_payload":
        disputed.source.payload_json = '{"values":[]}'
    elif change == "incomplete_capture":
        lines = RAW_LINES[:-1]
        disputed.source.payload_json = json.dumps({"values": {"raw_lines": lines}})
        disputed.note.body = "\n".join(lines)
    else:
        pytest.fail(f"unsupported fixture variation: {change}")
    await note_db.commit()
    expected_disputed = disputed.note.body

    _raw, notes = await workspace_notes(note_db, owner)

    assert notes[good.note.id].body == CLEAN_BODY
    assert notes[disputed.note.id].body == expected_disputed
    assert set(notes) == {good.note.id, disputed.note.id}
    assert not note_db.dirty
    assert (
        await note_db.scalar(select(CRMNote.body).where(CRMNote.id == disputed.note.id))
        == expected_disputed
    )


@pytest.mark.parametrize(
    "raw_lines",
    (
        ["not a time", *RAW_LINES[1:]],
        [*RAW_LINES[:-2], "Edit"],
        RAW_LINES[:-1],
        [*RAW_LINES[:-1], "not a control", "Edit"],
    ),
    ids=("invalid_header", "missing_delete", "missing_edit", "split_controls"),
)
async def test_workspace_note_content_preserves_unproven_raw_capture_with_structured_fields(
    note_db, raw_lines
):
    owner = CRMContact(first_name="Synthetic", last_name="Owner", stage="lead")
    note_db.add(owner)
    await note_db.flush()
    captured = await add_captured_note(note_db, owner, 1, raw_lines=raw_lines)
    captured.source.payload_json = json.dumps(
        {
            "values": {
                "raw_lines": raw_lines,
                "title": "Structured title",
                "body": "Structured body",
            }
        }
    )
    await note_db.commit()
    original_payload = captured.source.payload_json

    _raw, notes = await workspace_notes(note_db, owner)

    assert notes[captured.note.id].body == "\n".join(raw_lines)
    assert not note_db.dirty
    assert captured.source.payload_json == original_payload
    assert await note_db.scalar(
        select(CRMNote.body).where(CRMNote.id == captured.note.id)
    ) == "\n".join(raw_lines)
    # Source projection still trusts explicit structured fields independently of raw capture.
    source_content = read_contact_note_content(
        original_payload, display_label=captured.source.display_label
    )
    assert (source_content.title, source_content.body) == (
        "Structured title",
        "Structured body",
    )


@pytest.mark.parametrize("note_count", (1, 101))
async def test_workspace_note_content_uses_one_batched_provenance_query(
    note_db, note_count
):
    owner = CRMContact(first_name="Synthetic", last_name="Owner", stage="lead")
    note_db.add(owner)
    await note_db.flush()
    captured = [
        await add_captured_note(note_db, owner, index + 1)
        for index in range(note_count)
    ]
    await note_db.commit()
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        if "crm_entity_sources" in statement:
            statements.append(statement)

    event.listen(note_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        _raw, notes = await workspace_notes(note_db, owner)
    finally:
        event.remove(note_db.bind.sync_engine, "before_cursor_execute", capture)

    assert len(statements) == 1
    assert len(notes) == note_count
    assert all(notes[item.note.id].body == CLEAN_BODY for item in captured)
    assert "crm_contact_source_occurrences" in statements[0]
    assert "crm_contact_section_captures" in statements[0]
    assert "crm_contact_capture_positions" in statements[0]


async def test_workspace_note_content_protected_route_preserves_pending_user_edit(
    note_db,
):
    owner = CRMContact(first_name="Synthetic", last_name="Owner", stage="lead")
    note_db.add(owner)
    await note_db.flush()
    clean = await add_captured_note(note_db, owner, 1)
    edited = await add_captured_note(note_db, owner, 2)
    await note_db.commit()
    edited.note.body = "A pending owner edit with Delete and Edit in its own words."
    app = FastAPI()
    app.include_router(contact_router.router)
    app.dependency_overrides[get_db] = lambda: note_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://synthetic.test"
    ) as client:
        rejected = await client.get(f"/contacts/{owner.id}/workspace")
        assert rejected.status_code == 401
        app.dependency_overrides[require_admin_subject] = lambda: "17"
        response = await client.get(f"/contacts/{owner.id}/workspace")

    assert response.status_code == 200
    notes = {row["id"]: row for row in response.json()["notes"]}
    assert notes[clean.note.id]["body"] == CLEAN_BODY
    assert notes[edited.note.id]["body"] == edited.note.body
    assert set(note_db.dirty) == {edited.note}
    with note_db.no_autoflush:
        assert await note_db.scalar(
            select(CRMNote.body).where(CRMNote.id == edited.note.id)
        ) == "\n".join(RAW_LINES)
