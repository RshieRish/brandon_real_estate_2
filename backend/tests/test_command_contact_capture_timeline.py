"""Read-path recovery must preserve sources, edits, and cursor boundaries."""

import hashlib
import json
from datetime import date
from html import escape

import pytest

from models.command import CRMArchiveArtifact, CRMContact
from models.command_contacts import CRMContactSourceOccurrence, CRMContactTimelineEvent
from models.command_provenance import CRMSourceRecordArtifact
from services.command_contact_timeline import list_contact_timeline
from tests.test_command_contact_timeline import _source, _timeline_ownership
from tests.test_command_contact_timeline import timeline_db as _timeline_db
from tests.test_command_contact_timeline_snapshot import CONSENT_PANEL

timeline_db = _timeline_db


async def seed(db):
    db.add(CRMContact(id=1, first_name="Synthetic", last_name="Person", stage="lead"))
    db.add_all(_timeline_ownership(1, contact_id=1))
    await db.flush()
    lines = [
        [
            "SmartPlans",
            "Tasks",
            "Notes",
            "Saved Searches",
            "All Time",
            "All Activity",
            "AI Summary",
            "JAN 12, 2026",
        ],
        [
            "EMAIL",
            "1:40 PM",
            "Sent",
            "By Example Agent",
            "Latest update",
            "The message.",
            "SEP 4, 2025",
        ],
        [
            "NOTE",
            "9:15 AM",
            "Created",
            "By Example Agent",
            "Older note",
            "Keep this body.",
            "End of Timeline",
            "Welcome to KWIQ",
            "KWIQ uses artificial intelligence (AI).",
        ],
    ]
    events = []
    for index, raw in enumerate(lines, 1):
        source = _source(index)
        source.display_label = "Original parser title"
        values = {"kind": raw[0].upper(), "raw_lines": raw}
        source.payload_json = json.dumps(
            {
                "values": values,
                "source_contact_id": "000000000000000000000001",
                "capture_ordinal": "0000001",
                "section_name": "timeline",
                "occurrence_ordinal": index,
            }
        )
        db.add(source)
        if index > 1:
            db.add(
                CRMContactSourceOccurrence(
                    contact_id=1,
                    section_capture_id=300001,
                    source_record_id=index,
                    occurrence_ordinal=index,
                )
            )
        event = CRMContactTimelineEvent(
            id=index,
            contact_id=1,
            source_record_id=index,
            source_system="kw_command",
            source_event_key=source.source_key,
            kind=raw[0].lower(),
            title="Original parser title",
            body="\n".join(raw),
            attributes_json=json.dumps(values),
        )
        db.add(event)
        events.append(event)
    await db.flush()
    return events


@pytest.mark.asyncio
async def test_source_order_dates_cleanup_and_full_cursor_pages(timeline_db):
    events = await seed(timeline_db)
    await attach_html(timeline_db, events, literal=False)
    original = [
        (event.body, event.attributes_json, event.occurred_at) for event in events
    ]
    first = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=1)
    assert first.filtered_capture_count == 1
    assert first.rows[0].title == "Latest update"
    assert first.rows[0].occurred_at is None
    assert first.rows[0].captured_date == date(2026, 1, 12)
    assert first.rows[0].captured_time == "13:40:00"
    assert first.has_more and first.next_cursor
    second = await list_contact_timeline(
        timeline_db, 1, cursor=first.next_cursor, page_size=1
    )
    assert second.rows[0].title == "Older note"
    assert second.rows[0].body == "Keep this body."
    assert second.rows[0].captured_date == date(2025, 9, 4)
    assert not second.has_more
    assert original == [
        (event.body, event.attributes_json, event.occurred_at) for event in events
    ]
    assert not timeline_db.dirty


@pytest.mark.asyncio
async def test_later_edited_body_is_not_replaced_by_source(timeline_db):
    events = await seed(timeline_db)
    events[1].body = "A newer user edit. Keep exactly."
    await timeline_db.flush()
    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    edited = next(row for row in page.rows if row.entity_id == 2)
    assert edited.body == "A newer user edit. Keep exactly."


