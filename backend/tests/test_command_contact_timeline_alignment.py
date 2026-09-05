"""Ambiguous capture boundaries must preserve business content and source dates."""

import hashlib
import json
from datetime import date
from html import escape

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMArchiveArtifact
from models.command_contacts import CRMContactSourceOccurrence, CRMContactTimelineEvent
from models.command_provenance import CRMSourceRecord, CRMSourceRecordArtifact
from services.command_contact_timeline import list_contact_timeline
from tests.test_command_contact_capture_timeline import literal_note_seed, seed
from tests.test_command_contact_timeline import _source
from tests.test_command_contact_timeline import timeline_db as _timeline_db
from tests.test_command_contact_timeline_snapshot import CONSENT_PANEL

timeline_db = _timeline_db


async def _quoted_fragment_capture(db: AsyncSession, *, artifact_format: str):
    events = await seed(db)
    captures = [
        ["NOTE", "2:16 PM", "Created", "By Example Agent", "Training note"],
        [
            "NOTE",
            "9:15 AM",
            "Created",
            "By Example Agent",
            "Quoted example",
            "FEB 1, 2025",
        ],
        [
            "NOTE",
            "9:15 AM",
            "Created",
            "By Example Agent",
            "Actual later note",
            "End of Timeline",
        ],
    ]
    source = _source(4)
    source.display_label = "Original parser title"
    db.add(source)
    db.add(
        CRMContactSourceOccurrence(
            contact_id=1,
            section_capture_id=300001,
            source_record_id=4,
            occurrence_ordinal=4,
        )
    )
    events.append(
        CRMContactTimelineEvent(
            id=4,
            contact_id=1,
            source_record_id=4,
            source_system="kw_command",
            source_event_key=source.source_key,
            kind="note",
            title=source.display_label,
        )
    )
    db.add(events[-1])
    for event, raw in zip(events[1:], captures, strict=True):
        source = await db.get(CRMSourceRecord, event.source_record_id)
        assert source is not None
        values = {"kind": "NOTE", "raw_lines": raw}
        source.payload_json = json.dumps(
            {
                "values": values,
                "source_contact_id": "000000000000000000000001",
                "capture_ordinal": "0000001",
                "section_name": "timeline",
                "occurrence_ordinal": event.id,
            }
        )
        event.kind = "note"
        event.body = "\n".join(raw)
        event.attributes_json = json.dumps(values)

    # There are two real activities. The middle source record is a fragment of
    # the first activity's nested quotation, not a third structural activity.
    if artifact_format == "html":

        def divs(lines):
            return "".join(f"<div>{escape(line)}</div>" for line in lines)

        content = (
            '<h5 class="txt-h5 styles_date-header__example">Jan 12, 2026</h5>'
            '<div data-test="timeline-note">'
            + divs(captures[0])
            + "<blockquote>"
            + divs(captures[1][:-1])
            + "</blockquote></div>"
            '<h5 class="txt-h5 styles_date-header__example">Feb 1, 2025</h5>'
            '<div data-test="timeline-note">' + divs(captures[2][:-1]) + "</div>"
            '<p class="txt-p d-flex justify-content-center align-items-center pb-4">'
            "End of Timeline</p>"
        ).encode()
    else:
        snapshot = (
            "- generic: AI Summary\n"
            '- heading "Jan 12, 2026" [level=5]\n'
            + "".join(f"- generic: {line}\n" for line in captures[0])
            + "".join(f"  - generic: {line}\n" for line in captures[1][:-1])
            + '- heading "Feb 1, 2025" [level=5]\n'
            + "".join(f"- generic: {line}\n" for line in captures[2][:-1])
            + "- paragraph: End of Timeline\n"
            + CONSENT_PANEL
        )
        content = json.dumps({"accessibility_snapshot": snapshot}).encode()
    db.add(
        CRMArchiveArtifact(
            id=1,
            source_path=(
                "kw_command_repaired/contacts/sections/0000001/"
                f"timeline.{artifact_format}"
            ),
            domain="kw_command",
            artifact_type=artifact_format,
            filename=f"timeline.{artifact_format}",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            content_bytes=content,
        )
    )
    await db.flush()
    db.add_all(
        CRMSourceRecordArtifact(source_record_id=event.source_record_id, artifact_id=1)
        for event in events
    )
    await db.flush()
    return events


