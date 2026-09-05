"""Lossless section queries for recovered Command contact views."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import services.command_contacts as contact_service
from database import Base
from models.command import (
    CRMContact,
    CRMNote,
    CRMOpportunity,
    CRMOpportunityContact,
    CRMSavedSearch,
    CRMSmartPlan,
    CRMSmartPlanEnrollment,
    CRMTask,
)
from models.command_contacts import (
    CRMContactCapturePosition,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
)
from models.command_provenance import CRMEntitySource, CRMSourceRecord
from services.command_contact_contracts import (
    CaptureQualityValue,
    ContactMaterialized,
    ContactNoteOccurrence,
    ContactOpportunityOccurrence,
    ContactSavedSearchOccurrence,
    ContactSection,
    ContactSmartPlanOccurrence,
    ContactSourceOnly,
    ContactTaskOccurrence,
)
from services.command_contacts import (
    ContactDataIntegrityError,
    ContactNotFound,
    ContactSectionUnsupported,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
HASH_DOMAIN = b"command.contact.section-source-key.v1\0"


@pytest_asyncio.fixture()
async def section_db(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'contact-sections.sqlite'}"
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


async def _list_section(
    db: AsyncSession,
    contact_id: int,
    section: ContactSection,
    *,
    page: int = 1,
    page_size: int = 100,
):
    function = getattr(contact_service, "list_contact_section", None)
    assert function is not None, "list_contact_section is not implemented"
    return await function(
        db,
        contact_id,
        section,
        page=page,
        page_size=page_size,
    )


def _source(
    index: int,
    *,
    kind: str,
    payload: object,
    display_label: str = "Synthetic fallback",
    captured_at: datetime | None = NOW,
) -> CRMSourceRecord:
    return CRMSourceRecord(
        source_system="kw_command",
        module="contacts",
        record_kind=kind,
        source_key=f"private:synthetic:section:{index}",
        evidence_level="rendered_occurrence",
        display_label=display_label,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        capture_quality="complete",
        captured_at=captured_at,
        parser_version="contacts-section-test-v1",
    )


async def _add_occurrence(
    db: AsyncSession,
    contact: CRMContact,
    index: int,
    *,
    section: ContactSection,
    values: dict[str, object],
    captured_at: datetime | None = NOW,
    capture_ordinal: int | None = None,
    occurrence_ordinal: int = 1,
    display_label: str = "Synthetic fallback",
    occurrence_contact: CRMContact | None = None,
    position_contact: CRMContact | None = None,
    linked_entity: tuple[str, int] | None = None,
) -> tuple[CRMContactSourceOccurrence, CRMSourceRecord]:
    record_kind = {
        ContactSection.OPPORTUNITIES: "contact_opportunity",
        ContactSection.SMART_PLANS: "contact_smart_plan",
        ContactSection.NOTES: "contact_note",
        ContactSection.SAVED_SEARCHES: "contact_saved_search",
        ContactSection.TASKS_TO_DO: "contact_task",
        ContactSection.TASKS_COMPLETED: "contact_task",
        ContactSection.TASKS_ARCHIVED: "contact_task",
    }[section]
    ordinal = capture_ordinal or index
    position_source = _source(
        index * 10,
        kind="contact_capture_position",
        payload={"capture_ordinal": ordinal},
    )
    section_source = _source(
        index * 10 + 1,
        kind="contact_section_capture",
        payload={"section_name": section.value},
    )
    child_source = _source(
        index * 10 + 2,
        kind=record_kind,
        payload={"values": values},
        display_label=display_label,
        captured_at=captured_at,
    )
    db.add_all([position_source, section_source, child_source])
    await db.flush()
    owner = position_contact or contact
    position = CRMContactCapturePosition(
        contact_id=owner.id,
        source_record_id=position_source.id,
        bundle_fingerprint=f"{index:064x}",
        capture_ordinal=ordinal,
        source_contact_id=f"{index:024x}",
        captured_at=captured_at,
        capture_quality="complete",
        limitations_json="[]",
    )
    db.add(position)
    await db.flush()
    capture = CRMContactSectionCapture(
        capture_position_id=position.id,
        source_record_id=section_source.id,
        section_name=section.value,
        captured_at=captured_at,
        capture_quality="complete",
        is_empty=False,
        row_count=1,
        limitations_json="[]",
    )
    db.add(capture)
    await db.flush()
    occurrence = CRMContactSourceOccurrence(
        contact_id=(occurrence_contact or contact).id,
        section_capture_id=capture.id,
        source_record_id=child_source.id,
        occurrence_ordinal=occurrence_ordinal,
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
    return occurrence, child_source


@pytest.mark.parametrize("action", ("Created", "Updated"))
def test_recovered_note_content_uses_captured_title_and_body(action):
    source = _source(
        1,
        kind="contact_note",
        display_label="Updated" if action == "Updated" else "Lake open house",
        payload={
            "values": {
                "raw_lines": [
                    "2:16 PM",
                    action,
                    "By Example Agent",
                    "Lake open house",
                    "Requested a follow-up.",
                    "Delete",
                    "Edit",
                ]
            }
        },
    )
    original_payload = source.payload_json

    note = contact_service._project_section_occurrence(source, ContactSection.NOTES)

    assert note == ContactNoteOccurrence(
        kind="note", title="Lake open house", body="Requested a follow-up."
    )
    assert source.payload_json == original_payload
    assert source.display_label == (
        "Updated" if action == "Updated" else "Lake open house"
    )


@pytest.mark.parametrize("suffix", ([], ["Welcome to KWIQ"], ["3/5/2026"]))
def test_recovered_note_content_proves_title_only_without_uncaptured_fallback(suffix):
    source = _source(
        1,
        kind="contact_note",
        payload={
            "values": {
                "raw_lines": [
                    "2:16 PM",
                    "Created",
                    "By Example Agent",
                    "Call back",
                    "Delete",
                    "Edit",
                    *suffix,
                ]
            }
        },
    )

    note = contact_service._project_section_occurrence(source, ContactSection.NOTES)

    assert note == ContactNoteOccurrence(kind="note", title="Call back", body="")


def test_recovered_note_content_preserves_multiline_unicode_and_control_words():
    body_lines = [
        "  Zoë’s café — requested a follow-up.  ",
        "",
        "Created",
        "By Example Agent",
        "Delete",
        "Edit",
        "Welcome to KWIQ",
        "3/5/2026",
        "Line one\nLine two\n",
    ]
    source = _source(
        1,
        kind="contact_note",
        payload={
            "values": {
                "raw_lines": [
                    "2:16 PM",
                    "Updated",
                    "By Example Agent",
                    "  Café notes  ",
                    *body_lines,
                    "Delete",
                    "Edit",
                ]
            }
        },
    )

    note = contact_service._project_section_occurrence(source, ContactSection.NOTES)

    assert note.title == "  Café notes  "
    assert note.body == "\n".join(body_lines)


@pytest.mark.parametrize(
    "raw_lines",
    (
        None,
        "2:16 PM\nCreated\nBy Example Agent\nPrivate title\nDelete\nEdit",
        [],
        ["Private title", "Delete", "Edit"],
        ["2:16 PM", "Created", "Private title", "Delete", "Edit"],
        ["2:16 PM", "Created", "By ", "Private title", "Delete", "Edit"],
        ["25:61 PM", "Created", "By Agent", "Private title", "Delete", "Edit"],
        ["2:16 PM", "Created", "By Agent", "Private title", "Delete"],
        ["2:16 PM", "Created", "By Agent", "Private title", "Edit"],
        ["2:16 PM", "Created", "By Agent", "Private title", "Edit", "Delete"],
        ["2:16 PM", "Created", "By Agent", "Private title", "Delete", "gap", "Edit"],
        [
            "2:16 PM",
            "Created",
            "By Agent",
            "Private title",
            "Delete",
            "Edit",
            "private unknown tail",
        ],
        [
            "2:16 PM",
            "Created",
            "By Agent",
            "Private title",
            "Delete",
            "Edit",
            "2/30/2026",
        ],
        ["2:16 PM", "Created", "By Agent", "Private title", None, "Delete", "Edit"],
        ["2:16 PM", "Created", "By Agent", "", "Delete", "Edit"],
        ["2:16 PM", "Created", "By Agent", "x" * 501, "Delete", "Edit"],
        [
            "2:16 PM",
            "Created",
            "By Agent",
            "Private title",
            "x" * 20_001,
            "Delete",
            "Edit",
        ],
        [
            "2:16 PM",
            "Created",
            "By Agent",
            "Private title",
            *([""] * 20_002),
            "Delete",
            "Edit",
        ],
    ),
)
def test_recovered_note_content_rejects_malformed_or_unbounded_capture(raw_lines):
    source = _source(
        1,
        kind="contact_note",
        payload={"values": {"raw_lines": raw_lines}},
        display_label="Private fallback must not hide malformed evidence",
    )

    with pytest.raises(
        ContactDataIntegrityError, match="^contact occurrence payload is invalid$"
    ):
        contact_service._project_section_occurrence(source, ContactSection.NOTES)


def test_recovered_note_content_accepts_exact_title_and_body_bounds():
    source = _source(
        1,
        kind="contact_note",
        payload={
            "values": {
                "raw_lines": [
                    "2:16 PM",
                    "Created",
                    "By Agent",
                    "t" * 500,
                    "b" * 20_000,
                    "Delete",
                    "Edit",
                ]
            }
        },
    )

    note = contact_service._project_section_occurrence(source, ContactSection.NOTES)

    assert note.title == "t" * 500
    assert note.body == "b" * 20_000


@pytest.mark.parametrize("body", ("Structured\nbody", "", None))
def test_recovered_note_content_preserves_explicit_structured_fields(body):
    source = _source(
        1,
        kind="contact_note",
        payload={
            "values": {
                "title": "Structured title",
                "body": body,
                "raw_lines": [
                    "malformed legacy data must not override explicit fields"
                ],
            }
        },
    )

    note = contact_service._project_section_occurrence(source, ContactSection.NOTES)

    assert note == ContactNoteOccurrence(
        kind="note", title="Structured title", body=body
    )


@pytest.mark.parametrize(
    ("structured", "expected_title", "expected_body"),
    (
        ({"title": "Structured title"}, "Structured title", "Captured body"),
        ({"body": "Structured body"}, "Captured title", "Structured body"),
        ({"body": ""}, "Captured title", ""),
        ({"body": None}, "Captured title", None),
    ),
)
def test_recovered_note_content_prefers_each_explicit_field(
    structured, expected_title, expected_body
):
    source = _source(
        1,
        kind="contact_note",
        payload={
            "values": {
                "raw_lines": [
                    "2:16 PM",
                    "Updated",
                    "By Agent",
                    "Captured title",
                    "Captured body",
                    "Delete",
                    "Edit",
                ],
                **structured,
            }
        },
    )

    note = contact_service._project_section_occurrence(source, ContactSection.NOTES)

    assert (note.title, note.body) == (expected_title, expected_body)


@pytest.mark.asyncio
async def test_recovered_note_content_reaches_materialized_section_without_writes(
    section_db: AsyncSession,
):
    contact = CRMContact(first_name="Synthetic", last_name="Owner", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    raw_lines = [
        "2:16 PM",
        "Updated",
        "By Example Agent",
        "Lake open house",
        "Requested a follow-up.",
        "Delete",
        "Edit",
    ]
    stored_note = CRMNote(contact_id=contact.id, body="\n".join(raw_lines))
    section_db.add(stored_note)
    await section_db.flush()
    _occurrence, source = await _add_occurrence(
        section_db,
        contact,
        91_001,
        section=ContactSection.NOTES,
        values={"raw_lines": raw_lines},
        display_label="Updated",
        linked_entity=("note", stored_note.id),
    )
    await section_db.commit()
    original_payload = source.payload_json
    original_updated_at = stored_note.updated_at

    page = await _list_section(section_db, contact.id, ContactSection.NOTES)

    assert page.rows[0].value == ContactNoteOccurrence(
        kind="note", title="Lake open house", body="Requested a follow-up."
    )
    assert page.rows[0].entity_id == stored_note.id
    assert not section_db.dirty
    assert stored_note.body == "\n".join(raw_lines)
    assert stored_note.updated_at == original_updated_at
    assert source.payload_json == original_payload


@pytest.mark.asyncio
async def test_timeline_rejects_before_sql_and_boundaries_are_safe(
    section_db: AsyncSession,
):
    selects = 0

    def capture(_connection, _cursor, statement, _params, _context, _many):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    assert section_db.bind is not None
    event.listen(section_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(ContactSectionUnsupported):
            await _list_section(section_db, 999_999, ContactSection.TIMELINE)
    finally:
        event.remove(section_db.bind.sync_engine, "before_cursor_execute", capture)
    assert selects == 0

    with pytest.raises(ContactNotFound, match="contact does not exist"):
        await _list_section(
            section_db, 999_999, ContactSection.NOTES, page=1, page_size=1
        )
    contact = CRMContact(first_name="Bounds", last_name="Owner", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    for page, page_size in ((0, 1), (True, 1), (1, 0), (1, 101), (1, True)):
        selects = 0
        event.listen(section_db.bind.sync_engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(ValueError):
                await _list_section(
                    section_db,
                    contact.id,
                    ContactSection.NOTES,
                    page=page,
                    page_size=page_size,
                )
        finally:
            event.remove(section_db.bind.sync_engine, "before_cursor_execute", capture)
        assert selects == 0


@pytest.mark.asyncio
async def test_all_seven_sections_project_only_typed_whitelisted_values(
    section_db: AsyncSession,
):
    contact = CRMContact(first_name="Typed", last_name="Views", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    specs: tuple[tuple[ContactSection, dict[str, object], object], ...] = (
        (
            ContactSection.OPPORTUNITIES,
            {
                "title": "  Exact opportunity  ",
                "stage": "  cultivate  ",
                "value_cents": 123_456,
                "budget": "$9m private",
            },
            ContactOpportunityOccurrence(
                kind="opportunity",
                title="Exact opportunity",
                stage="cultivate",
                value_cents=123_456,
            ),
        ),
        (
            ContactSection.SMART_PLANS,
            {"name": "  Exact plan  ", "status": "  Active  ", "steps": [1]},
            ContactSmartPlanOccurrence(
                kind="smart_plan", title="Exact plan", status="Active"
            ),
        ),
        (
            ContactSection.NOTES,
            {
                "title": "  Exact note  ",
                "body": "  Explicit body  ",
                "raw_lines": ["private raw line"],
            },
            ContactNoteOccurrence(
                kind="note", title="Exact note", body="Explicit body"
            ),
        ),
        (
            ContactSection.SAVED_SEARCHES,
            {
                "name": "  Exact search  ",
                "price": "  500000  ",
                "beds": 3,
                "baths": 2,
                "created_by": "private actor",
                "unknown": "private field",
            },
            ContactSavedSearchOccurrence(
                kind="saved_search",
                title="Exact search",
                criteria_summary=("Price: 500000", "Beds: 3", "Baths: 2"),
            ),
        ),
        (
            ContactSection.TASKS_TO_DO,
            {
                "title": "  Exact task  ",
                "description": "  Explicit description  ",
                "due_at": "2026-08-13T08:15:30-04:00",
                "due_date": "Tomorrow private",
            },
            ContactTaskOccurrence(
                kind="task",
                title="Exact task",
                description="Explicit description",
                state="to_do",
                due_at=NOW.replace(minute=15, second=30),
            ),
        ),
        (
            ContactSection.TASKS_COMPLETED,
            {"title": "Completed task", "due_at": "2026-08-13"},
            ContactTaskOccurrence(
                kind="task",
                title="Completed task",
                description=None,
                state="completed",
                due_at=None,
            ),
        ),
        (
            ContactSection.TASKS_ARCHIVED,
            {"title": "Archived task", "due_at": "not a timestamp"},
            ContactTaskOccurrence(
                kind="task",
                title="Archived task",
                description=None,
                state="archived",
                due_at=None,
            ),
        ),
    )
    sources: dict[ContactSection, CRMSourceRecord] = {}
    for index, (section, values, _expected) in enumerate(specs, 1):
        _occurrence, source = await _add_occurrence(
            section_db,
            contact,
            10_000 + index,
            section=section,
            values=values,
        )
        sources[section] = source

    for section, _values, expected in specs:
        page = await _list_section(section_db, contact.id, section)
        source = sources[section]
        expected_hash = hashlib.sha256(
            HASH_DOMAIN + source.source_key.encode("utf-8")
        ).hexdigest()
        assert page.total == 1
        assert page.page_count == 1
        assert page.rows == (
            ContactSourceOnly(
                status="source_only",
                source_record_id=source.id,
                source_key_hash=expected_hash,
                section=section,
                occurrence_ordinal=1,
                capture_quality=CaptureQualityValue.COMPLETE,
                captured_at=NOW,
                value=expected,  # type: ignore[arg-type]
            ),
        )
        rendered = repr(page)
        assert source.source_key not in rendered
        for private_value in (
            "$9m private",
            "private raw line",
            "private actor",
            "private field",
            "Tomorrow private",
        ):
            assert private_value not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_value",
    (True, "500000", 12.5, -1),
)
async def test_opportunity_never_infers_or_parses_value_cents(
    section_db: AsyncSession,
    unsafe_value: object,
):
    contact = CRMContact(first_name="Conservative", last_name="Value", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    await _add_occurrence(
        section_db,
        contact,
        20_001,
        section=ContactSection.OPPORTUNITIES,
        values={"title": "Exact", "value_cents": unsafe_value, "budget": 999},
    )
    page = await _list_section(section_db, contact.id, ContactSection.OPPORTUNITIES)
    assert page.rows[0].value.value_cents is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_titles_fallback_and_saved_search_criteria_omit_unsafe_values(
    section_db: AsyncSession,
):
    contact = CRMContact(first_name="Safe", last_name="Fallback", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    await _add_occurrence(
        section_db,
        contact,
        21_001,
        section=ContactSection.SAVED_SEARCHES,
        values={
            "name": None,
            "price": "x" * 121,
            "beds": True,
            "baths": {"minimum": 2},
        },
        display_label="  Safe fallback  ",
    )
    page = await _list_section(section_db, contact.id, ContactSection.SAVED_SEARCHES)
    assert page.rows[0].value == ContactSavedSearchOccurrence(
        kind="saved_search",
        title="Safe fallback",
        criteria_summary=(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("section", "values"),
    (
        (ContactSection.NOTES, {}),
        (ContactSection.NOTES, {"title": "x" * 501}),
        (ContactSection.NOTES, {"title": "note", "body": "x" * 20_001}),
        (
            ContactSection.SMART_PLANS,
            {"name": "plan", "status": "x" * 121},
        ),
    ),
)
async def test_section_projection_rejects_missing_or_overbound_text(
    section_db: AsyncSession,
    section: ContactSection,
    values: dict[str, object],
):
    contact = CRMContact(first_name="Invalid", last_name="Text", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    await _add_occurrence(
        section_db,
        contact,
        22_001,
        section=section,
        values=values,
        display_label="   " if not values else "Synthetic fallback",
    )
    with pytest.raises(ContactDataIntegrityError) as error:
        await _list_section(section_db, contact.id, section)
    assert "x" * 50 not in str(error.value)


@pytest.mark.asyncio
async def test_section_projection_rejects_an_overbound_fallback_label(
    section_db: AsyncSession,
):
    contact = CRMContact(first_name="Invalid", last_name="Fallback", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    await _add_occurrence(
        section_db,
        contact,
        22_002,
        section=ContactSection.NOTES,
        values={},
        display_label="x" * 501,
    )

    with pytest.raises(
        ContactDataIntegrityError,
        match="contact occurrence payload is invalid",
    ) as error:
        await _list_section(section_db, contact.id, ContactSection.NOTES)
    assert "x" * 50 not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_due_at", "expected"),
    (
        ("2026-08-13T12:00:00Z", NOW),
        ("2026-08-13t08:00:00-04:00", NOW),
        ("2026-08-13T12:00:00.123456+00:00", NOW.replace(microsecond=123456)),
        ("2026-08-13T12:00:00", None),
        ("2026-08-13", None),
        ("Tomorrow", None),
        ("9999-12-31T23:59:59-23:59", None),
        ("0001-01-01T00:00:00+23:59", None),
        (1_786_622_400, None),
        (True, None),
    ),
)
async def test_task_due_at_accepts_only_explicit_valid_rfc3339_datetimes(
    section_db: AsyncSession,
    raw_due_at: object,
    expected: datetime | None,
):
    contact = CRMContact(first_name="Due", last_name="Timestamp", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    await _add_occurrence(
        section_db,
        contact,
        22_100,
        section=ContactSection.TASKS_TO_DO,
        values={"title": "Exact task", "due_at": raw_due_at},
    )

    page = await _list_section(section_db, contact.id, ContactSection.TASKS_TO_DO)
    assert page.rows[0].value.due_at == expected  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_optional_projected_fields_never_coerce_wrong_typed_values(
    section_db: AsyncSession,
):
    contact = CRMContact(first_name="No", last_name="Coercion", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    specs: tuple[tuple[ContactSection, dict[str, object]], ...] = (
        (ContactSection.OPPORTUNITIES, {"title": "Opp", "stage": 7}),
        (ContactSection.SMART_PLANS, {"name": "Plan", "status": ["active"]}),
        (ContactSection.NOTES, {"title": "Note", "body": {"raw": "secret"}}),
        (
            ContactSection.TASKS_TO_DO,
            {"title": "Task", "description": ["secret"]},
        ),
    )
    for index, (section, values) in enumerate(specs):
        await _add_occurrence(
            section_db,
            contact,
            22_200 + index,
            section=section,
            values=values,
        )

    opportunity = await _list_section(
        section_db, contact.id, ContactSection.OPPORTUNITIES
    )
    smart_plan = await _list_section(section_db, contact.id, ContactSection.SMART_PLANS)
    note = await _list_section(section_db, contact.id, ContactSection.NOTES)
    task = await _list_section(section_db, contact.id, ContactSection.TASKS_TO_DO)
    assert opportunity.rows[0].value.stage is None  # type: ignore[union-attr]
    assert smart_plan.rows[0].value.status is None  # type: ignore[union-attr]
    assert note.rows[0].value.body is None  # type: ignore[union-attr]
    assert task.rows[0].value.description is None  # type: ignore[union-attr]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload_json",
    (
        "{",
        "[]",
        "null",
        "7",
        "{}",
        '{"values":null}',
        '{"values":[]}',
        '{"values":"not-an-object"}',
    ),
)
async def test_source_only_projection_rejects_every_non_object_payload_shape(
    section_db: AsyncSession,
    payload_json: str,
):
    contact = CRMContact(first_name="Strict", last_name="Source", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    _occurrence, source = await _add_occurrence(
        section_db,
        contact,
        23_001,
        section=ContactSection.NOTES,
        values={"title": "Private planted title"},
    )
    source.payload_json = payload_json
    await section_db.flush()

    with pytest.raises(
        ContactDataIntegrityError,
        match="contact occurrence payload is invalid",
    ) as error:
        await _list_section(section_db, contact.id, ContactSection.NOTES)
    assert "Private planted title" not in str(error.value)


@pytest.mark.asyncio
async def test_materialized_projection_uses_the_same_strict_payload_validator(
    section_db: AsyncSession,
):
    contact = CRMContact(first_name="Strict", last_name="Linked", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    entity_type, entity_id = await _materialized_target(
        section_db, contact, ContactSection.NOTES, 23_002
    )
    _occurrence, source = await _add_occurrence(
        section_db,
        contact,
        23_002,
        section=ContactSection.NOTES,
        values={"title": "Private linked title"},
        linked_entity=(entity_type, entity_id),
    )
    source.payload_json = '{"values":[]}'
    await section_db.flush()

    with pytest.raises(
        ContactDataIntegrityError,
        match="contact occurrence payload is invalid",
    ) as error:
        await _list_section(section_db, contact.id, ContactSection.NOTES)
    assert "Private linked title" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("nonfinite", ("NaN", "Infinity", "-Infinity"))
@pytest.mark.parametrize("materialized", (False, True))
async def test_section_projection_rejects_nonfinite_json_constants_everywhere(
    section_db: AsyncSession,
    nonfinite: str,
    materialized: bool,
):
    contact = CRMContact(first_name="Finite", last_name="Only", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    linked_entity = None
    if materialized:
        linked_entity = await _materialized_target(
            section_db, contact, ContactSection.NOTES, 23_003
        )
    _occurrence, source = await _add_occurrence(
        section_db,
        contact,
        23_003,
        section=ContactSection.NOTES,
        values={"title": "Private nonfinite title"},
        linked_entity=linked_entity,
    )
    source.payload_json = (
        '{"private_nested":{"unsafe":'
        + nonfinite
        + '},"values":{"title":"Safe label"}}'
    )
    await section_db.flush()

    with pytest.raises(
        ContactDataIntegrityError,
        match="contact occurrence payload is invalid",
    ) as error:
        await _list_section(section_db, contact.id, ContactSection.NOTES)
    rendered = str(error.value)
    assert nonfinite not in rendered
    assert "Private nonfinite title" not in rendered


async def _materialized_target(
    db: AsyncSession,
    contact: CRMContact,
    section: ContactSection,
    index: int,
) -> tuple[str, int]:
    if section in {
        ContactSection.TASKS_TO_DO,
        ContactSection.TASKS_COMPLETED,
        ContactSection.TASKS_ARCHIVED,
    }:
        row = CRMTask(contact_id=contact.id, title="Synthetic task", status="open")
        entity_type = "task"
    elif section is ContactSection.NOTES:
        row = CRMNote(contact_id=contact.id, body="Synthetic note")
        entity_type = "note"
    elif section is ContactSection.SAVED_SEARCHES:
        row = CRMSavedSearch(contact_id=contact.id, name="Synthetic search")
        entity_type = "saved_search"
    elif section is ContactSection.SMART_PLANS:
        plan = CRMSmartPlan(name=f"Synthetic plan {index}", status="active")
        db.add(plan)
        await db.flush()
        row = CRMSmartPlanEnrollment(
            contact_id=contact.id, smart_plan_id=plan.id, status="active"
        )
        entity_type = "smart_plan"
    else:
        row = CRMOpportunity(name=f"Synthetic opportunity {index}")
        db.add(row)
        await db.flush()
        db.add(
            CRMOpportunityContact(
                contact_id=contact.id,
                opportunity_id=row.id,
                role="client",
            )
        )
        entity_type = "opportunity"
    db.add(row)
    await db.flush()
    return entity_type, row.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "section",
    tuple(value for value in ContactSection if value is not ContactSection.TIMELINE),
)
async def test_every_section_materializes_only_one_same_contact_target(
    section_db: AsyncSession,
    section: ContactSection,
):
    contact = CRMContact(first_name="Linked", last_name="Owner", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    entity_type, entity_id = await _materialized_target(
        section_db, contact, section, 30_001
    )
    title_key = (
        "name"
        if section
        in {
            ContactSection.SMART_PLANS,
            ContactSection.SAVED_SEARCHES,
        }
        else "title"
    )
    _occurrence, source = await _add_occurrence(
        section_db,
        contact,
        30_001,
        section=section,
        values={title_key: "Materialized row"},
        linked_entity=(entity_type, entity_id),
    )
    page = await _list_section(section_db, contact.id, section)
    assert len(page.rows) == 1
    row = page.rows[0]
    assert isinstance(row, ContactMaterialized)
    assert (row.entity_type, row.entity_id) == (entity_type, entity_id)
    assert source.source_key not in repr(row)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ("wrong_type", "dangling", "multiple"))
async def test_section_links_fail_closed_without_private_values(
    section_db: AsyncSession,
    failure: str,
):
    contact = CRMContact(first_name="Invalid", last_name="Link", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    task = CRMTask(contact_id=contact.id, title="Synthetic task", status="open")
    section_db.add(task)
    await section_db.flush()
    occurrence, source = await _add_occurrence(
        section_db,
        contact,
        31_001,
        section=ContactSection.TASKS_TO_DO,
        values={"title": "Private planted title"},
    )
    if failure == "wrong_type":
        links = [
            CRMEntitySource(
                entity_type="note",
                entity_id=task.id,
                source_record_id=source.id,
            )
        ]
    elif failure == "dangling":
        links = [
            CRMEntitySource(
                entity_type="task",
                entity_id=999_999,
                source_record_id=source.id,
            )
        ]
    else:
        links = [
            CRMEntitySource(
                entity_type="task",
                entity_id=task.id,
                source_record_id=source.id,
            ),
            CRMEntitySource(
                entity_type="note",
                entity_id=999_999,
                source_record_id=source.id,
            ),
        ]
    section_db.add_all(links)
    await section_db.flush()

    with pytest.raises(ContactDataIntegrityError) as error:
        await _list_section(section_db, contact.id, ContactSection.TASKS_TO_DO)
    rendered = str(error.value)
    assert source.source_key not in rendered
    assert "Private planted title" not in rendered
    assert str(occurrence.id) not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ("occurrence", "position", "source"))
async def test_section_context_mismatches_fail_closed(
    section_db: AsyncSession,
    mismatch: str,
):
    requested = CRMContact(first_name="Requested", last_name="Owner", stage="lead")
    other = CRMContact(first_name="Other", last_name="Owner", stage="lead")
    section_db.add_all([requested, other])
    await section_db.flush()
    occurrence, source = await _add_occurrence(
        section_db,
        requested,
        32_001,
        section=ContactSection.NOTES,
        values={"title": "Synthetic note"},
        occurrence_contact=other if mismatch == "occurrence" else requested,
        position_contact=other if mismatch == "position" else requested,
    )
    if mismatch == "source":
        source.module = "synthetic_wrong_module"
        await section_db.flush()
    with pytest.raises(ContactDataIntegrityError):
        await _list_section(section_db, requested.id, ContactSection.NOTES)
    assert occurrence.source_record_id == source.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mismatch", "replacement"),
    (
        ("section", "saved_searches"),
        ("system", "synthetic_wrong_system"),
        ("module", "synthetic_wrong_module"),
        ("kind", "contact_task"),
        ("quality", "synthetic_wrong_quality"),
    ),
)
async def test_section_domain_and_capture_quality_mismatches_fail_closed(
    section_db: AsyncSession,
    mismatch: str,
    replacement: str,
):
    contact = CRMContact(first_name="Domain", last_name="Mismatch", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    occurrence, source = await _add_occurrence(
        section_db,
        contact,
        32_101,
        section=ContactSection.NOTES,
        values={"title": "Private mismatch note"},
    )
    capture = await section_db.get(
        CRMContactSectionCapture, occurrence.section_capture_id
    )
    assert capture is not None
    if mismatch == "section":
        capture.section_name = replacement
    elif mismatch == "system":
        source.source_system = replacement
    elif mismatch == "module":
        source.module = replacement
    elif mismatch == "kind":
        source.record_kind = replacement
    else:
        await section_db.flush()
        connection = await section_db.connection()
        await connection.exec_driver_sql("PRAGMA ignore_check_constraints=ON")
        try:
            await connection.execute(
                text(
                    "UPDATE crm_contact_section_captures "
                    "SET capture_quality = :quality WHERE id = :capture_id"
                ),
                {"quality": replacement, "capture_id": capture.id},
            )
        finally:
            await connection.exec_driver_sql("PRAGMA ignore_check_constraints=OFF")
    if mismatch != "quality":
        await section_db.flush()

    with pytest.raises(ContactDataIntegrityError) as error:
        await _list_section(section_db, contact.id, ContactSection.NOTES)
    assert "Private mismatch note" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quality", "expected"),
    tuple((quality.value, quality) for quality in CaptureQualityValue),
)
async def test_section_rows_preserve_all_four_capture_qualities(
    section_db: AsyncSession,
    quality: str,
    expected: CaptureQualityValue,
):
    contact = CRMContact(first_name="Quality", last_name=quality, stage="lead")
    section_db.add(contact)
    await section_db.flush()
    occurrence, _source_record = await _add_occurrence(
        section_db,
        contact,
        32_201,
        section=ContactSection.NOTES,
        values={"title": "Quality note"},
    )
    capture = await section_db.get(
        CRMContactSectionCapture, occurrence.section_capture_id
    )
    assert capture is not None
    capture.capture_quality = quality
    await section_db.flush()

    page = await _list_section(section_db, contact.id, ContactSection.NOTES)
    assert page.rows[0].capture_quality is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "section",
    tuple(value for value in ContactSection if value is not ContactSection.TIMELINE),
)
@pytest.mark.parametrize("direction", ("target_owned_by_other", "reverse_link"))
async def test_section_target_ownership_never_crosses_contacts(
    section_db: AsyncSession,
    section: ContactSection,
    direction: str,
):
    requested = CRMContact(first_name="Requested", last_name="Target", stage="lead")
    other = CRMContact(first_name="Other", last_name="Target", stage="lead")
    section_db.add_all([requested, other])
    await section_db.flush()
    target_owner = other if direction == "target_owned_by_other" else requested
    entity_type, entity_id = await _materialized_target(
        section_db, target_owner, section, 33_001
    )
    occurrence_owner = requested if direction == "target_owned_by_other" else other
    title_key = (
        "name"
        if section in {ContactSection.SMART_PLANS, ContactSection.SAVED_SEARCHES}
        else "title"
    )
    _occurrence, source = await _add_occurrence(
        section_db,
        occurrence_owner,
        33_001,
        section=section,
        values={title_key: "Private cross-contact row"},
        linked_entity=(entity_type, entity_id),
    )

    with pytest.raises(ContactDataIntegrityError) as error:
        await _list_section(section_db, requested.id, section)
    assert source.source_key not in str(error.value)
    assert "Private cross-contact row" not in str(error.value)


@pytest.mark.asyncio
async def test_requested_target_linked_from_another_section_fails_closed(
    section_db: AsyncSession,
):
    requested = CRMContact(first_name="Requested", last_name="Task", stage="lead")
    other = CRMContact(first_name="Other", last_name="Note", stage="lead")
    section_db.add_all([requested, other])
    await section_db.flush()
    task = CRMTask(contact_id=requested.id, title="Requested task", status="open")
    section_db.add(task)
    await section_db.flush()
    _occurrence, source = await _add_occurrence(
        section_db,
        other,
        33_101,
        section=ContactSection.NOTES,
        values={"title": "Private cross-section source"},
        linked_entity=("task", task.id),
    )

    with pytest.raises(ContactDataIntegrityError) as error:
        await _list_section(section_db, requested.id, ContactSection.TASKS_TO_DO)
    assert source.source_key not in str(error.value)
    assert "Private cross-section source" not in str(error.value)


@pytest.mark.asyncio
async def test_section_row_uses_section_capture_quality_and_time_not_child_source(
    section_db: AsyncSession,
):
    contact = CRMContact(first_name="Capture", last_name="Authority", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    occurrence, source = await _add_occurrence(
        section_db,
        contact,
        34_001,
        section=ContactSection.NOTES,
        values={"title": "Synthetic capture"},
    )
    capture = await section_db.get(
        CRMContactSectionCapture, occurrence.section_capture_id
    )
    assert capture is not None
    authoritative_time = NOW - timedelta(days=2)
    capture.capture_quality = "partial"
    capture.captured_at = authoritative_time
    source.capture_quality = "error"
    source.captured_at = NOW + timedelta(days=2)
    await section_db.flush()

    page = await _list_section(section_db, contact.id, ContactSection.NOTES)
    assert page.rows[0].capture_quality is CaptureQualityValue.PARTIAL
    assert page.rows[0].captured_at == authoritative_time


@pytest.mark.asyncio
async def test_page_two_does_not_hydrate_or_validate_page_one_targets(
    section_db: AsyncSession,
):
    requested = CRMContact(first_name="Paged", last_name="Owner", stage="lead")
    section_db.add(requested)
    await section_db.flush()
    page_one_id = 70_001
    page_two_id = 70_002
    section_db.add_all(
        [
            CRMNote(
                id=page_one_id,
                contact_id=requested.id,
                body="Valid off-page target",
            ),
            CRMNote(
                id=page_two_id,
                contact_id=requested.id,
                body="Valid requested-page target",
            ),
        ]
    )
    await section_db.flush()
    await _add_occurrence(
        section_db,
        requested,
        35_001,
        section=ContactSection.NOTES,
        values={"title": "Off-page valid target"},
        captured_at=NOW,
        linked_entity=("note", page_one_id),
    )
    await _add_occurrence(
        section_db,
        requested,
        35_002,
        section=ContactSection.NOTES,
        values={"title": "Requested page target"},
        captured_at=NOW - timedelta(days=1),
        linked_entity=("note", page_two_id),
    )
    bound_parameters: list[object] = []

    def capture(_connection, _cursor, _statement, params, _context, _many):
        bound_parameters.append(params)

    assert section_db.bind is not None
    event.listen(section_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        page = await _list_section(
            section_db,
            requested.id,
            ContactSection.NOTES,
            page=2,
            page_size=1,
        )
    finally:
        event.remove(section_db.bind.sync_engine, "before_cursor_execute", capture)
    assert page.total == 2
    assert len(page.rows) == 1
    row = page.rows[0]
    assert isinstance(row, ContactMaterialized)
    assert row.entity_type == "note"
    assert row.entity_id == page_two_id
    assert row.value.title == "Requested page target"
    assert str(page_one_id) not in repr(bound_parameters)


@pytest.mark.asyncio
async def test_section_order_pagination_and_query_count_are_deterministic(
    section_db: AsyncSession,
):
    one = CRMContact(first_name="One", last_name="Occurrence", stage="lead")
    many = CRMContact(first_name="Many", last_name="Occurrences", stage="lead")
    section_db.add_all([one, many])
    await section_db.flush()
    await _add_occurrence(
        section_db,
        one,
        40_001,
        section=ContactSection.NOTES,
        values={"title": "only"},
    )
    for offset in reversed(range(101)):
        captured_at = None if offset == 100 else NOW - timedelta(days=offset // 2)
        await _add_occurrence(
            section_db,
            many,
            41_000 + offset,
            section=ContactSection.NOTES,
            values={"title": f"note {offset}"},
            captured_at=captured_at,
            capture_ordinal=offset + 1,
            occurrence_ordinal=1,
        )
    pending = CRMContact(first_name="Pending", last_name="No Flush", stage="lead")
    section_db.add(pending)

    async def measured(contact_id: int, page_size: int):
        selects = 0
        dml = 0

        def capture(_connection, _cursor, statement, _params, _context, _many):
            nonlocal selects, dml
            verb = statement.lstrip().split(None, 1)[0].upper()
            if verb == "SELECT":
                selects += 1
            elif verb in {"INSERT", "UPDATE", "DELETE"}:
                dml += 1

        assert section_db.bind is not None
        event.listen(section_db.bind.sync_engine, "before_cursor_execute", capture)
        try:
            result = await _list_section(
                section_db,
                contact_id,
                ContactSection.NOTES,
                page=1,
                page_size=page_size,
            )
        finally:
            event.remove(section_db.bind.sync_engine, "before_cursor_execute", capture)
        return result, selects, dml

    one_page, one_selects, one_dml = await measured(one.id, 1)
    many_page, many_selects, many_dml = await measured(many.id, 100)
    assert one_page.total == 1
    assert many_page.total == 101
    assert many_page.page_count == 2
    assert len(many_page.rows) == 100
    assert many_page.rows[0].value.title == "note 0"  # type: ignore[union-attr]
    assert many_page.rows[1].value.title == "note 1"  # type: ignore[union-attr]
    assert many_page.rows[-1].captured_at is not None
    terminal = await _list_section(
        section_db,
        many.id,
        ContactSection.NOTES,
        page=2,
        page_size=100,
    )
    assert len(terminal.rows) == 1
    assert terminal.rows[0].captured_at is None
    assert one_selects == many_selects == 6
    assert one_dml == many_dml == 0
    assert pending in section_db.new
    assert pending.id is None


@pytest.mark.asyncio
async def test_empty_and_beyond_last_pages_preserve_truthful_totals(
    section_db: AsyncSession,
):
    empty = CRMContact(first_name="Empty", last_name="Section", stage="lead")
    populated = CRMContact(first_name="Populated", last_name="Section", stage="lead")
    section_db.add_all([empty, populated])
    await section_db.flush()
    for index in range(3):
        await _add_occurrence(
            section_db,
            populated,
            42_000 + index,
            section=ContactSection.NOTES,
            values={"title": f"note {index}"},
        )

    empty_page = await _list_section(
        section_db, empty.id, ContactSection.NOTES, page=2, page_size=2
    )
    beyond = await _list_section(
        section_db, populated.id, ContactSection.NOTES, page=3, page_size=2
    )
    assert (empty_page.rows, empty_page.total, empty_page.page_count) == ((), 0, 0)
    assert empty_page.page == 2
    assert (beyond.rows, beyond.total, beyond.page_count) == ((), 3, 2)
    assert beyond.page == 3


@pytest.mark.asyncio
async def test_section_order_uses_occurrence_ordinal_then_occurrence_id_for_ties(
    section_db: AsyncSession,
):
    contact = CRMContact(first_name="Tie", last_name="Order", stage="lead")
    section_db.add(contact)
    await section_db.flush()
    first, _first_source = await _add_occurrence(
        section_db,
        contact,
        43_001,
        section=ContactSection.NOTES,
        values={"title": "ordinal two"},
        capture_ordinal=1,
        occurrence_ordinal=2,
    )
    capture = await section_db.get(CRMContactSectionCapture, first.section_capture_id)
    assert capture is not None
    source_one = _source(
        43_002,
        kind="contact_note",
        payload={"values": {"title": "ordinal one A"}},
    )
    source_two = _source(
        43_003,
        kind="contact_note",
        payload={"values": {"title": "ordinal one B"}},
    )
    section_db.add_all([source_one, source_two])
    await section_db.flush()
    occurrence_one_a = CRMContactSourceOccurrence(
        contact_id=contact.id,
        section_capture_id=capture.id,
        source_record_id=source_one.id,
        occurrence_ordinal=1,
    )
    occurrence_one_b = CRMContactSourceOccurrence(
        contact_id=contact.id,
        section_capture_id=capture.id,
        source_record_id=source_two.id,
        occurrence_ordinal=3,
    )
    section_db.add_all([occurrence_one_a, occurrence_one_b])
    await section_db.flush()

    page = await _list_section(section_db, contact.id, ContactSection.NOTES)
    assert tuple(row.value.title for row in page.rows) == (
        "ordinal one A",
        "ordinal two",
        "ordinal one B",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "section",
    tuple(value for value in ContactSection if value is not ContactSection.TIMELINE),
)
async def test_each_section_query_count_is_constant_at_one_vs_101_occurrences(
    section_db: AsyncSession,
    section: ContactSection,
):
    one = CRMContact(first_name="One", last_name=section.value, stage="lead")
    many = CRMContact(first_name="Many", last_name=section.value, stage="lead")
    section_db.add_all([one, many])
    await section_db.flush()

    def values(index: int) -> dict[str, object]:
        key = (
            "name"
            if section in {ContactSection.SMART_PLANS, ContactSection.SAVED_SEARCHES}
            else "title"
        )
        return {key: f"row {index}"}

    await _add_occurrence(
        section_db,
        one,
        50_001,
        section=section,
        values=values(0),
    )
    for index in range(101):
        await _add_occurrence(
            section_db,
            many,
            51_000 + index,
            section=section,
            values=values(index),
        )

    async def select_count(contact_id: int, page_size: int) -> tuple[int, int]:
        selects = 0
        dml = 0

        def capture(_connection, _cursor, statement, _params, _context, _many):
            nonlocal selects, dml
            verb = statement.lstrip().split(None, 1)[0].upper()
            if verb == "SELECT":
                selects += 1
            elif verb in {"INSERT", "UPDATE", "DELETE"}:
                dml += 1

        assert section_db.bind is not None
        event.listen(section_db.bind.sync_engine, "before_cursor_execute", capture)
        try:
            page = await _list_section(
                section_db,
                contact_id,
                section,
                page=1,
                page_size=page_size,
            )
        finally:
            event.remove(section_db.bind.sync_engine, "before_cursor_execute", capture)
        assert len(page.rows) == page_size
        return selects, dml

    one_selects, one_dml = await select_count(one.id, 1)
    many_selects, many_dml = await select_count(many.id, 100)
    assert one_selects == many_selects == 6
    assert one_dml == many_dml == 0