@pytest.mark.asyncio
async def test_later_title_edits_are_preserved_including_otherwise_hidden_rows(
    timeline_db,
):
    events = await seed(timeline_db)
    events[0].title = "A later navigation annotation"
    events[1].title = "A newer title"
    await timeline_db.flush()
    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    by_id = {row.entity_id: row for row in page.rows}
    assert by_id[1].title == "A later navigation annotation"
    assert by_id[2].title == "A newer title"
    assert page.filtered_capture_count == 0


async def attach_html(db, events, *, corrupt=False, literal=True):
    connection = await db.connection()
    await connection.run_sync(
        lambda sync: CRMArchiveArtifact.__table__.create(sync, checkfirst=True)
    )
    await connection.run_sync(
        lambda sync: CRMSourceRecordArtifact.__table__.create(sync, checkfirst=True)
    )
    html = '<h5 class="txt-h5 styles_date-header__example">Jan 12, 2026</h5>'
    for event in events[1:]:
        raw = json.loads(event.attributes_json)["raw_lines"]
        # Only the final literal footer is a page control, not the one in the note.
        if not literal:
            raw = raw[:-1] if event.id == 2 else raw[:6]
        elif event.id == 3:
            raw = raw[:-1]
        html += (
            '<div data-test="timeline-note">'
            + "".join(f"<div>{escape(line)}</div>" for line in raw)
            + "</div>"
        )
        if not literal and event.id == 2:
            html += '<h5 class="txt-h5 styles_date-header__example">Sep 4, 2025</h5>'
    html += '<p class="txt-p d-flex justify-content-center align-items-center pb-4">End of Timeline</p>'
    content = html.encode()
    artifact = CRMArchiveArtifact(
        id=1,
        source_path="kw_command_repaired/contacts/sections/0000001/timeline.html",
        domain="kw_command",
        artifact_type="html",
        filename="timeline.html",
        sha256=("0" * 64 if corrupt else hashlib.sha256(content).hexdigest()),
        size_bytes=len(content),
        content_bytes=content,
    )
    db.add(artifact)
    await db.flush()
    db.add_all(
        CRMSourceRecordArtifact(source_record_id=event.source_record_id, artifact_id=1)
        for event in events
    )
    await db.flush()


async def literal_note_seed(db):
    from models.command_provenance import CRMSourceRecord

    events = await seed(db)
    for event, body in (
        (events[1], ["A date is part of this note", "SEP 4, 2025"]),
        (
            events[2],
            [
                "A footer label is part of this note",
                "End of Timeline",
                "Preserve the next sentence.",
                "End of Timeline",
            ],
        ),
    ):
        raw = [
            "NOTE",
            "2:16 PM" if event.id == 2 else "1:15 PM",
            "Created",
            "By Example Agent",
            *body,
        ]
        values = {"kind": "NOTE", "raw_lines": raw}
        source = await db.get(CRMSourceRecord, event.source_record_id)
        source.payload_json = json.dumps(
            {**json.loads(source.payload_json), "values": values}
        )
        event.kind = "note"
        event.body = "\n".join(raw)
        event.attributes_json = json.dumps(values)
    await db.flush()
    return events


@pytest.mark.asyncio
async def test_verified_html_keeps_literal_dates_and_footer_words_in_notes(timeline_db):
    events = await literal_note_seed(timeline_db)
    await attach_html(timeline_db, events)
    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    by_id = {row.entity_id: row for row in page.rows}
    assert by_id[2].body == "SEP 4, 2025"
    assert by_id[3].captured_date == date(2026, 1, 12)
    assert by_id[3].body == "End of Timeline\nPreserve the next sentence."
    assert not timeline_db.dirty


@pytest.mark.asyncio
async def test_corrupt_html_is_not_used_to_infer_captured_dates(timeline_db):
    from services.command_contact_timeline import ContactTimelineIntegrityError

    events = await literal_note_seed(timeline_db)
    await attach_html(timeline_db, events, corrupt=True)
    with pytest.raises(ContactTimelineIntegrityError, match="archive"):
        await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)