@pytest.mark.asyncio
@pytest.mark.parametrize("artifact_format", ["html", "json"])
@pytest.mark.parametrize("page_size", [1, 10])
async def test_quoted_header_cannot_steal_later_real_activity_date(
    timeline_db: AsyncSession, artifact_format: str, page_size: int
):
    events = await _quoted_fragment_capture(
        timeline_db, artifact_format=artifact_format
    )
    sources = [
        await timeline_db.get(CRMSourceRecord, event.source_record_id)
        for event in events
    ]
    original_events = [
        (event.title, event.body, event.attributes_json, event.occurred_at)
        for event in events
    ]
    original_sources = [source.payload_json for source in sources]

    rows = []
    cursor = None
    for _ in range(len(events)):
        page = await list_contact_timeline(
            timeline_db, 1, cursor=cursor, page_size=page_size
        )
        assert page.filtered_capture_count == 1
        rows.extend(page.rows)
        if not page.has_more:
            assert page.next_cursor is None
            break
        assert page.next_cursor is not None and page.next_cursor != cursor
        cursor = page.next_cursor
    else:
        pytest.fail("Timeline cursor failed to reach the end of this bounded capture")

    assert len(rows) == 3
    by_id = {row.entity_id: row for row in rows}
    assert set(by_id) == {2, 3, 4}
    assert by_id[2].title == "Training note"
    assert by_id[3].title == "Quoted example"
    assert by_id[3].body == "FEB 1, 2025"
    assert by_id[4].title == "Actual later note"
    assert (by_id[3].captured_date, by_id[4].captured_date) == (
        None,
        date(2025, 2, 1),
    )
    assert all(row.occurred_at is None for row in rows)
    assert original_events == [
        (event.title, event.body, event.attributes_json, event.occurred_at)
        for event in events
    ]
    assert original_sources == [source.payload_json for source in sources]
    assert not timeline_db.dirty


async def _attach_verified_archive(
    db: AsyncSession,
    events: list[CRMContactTimelineEvent],
    *,
    content: bytes,
    artifact_format: str,
) -> None:
    db.add(
        CRMArchiveArtifact(
            id=1,
            source_path=(
                "kw_command_repaired/contacts/sections/0000001/"
                f"timeline.{artifact_format}"
            ),
            domain="kw_command",
            artifact_type=artifact_format,
            filename=f"timeline.{artifact_format}",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            content_bytes=content,
        )
    )
    await db.flush()
    db.add_all(
        CRMSourceRecordArtifact(source_record_id=event.source_record_id, artifact_id=1)
        for event in events
    )
    await db.flush()


@pytest.mark.asyncio
async def test_verified_navigation_activity_without_clock_remains_visible_for_review(
    timeline_db: AsyncSession,
):
    events = await seed(timeline_db)
    source = await timeline_db.get(CRMSourceRecord, 1)
    assert source is not None
    payload = json.loads(source.payload_json)
    activity = [
        "Neighborhoods",
        "Time was not captured",
        "Added",
        "By Example Agent",
        "Saved neighborhood",
        "Preserve this business detail.",
    ]
    raw = [*payload["values"]["raw_lines"], *activity, "End of Timeline"]
    payload["values"]["raw_lines"] = raw
    source.payload_json = json.dumps(payload)
    events[0].body = "\n".join(raw)
    events[0].attributes_json = json.dumps(payload["values"])
    html = (
        '<h5 class="txt-h5 styles_date-header__example">Jan 12, 2026</h5>'
        '<div data-test="timeline-neighborhoods">'
        + "".join(f"<div>{escape(line)}</div>" for line in activity)
        + "</div>"
        '<p class="txt-p d-flex justify-content-center align-items-center pb-4">'
        "End of Timeline</p>"
    )
    await _attach_verified_archive(
        timeline_db, events, content=html.encode(), artifact_format="html"
    )
    original = source.payload_json, events[0].body, events[0].attributes_json

    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)

    by_id = {row.entity_id: row for row in page.rows}
    assert 1 in by_id, (
        "A verified business activity must not be filtered as page controls"
    )
    row = by_id[1]
    assert row.kind == "capture_needs_review"
    assert row.title == "Captured activity needs review"
    assert "Source Evidence" in row.body
    assert row.captured_date is None
    assert row.captured_time is None
    assert row.occurred_at is None
    assert page.filtered_capture_count == 0
    assert original == (source.payload_json, events[0].body, events[0].attributes_json)
    assert not timeline_db.dirty


@pytest.mark.asyncio
async def test_final_snapshot_note_keeps_literal_footer_paragraph_before_real_footer(
    timeline_db: AsyncSession,
):
    events = await literal_note_seed(timeline_db)
    snapshot = '- generic: AI Summary\n- heading "Jan 12, 2026" [level=5]\n'
    for event in events[1:]:
        raw = json.loads(event.attributes_json)["raw_lines"]
        if event.id == 3:
            raw = raw[:-1]
        for line in raw:
            role = "paragraph" if line == "End of Timeline" else "generic"
            snapshot += f"- {role}: {line}\n"
    snapshot += "- paragraph: End of Timeline\n" + CONSENT_PANEL
    await _attach_verified_archive(
        timeline_db,
        events,
        content=json.dumps({"accessibility_snapshot": snapshot}).encode(),
        artifact_format="json",
    )
    source = await timeline_db.get(CRMSourceRecord, 3)
    assert source is not None
    original = source.payload_json, events[2].body, events[2].attributes_json

    page = await list_contact_timeline(timeline_db, 1, cursor=None, page_size=10)

    row = next(row for row in page.rows if row.entity_id == 3)
    assert row.body == "End of Timeline\nPreserve the next sentence."
    assert row.title == "A footer label is part of this note"
    assert row.captured_date == date(2026, 1, 12)
    assert row.captured_time == "13:15:00"
    assert row.occurred_at is None
    assert original == (source.payload_json, events[2].body, events[2].attributes_json)
    assert not timeline_db.dirty