@pytest.mark.asyncio
async def test_absent_html_keeps_date_literals_without_inventing_date(timeline_db):
    await literal_note_seed(timeline_db)
    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    note = next(row for row in page.rows if row.entity_id == 2)
    assert note.body == "SEP 4, 2025"
    assert note.captured_date is None


@pytest.mark.asyncio
async def test_combined_legacy_activity_tail_keeps_every_event_without_page_footer(
    timeline_db,
):
    from models.command_provenance import CRMSourceRecord

    events = await seed(timeline_db)
    raw = [
        "NOTE",
        "9:15 AM",
        "Created",
        "By Example Agent",
        "Older note",
        "Keep this body.",
        "SEP 3, 2025",
        "Neighborhoods",
        "8:00 AM",
        "Added",
        "By Example Agent",
        "Saved neighborhood",
        "Example neighborhood",
        "End of Timeline",
    ]
    event = events[2]
    source = await timeline_db.get(CRMSourceRecord, event.source_record_id)
    payload = json.loads(source.payload_json)
    payload["values"]["raw_lines"] = raw
    source.payload_json = json.dumps(payload)
    event.attributes_json = json.dumps(payload["values"])
    event.body = "\n".join(raw)
    await attach_html(timeline_db, events, literal=False)
    artifact = await timeline_db.get(CRMArchiveArtifact, 1)
    html = artifact.content_bytes.decode()
    marker = '<p class="txt-p d-flex justify-content-center align-items-center pb-4">'
    extra = (
        '<h5 class="txt-h5 styles_date-header__example">Sep 3, 2025</h5><div data-test="timeline-neighborhoods">'
        + "".join(f"<div>{escape(line)}</div>" for line in raw[7:-1])
        + "</div>"
    )
    artifact.content_bytes = html.replace(marker, extra + marker).encode()
    artifact.size_bytes = len(artifact.content_bytes)
    artifact.sha256 = hashlib.sha256(artifact.content_bytes).hexdigest()
    await timeline_db.flush()

    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    result = next(row for row in page.rows if row.entity_id == 3)
    assert result.body == "\n".join(raw[5:-1])
    assert result.captured_date == date(2025, 9, 4)
    assert not timeline_db.dirty


@pytest.mark.asyncio
@pytest.mark.parametrize("literal_reply", [True, False])
async def test_unproven_control_words_are_kept_in_verified_business_content(
    timeline_db, literal_reply
):
    from models.command_provenance import CRMSourceRecord

    events = await seed(timeline_db)
    event = events[2]
    raw = (
        ["TEXT", "9:15 AM", "Sent", "By Example Agent", "SMS message", "Reply"]
        if literal_reply
        else [
            "NOTE",
            "9:15 AM",
            "Created",
            "By Example Agent",
            "Training note",
            "End of Timeline",
            "Welcome to KWIQ",
            "KWIQ uses artificial intelligence (AI).",
            "Keep this business sentence.",
        ]
    )
    source = await timeline_db.get(CRMSourceRecord, event.source_record_id)
    payload = json.loads(source.payload_json)
    payload["values"].update(kind=raw[0], raw_lines=raw)
    source.payload_json = json.dumps(payload)
    event.kind = raw[0].lower()
    event.attributes_json = json.dumps(payload["values"])
    event.body = "\n".join(raw)
    await attach_html(timeline_db, events, literal=False)
    artifact = await timeline_db.get(CRMArchiveArtifact, 1)
    html = (
        '<h5 class="txt-h5 styles_date-header__example">Jan 12, 2026</h5><div data-test="timeline-text">'
        + "".join(f"<div>{escape(line)}</div>" for line in raw)
        + (
            ""
            if literal_reply
            else "<button>Additional control absent from raw capture</button>"
        )
        + "</div>"
    )
    artifact.content_bytes = html.encode()
    artifact.size_bytes = len(artifact.content_bytes)
    artifact.sha256 = hashlib.sha256(artifact.content_bytes).hexdigest()
    await timeline_db.flush()

    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    result = next(row for row in page.rows if row.entity_id == 3)
    assert result.body == "\n".join(raw[5:])
    assert result.captured_date == date(2026, 1, 12)
    assert not timeline_db.dirty


@pytest.mark.asyncio
async def test_embedded_navigation_activities_are_visible_as_one_preserved_group(
    timeline_db,
    monkeypatch,
):
    from models.command_provenance import CRMSourceRecord
    from services import command_contact_timeline as timeline_service

    original_cleanup = timeline_service.verified_timeline_fragment_tail_lines

    def unmatched_fragment_only(facts, raw):
        assert raw[0] != "SmartPlans", (
            "A recovered navigation group is not an unmatched fragment"
        )
        return original_cleanup(facts, raw)

    monkeypatch.setattr(
        timeline_service,
        "verified_timeline_fragment_tail_lines",
        unmatched_fragment_only,
    )

    events = await seed(timeline_db)
    source = await timeline_db.get(CRMSourceRecord, 1)
    payload = json.loads(source.payload_json)
    first = [
        "Neighborhoods",
        "8:00 AM",
        "Added",
        "By Example Agent",
        "Saved neighborhood",
        "Example neighborhood",
    ]
    second = [
        "Property Inquiry",
        "7:00 AM",
        "Created",
        "By Example Agent",
        "Saved listing",
        "Keep every detail",
    ]
    group = [*first, "SEP 3, 2025", *second]
    raw = [
        *payload["values"]["raw_lines"],
        *group,
        "End of Timeline",
        "Welcome to KWIQ",
    ]
    payload["values"]["raw_lines"] = raw
    source.payload_json = json.dumps(payload)
    events[0].attributes_json = json.dumps(payload["values"])
    events[0].body = "\n".join(raw)
    await attach_html(timeline_db, events, literal=False)
    artifact = await timeline_db.get(CRMArchiveArtifact, 1)
    html = '<h5 class="txt-h5 styles_date-header__example">Jan 12, 2026</h5>'
    for block, data_test in [
        (first, "timeline-neighborhoods"),
        (second, "timeline-listings"),
    ]:
        if block is second:
            html += '<h5 class="txt-h5 styles_date-header__example">Sep 3, 2025</h5>'
        html += (
            f'<div data-test="{data_test}">'
            + "".join(f"<div>{escape(line)}</div>" for line in block)
            + "</div>"
        )
    html += '<p class="txt-p d-flex justify-content-center align-items-center pb-4">End of Timeline</p>'
    artifact.content_bytes = html.encode()
    artifact.size_bytes = len(artifact.content_bytes)
    artifact.sha256 = hashlib.sha256(artifact.content_bytes).hexdigest()
    await timeline_db.flush()
    original = source.payload_json, events[0].body

    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=1)
    result = page.rows[0]
    assert result.entity_id == 1
    assert result.title == "2 recovered activities"
    assert result.kind == "captured_activity_group"
    assert result.body == "\n".join(group)
    assert result.captured_date == date(2026, 1, 12)
    assert page.filtered_capture_count == 0
    assert original == (source.payload_json, events[0].body)
    assert not timeline_db.dirty


@pytest.mark.asyncio
async def test_unsupported_activity_in_navigation_is_not_reported_as_empty(timeline_db):
    from models.command_provenance import CRMSourceRecord

    events = await seed(timeline_db)
    source = await timeline_db.get(CRMSourceRecord, 1)
    payload = json.loads(source.payload_json)
    raw = [
        *payload["values"]["raw_lines"],
        "Future activity type",
        "8:00 AM",
        "Captured business detail",
    ]
    payload["values"]["raw_lines"] = raw
    source.payload_json = json.dumps(payload)
    events[0].attributes_json = json.dumps(payload["values"])
    events[0].body = "\n".join(raw)
    await timeline_db.flush()

    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    by_id = {row.entity_id: row for row in page.rows}
    assert 1 in by_id
    assert by_id[1].title == "Captured activity needs review"
    assert by_id[1].kind == "capture_needs_review"
    assert "Source Evidence" in by_id[1].body
    assert page.filtered_capture_count == 0
    assert not timeline_db.dirty


@pytest.mark.asyncio
@pytest.mark.parametrize("edited", [False, True])
async def test_archive_quoted_body_restoration_preserves_raw_source_and_later_edits(
    timeline_db, edited
):
    from models.command_provenance import CRMSourceRecord

    events = await seed(timeline_db)
    source = await timeline_db.get(CRMSourceRecord, 1)
    payload = json.loads(source.payload_json)
    header = ["Contact Details", "8:00 AM", "Updated", "By Example Agent"]
    raw = [
        *payload["values"]["raw_lines"],
        *header,
        "End of Timeline",
        "Welcome to KWIQ",
    ]
    payload["values"]["raw_lines"] = raw
    source.payload_json = json.dumps(payload)
    events[0].attributes_json = json.dumps(payload["values"])
    events[0].body = "A newer manual annotation." if edited else "\n".join(raw)
    snapshot = (
        '- generic: AI Summary\n- heading "Jan 12, 2026" [level=5]\n'
        + "\n".join(f"- generic: {line}" for line in header)
        + '\n- separator\n- generic: Status changed to "Assigned"\n'
        + "- paragraph: End of Timeline\n"
        + CONSENT_PANEL
    )
    content = json.dumps({"accessibility_snapshot": snapshot}).encode()
    timeline_db.add(
        CRMArchiveArtifact(
            id=1,
            source_path="kw_command_repaired/contacts/sections/0000001/timeline.json",
            domain="kw_command",
            artifact_type="json",
            filename="timeline.json",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            content_bytes=content,
        )
    )
    await timeline_db.flush()
    timeline_db.add_all(
        CRMSourceRecordArtifact(source_record_id=event.source_record_id, artifact_id=1)
        for event in events
    )
    await timeline_db.flush()
    original = (source.payload_json, events[0].body)
    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    row = next(row for row in page.rows if row.entity_id == 1)
    assert row.body == (
        "A newer manual annotation."
        if edited
        else "\n".join([*header, 'Status changed to "Assigned"'])
    )
    if not edited:
        assert row.captured_date == date(2026, 1, 12)
        assert row.kind != "capture_needs_review"
    assert original == (source.payload_json, events[0].body)
    assert not timeline_db.dirty


@pytest.mark.asyncio
async def test_verified_snapshot_json_restores_days_and_preserves_date_literals(
    timeline_db,
):
    events = await literal_note_seed(timeline_db)
    snapshot = '- generic: AI Summary\n- heading "Jan 12, 2026" [level=5]\n'
    for event in events[1:]:
        raw = json.loads(event.attributes_json)["raw_lines"]
        if event.id == 3:
            raw = raw[:-1]
        snapshot += "\n".join(f"- generic: {line}" for line in raw) + "\n"
    snapshot += "- paragraph: End of Timeline\n" + CONSENT_PANEL
    content = json.dumps({"accessibility_snapshot": snapshot}).encode()
    timeline_db.add(
        CRMArchiveArtifact(
            id=1,
            source_path="kw_command_repaired/contacts/sections/0000001/timeline.json",
            domain="kw_command",
            artifact_type="json",
            filename="timeline.json",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            content_bytes=content,
        )
    )
    await timeline_db.flush()
    timeline_db.add_all(
        CRMSourceRecordArtifact(source_record_id=event.source_record_id, artifact_id=1)
        for event in events
    )
    await timeline_db.flush()
    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    by_id = {row.entity_id: row for row in page.rows}
    assert by_id[2].captured_date == date(2026, 1, 12)
    assert by_id[2].body == "SEP 4, 2025"
    assert by_id[3].body == "End of Timeline\nPreserve the next sentence."
    assert not timeline_db.dirty


@pytest.mark.asyncio
async def test_verified_legacy_tail_removes_only_controls_after_omitted_quoted_generic(
    timeline_db,
):
    from models.command_provenance import CRMSourceRecord

    events = await seed(timeline_db)
    source = await timeline_db.get(CRMSourceRecord, 3)
    payload = json.loads(source.payload_json)
    first = payload["values"]["raw_lines"][:6]
    second = ["Contact Details", "8:00 AM", "Updated", "By Example Agent"]
    raw = [*first, "SEP 3, 2025", *second, "End of Timeline", "Welcome to KWIQ"]
    payload["values"]["raw_lines"] = raw
    source.payload_json = json.dumps(payload)
    events[2].attributes_json = json.dumps(payload["values"])
    events[2].body = "\n".join(raw)
    snapshot = (
        '- generic: AI Summary\n- heading "Sep 4, 2025" [level=5]\n'
        + "\n".join(f"- generic: {line}" for line in first)
        + '\n- heading "Sep 3, 2025" [level=5]\n'
        + "\n".join(f"- generic: {line}" for line in second)
        + '\n- separator\n- generic: Status changed to "Assigned"\n'
        + "- paragraph: End of Timeline\n"
        + CONSENT_PANEL
    )
    content = json.dumps({"accessibility_snapshot": snapshot}).encode()
    timeline_db.add(
        CRMArchiveArtifact(
            id=1,
            source_path="kw_command_repaired/contacts/sections/0000001/timeline.json",
            domain="kw_command",
            artifact_type="json",
            filename="timeline.json",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            content_bytes=content,
        )
    )
    await timeline_db.flush()
    timeline_db.add_all(
        CRMSourceRecordArtifact(source_record_id=event.source_record_id, artifact_id=1)
        for event in events
    )
    await timeline_db.flush()
    original = (source.payload_json, events[2].body)
    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    row = next(row for row in page.rows if row.entity_id == 3)
    assert row.body == "\n".join(raw[5:-2])
    assert row.captured_date == date(2025, 9, 4)
    assert original == (source.payload_json, events[2].body)
    assert not timeline_db.dirty


@pytest.mark.asyncio
@pytest.mark.parametrize("edited", [False, True])
async def test_split_note_body_cleanup_never_assigns_an_event_date_or_changes_edits(
    timeline_db, edited
):
    from models.command_provenance import CRMSourceRecord

    events = await seed(timeline_db)
    source = await timeline_db.get(CRMSourceRecord, 3)
    payload = json.loads(source.payload_json)
    fragment = ["Call", "Preserve this entire follow-up note."]
    following = [
        "Neighborhoods",
        "8:00 AM",
        "Added",
        "By Example Agent",
        "Saved neighborhood",
        "Example area",
    ]
    raw = [*fragment, "SEP 3, 2025", *following, "End of Timeline", "Welcome to KWIQ"]
    payload["values"].update(kind="CALL", raw_lines=raw)
    source.payload_json = json.dumps(payload)
    events[2].kind = "call"
    events[2].attributes_json = json.dumps(payload["values"])
    events[2].body = "A later manual edit." if edited else "\n".join(raw)
    await attach_html(timeline_db, events, literal=False)
    artifact = await timeline_db.get(CRMArchiveArtifact, 1)
    first = ["NOTE", "9:15 AM", "Created", "By Example Agent", *fragment]
    artifact.content_bytes = (
        '<h5 class="txt-h5 styles_date-header__example">Sep 4, 2025</h5>'
        '<div data-test="timeline-note">'
        + "".join(f"<div>{escape(line)}</div>" for line in first)
        + '</div><h5 class="txt-h5 styles_date-header__example">Sep 3, 2025</h5>'
        '<div data-test="timeline-neighborhoods">'
        + "".join(f"<div>{escape(line)}</div>" for line in following)
        + '</div><p class="txt-p d-flex justify-content-center align-items-center pb-4">End of Timeline</p>'
    ).encode()
    artifact.size_bytes = len(artifact.content_bytes)
    artifact.sha256 = hashlib.sha256(artifact.content_bytes).hexdigest()
    await timeline_db.flush()
    original = (source.payload_json, events[2].body)

    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)
    row = next(row for row in page.rows if row.entity_id == 3)
    assert row.body == ("A later manual edit." if edited else "\n".join(raw[:-2]))
    assert row.captured_date is None and row.captured_time is None
    assert row.occurred_at is None
    assert original == (source.payload_json, events[2].body)
    assert not timeline_db.dirty
