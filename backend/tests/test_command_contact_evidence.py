"""Lossless, privacy-safe evidence queries for recovered Command contacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import services.command_contacts as contact_service
from database import Base
from models.command import CRMArchiveArtifact, CRMContact, CRMNote, CRMTask
from models.command_contacts import (
    CRMContactAuditEvent,
    CRMContactCapturePosition,
    CRMContactSectionCapture,
    CRMContactSourceOccurrence,
    CRMContactTimelineEvent,
)
from models.command_provenance import (
    CRMEntitySource,
    CRMSourceRecord,
    CRMSourceRecordArtifact,
)
from models.lead import Lead
from services.command_contact_contracts import (
    CaptureQualityValue,
    ContactArtifactMetadata,
    ContactCaptureEvidence,
    ContactEvidence,
    ContactSection,
    ContactSectionEvidence,
    ContactSourceMetadata,
)
from services.command_contacts import ContactDataIntegrityError, ContactNotFound

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)
SECRET = "private-evidence-sentinel@example.test"
SECTION_KIND = {
    ContactSection.TIMELINE: "contact_timeline_event",
    ContactSection.OPPORTUNITIES: "contact_opportunity",
    ContactSection.SMART_PLANS: "contact_smart_plan",
    ContactSection.NOTES: "contact_note",
    ContactSection.SAVED_SEARCHES: "contact_saved_search",
    ContactSection.TASKS_TO_DO: "contact_task",
    ContactSection.TASKS_COMPLETED: "contact_task",
    ContactSection.TASKS_ARCHIVED: "contact_task",
}


@dataclass
class EvidenceGraph:
    contact: CRMContact
    profile_source: CRMSourceRecord
    position_source: CRMSourceRecord
    position: CRMContactCapturePosition
    sections: dict[ContactSection, CRMContactSectionCapture]
    section_sources: dict[ContactSection, CRMSourceRecord]
    occurrences: dict[ContactSection, CRMContactSourceOccurrence]
    occurrence_sources: dict[ContactSection, CRMSourceRecord]


@pytest_asyncio.fixture()
async def evidence_db(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'contact-evidence.sqlite'}"
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


async def _get_evidence(db: AsyncSession, contact_id: int) -> ContactEvidence:
    function = getattr(contact_service, "get_contact_evidence", None)
    assert function is not None, "get_contact_evidence is not implemented"
    return await function(db, contact_id)


def _source(
    index: int,
    *,
    kind: str,
    payload: object,
    evidence_level: str = "rendered_occurrence",
    quality: str = "complete",
    captured_at: datetime | None = NOW,
) -> CRMSourceRecord:
    return CRMSourceRecord(
        source_system="kw_command",
        module="contacts",
        record_kind=kind,
        source_key=f"{SECRET}:source:{index}",
        evidence_level=evidence_level,
        display_label=f"Synthetic evidence {index}",
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        capture_quality=quality,
        captured_at=captured_at,
        parser_version="contacts-evidence-test-v1",
    )


def _occurrence_values(section: ContactSection, index: int) -> dict[str, object]:
    if section is ContactSection.OPPORTUNITIES:
        return {"title": f"Opportunity {index}"}
    if section is ContactSection.SMART_PLANS:
        return {"name": f"Plan {index}", "status": "active"}
    if section is ContactSection.NOTES:
        return {"title": f"Note {index}", "body": "Synthetic body"}
    if section is ContactSection.SAVED_SEARCHES:
        return {"name": f"Search {index}", "beds": 3}
    if section in {
        ContactSection.TASKS_TO_DO,
        ContactSection.TASKS_COMPLETED,
        ContactSection.TASKS_ARCHIVED,
    }:
        return {"title": f"Task {index}"}
    return {"private_timeline_body": SECRET}


async def _add_graph(
    db: AsyncSession,
    index: int,
    *,
    contact: CRMContact | None = None,
    lead_id: int | None = None,
    occurrence_sections: tuple[ContactSection, ...] = (),
    section_qualities: dict[ContactSection, str] | None = None,
    reverse_sections: bool = False,
    artifacts: bool = False,
) -> EvidenceGraph:
    if lead_id is not None:
        db.add(Lead(id=lead_id, name=f"Synthetic lead {lead_id}"))
        await db.flush()
    if contact is None:
        contact = CRMContact(
            first_name="Recovered",
            last_name=f"Contact {index}",
            stage="lead",
            lead_id=lead_id,
        )
        db.add(contact)
        await db.flush()
    provider_id = f"{index:024x}"
    profile_source = _source(
        index * 100,
        kind="contact_profile",
        payload={"source_contact_id": provider_id, "private": SECRET},
        evidence_level="observed_record",
    )
    position_source = _source(
        index * 100 + 1,
        kind="contact_capture_position",
        payload={"capture_ordinal": index, "private": SECRET},
    )
    db.add_all([profile_source, position_source])
    await db.flush()
    db.add(
        CRMEntitySource(
            entity_type="contact",
            entity_id=contact.id,
            source_record_id=profile_source.id,
        )
    )
    position = CRMContactCapturePosition(
        contact_id=contact.id,
        source_record_id=position_source.id,
        bundle_fingerprint=f"{index:064x}",
        capture_ordinal=index,
        source_contact_id=provider_id,
        captured_at=NOW,
        capture_quality="complete",
        limitations_json="[]",
    )
    db.add(position)
    await db.flush()
    sections: dict[ContactSection, CRMContactSectionCapture] = {}
    section_sources: dict[ContactSection, CRMSourceRecord] = {}
    occurrences: dict[ContactSection, CRMContactSourceOccurrence] = {}
    occurrence_sources: dict[ContactSection, CRMSourceRecord] = {}
    ordered_sections = list(ContactSection)
    if reverse_sections:
        ordered_sections.reverse()
    for section_index, section in enumerate(ordered_sections, 1):
        quality = (section_qualities or {}).get(section, "complete")
        section_source = _source(
            index * 1000 + section_index,
            kind="contact_section_capture",
            payload={"section_name": section.value, "private": SECRET},
            quality=quality,
            captured_at=NOW - timedelta(minutes=section_index),
        )
        db.add(section_source)
        await db.flush()
        has_occurrence = section in occurrence_sections
        capture = CRMContactSectionCapture(
            capture_position_id=position.id,
            source_record_id=section_source.id,
            section_name=section.value,
            captured_at=section_source.captured_at,
            capture_quality=quality,
            is_empty=not has_occurrence,
            row_count=1 if has_occurrence else 0,
            limitations_json="[]",
        )
        db.add(capture)
        await db.flush()
        sections[section] = capture
        section_sources[section] = section_source
        if has_occurrence:
            occurrence_source = _source(
                index * 10_000 + section_index,
                kind=SECTION_KIND[section],
                payload={
                    "section_name": section.value,
                    "values": _occurrence_values(section, index),
                },
                captured_at=capture.captured_at,
            )
            db.add(occurrence_source)
            await db.flush()
            occurrence = CRMContactSourceOccurrence(
                contact_id=contact.id,
                section_capture_id=capture.id,
                source_record_id=occurrence_source.id,
                occurrence_ordinal=1,
            )
            db.add(occurrence)
            await db.flush()
            occurrences[section] = occurrence
            occurrence_sources[section] = occurrence_source
    if artifacts:
        all_sources = [
            profile_source,
            position_source,
            *section_sources.values(),
            *occurrence_sources.values(),
        ]
        for source_index, source in enumerate(all_sources, 1):
            content = f"artifact-{index}-{source_index}".encode()
            artifact = CRMArchiveArtifact(
                source_path=f"{SECRET}/artifact/{index}/{source_index}",
                domain="kw_command",
                artifact_type="json",
                filename=f"{SECRET}-{source_index}.json",
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                text_preview=SECRET,
                content_bytes=content,
            )
            db.add(artifact)
            await db.flush()
            db.add(
                CRMSourceRecordArtifact(
                    source_record_id=source.id,
                    artifact_id=artifact.id,
                    relation="evidence",
                )
            )
    await db.flush()
    return EvidenceGraph(
        contact=contact,
        profile_source=profile_source,
        position_source=position_source,
        position=position,
        sections=sections,
        section_sources=section_sources,
        occurrences=occurrences,
        occurrence_sources=occurrence_sources,
    )


@pytest.mark.asyncio
async def test_internal_only_contact_has_truthful_zero_position_limitation(
    evidence_db: AsyncSession,
):
    contact = CRMContact(first_name="Internal", last_name="Only", stage="lead")
    evidence_db.add(contact)
    await evidence_db.flush()

    result = await _get_evidence(evidence_db, contact.id)

    assert result == ContactEvidence(
        contact_id=contact.id,
        provider_contact_rows=0,
        resolved_provider_identities=0,
        coalesced_aliases=0,
        lead_backed_contacts=0,
        reviewed_overlaps=0,
        legacy_only_contacts=0,
        capture_positions=(),
        section_matrix=(),
        sources=(),
        capture_quality="limitation",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("contact_id", [True, 0, -1, 1.0, "1"])
async def test_evidence_rejects_invalid_contact_id_before_sql(
    evidence_db: AsyncSession,
    contact_id: object,
):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    assert evidence_db.bind is not None
    event.listen(evidence_db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(ContactNotFound, match="contact does not exist"):
            await _get_evidence(evidence_db, contact_id)  # type: ignore[arg-type]
    finally:
        event.remove(evidence_db.bind.sync_engine, "before_cursor_execute", capture)
    assert statements == []


@pytest.mark.asyncio
async def test_evidence_missing_contact_is_safe_not_found(
    evidence_db: AsyncSession,
):
    with pytest.raises(ContactNotFound, match="contact does not exist"):
        await _get_evidence(evidence_db, 999_999)


@pytest.mark.asyncio
async def test_evidence_projects_exact_graph_counts_order_and_safe_artifacts(
    evidence_db: AsyncSession,
):
    graph = await _add_graph(
        evidence_db,
        1,
        occurrence_sections=tuple(ContactSection),
        reverse_sections=True,
        artifacts=True,
    )
    catalog_rows = (await evidence_db.scalars(select(CRMArchiveArtifact))).all()
    for catalog_row in catalog_rows:
        evidence_db.expunge(catalog_row)

    result = await _get_evidence(evidence_db, graph.contact.id)

    expected_sections = tuple(
        ContactSectionEvidence(
            capture_position_id=graph.position.id,
            section=section,
            source_record_id=graph.section_sources[section].id,
            capture_quality=CaptureQualityValue.COMPLETE,
            row_count=1,
            is_empty=False,
            limitation_codes=(),
        )
        for section in ContactSection
    )
    assert result.contact_id == graph.contact.id
    assert (
        result.provider_contact_rows,
        result.resolved_provider_identities,
        result.coalesced_aliases,
        result.lead_backed_contacts,
        result.reviewed_overlaps,
        result.legacy_only_contacts,
    ) == (1, 1, 0, 0, 0, 0)
    assert result.capture_positions == (
        ContactCaptureEvidence(
            capture_position_id=graph.position.id,
            capture_ordinal=1,
            source_record_id=graph.position_source.id,
            capture_quality=CaptureQualityValue.COMPLETE,
            sections=expected_sections,
        ),
    )
    assert result.section_matrix == expected_sections
    expected_source_ids = sorted(
        {
            graph.profile_source.id,
            graph.position_source.id,
            *(source.id for source in graph.section_sources.values()),
            *(source.id for source in graph.occurrence_sources.values()),
        }
    )
    assert [source.source_record_id for source in result.sources] == expected_source_ids
    assert all(len(source.artifacts) == 1 for source in result.sources)
    assert all(
        isinstance(source, ContactSourceMetadata)
        and isinstance(source.artifacts[0], ContactArtifactMetadata)
        and source.artifacts[0].content_href
        == f"/api/v1/command/archive/artifacts/{source.artifacts[0].artifact_id}/content"
        for source in result.sources
    )
    assert result.capture_quality == "complete"
    assert not any(
        isinstance(value, CRMArchiveArtifact)
        for value in evidence_db.identity_map.values()
    )
    assert SECRET not in repr(result)
    assert SECRET not in repr(asdict(result))


@pytest.mark.asyncio
async def test_evidence_derives_global_lead_and_reviewed_overlap_counts(
    evidence_db: AsyncSession,
):
    reviewed = await _add_graph(evidence_db, 1, lead_id=1)
    await _add_graph(evidence_db, 2, lead_id=2)
    evidence_db.add(Lead(id=3, name="Synthetic lead 3"))
    await evidence_db.flush()
    lead_only = CRMContact(
        first_name="Legacy", last_name="Only", stage="lead", lead_id=3
    )
    evidence_db.add(lead_only)
    await evidence_db.flush()
    evidence_db.add_all(
        [
            CRMContactAuditEvent(
                contact_id=reviewed.contact.id,
                actor_subject="synthetic-actor",
                action="command_contact_overlap_reviewed",
                before_json="{}",
                after_json="{}",
            ),
            CRMContactAuditEvent(
                contact_id=reviewed.contact.id,
                actor_subject="synthetic-actor",
                action="command_contact_overlap_reviewed",
                before_json="not parsed",
                after_json="not parsed",
            ),
            CRMContactAuditEvent(
                contact_id=lead_only.id,
                actor_subject="synthetic-actor",
                action="command_contact_overlap_reviewed",
                before_json="{}",
                after_json="{}",
            ),
        ]
    )
    await evidence_db.flush()

    result = await _get_evidence(evidence_db, reviewed.contact.id)

    assert (
        result.provider_contact_rows,
        result.resolved_provider_identities,
        result.coalesced_aliases,
        result.lead_backed_contacts,
        result.reviewed_overlaps,
        result.legacy_only_contacts,
    ) == (2, 2, 0, 3, 1, 2)


@pytest.mark.asyncio
async def test_evidence_quality_uses_requested_cells_only(
    evidence_db: AsyncSession,
):
    partial = await _add_graph(
        evidence_db,
        1,
        section_qualities={ContactSection.NOTES: "partial"},
    )
    await _add_graph(
        evidence_db,
        2,
        section_qualities={ContactSection.NOTES: "error"},
    )

    result = await _get_evidence(evidence_db, partial.contact.id)

    assert result.capture_quality == "partial"
    assert tuple(row.section for row in result.section_matrix) == tuple(ContactSection)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        "null",
        "{}",
        '{"source_contact_id":null}',
        '{"source_contact_id":"ABCDEF000000000000000001"}',
        '{"source_contact_id":"00000000000000000000000g"}',
    ],
)
async def test_evidence_rejects_invalid_canonical_profile_mapping_safely(
    evidence_db: AsyncSession,
    payload: str,
):
    graph = await _add_graph(evidence_db, 1)
    graph.profile_source.payload_json = payload
    await evidence_db.flush()

    with pytest.raises(ContactDataIntegrityError) as captured:
        await _get_evidence(evidence_db, graph.contact.id)

    assert SECRET not in str(captured.value)
    assert SECRET not in repr(captured.value)


@pytest.mark.asyncio
async def test_evidence_rejects_duplicate_profile_resolution_and_aliases(
    evidence_db: AsyncSession,
):
    first = await _add_graph(evidence_db, 1)
    duplicate = _source(
        99_001,
        kind="contact_profile",
        payload={"source_contact_id": first.position.source_contact_id},
        evidence_level="observed_record",
    )
    evidence_db.add(duplicate)
    await evidence_db.flush()
    evidence_db.add(
        CRMEntitySource(
            entity_type="contact",
            entity_id=first.contact.id,
            source_record_id=duplicate.id,
        )
    )
    await evidence_db.flush()

    with pytest.raises(ContactDataIntegrityError, match="evidence graph is invalid"):
        await _get_evidence(evidence_db, first.contact.id)

    await evidence_db.delete(duplicate)
    await evidence_db.flush()
    second_source = _source(
        99_002,
        kind="contact_capture_position",
        payload={"capture_ordinal": 2},
    )
    evidence_db.add(second_source)
    await evidence_db.flush()
    evidence_db.add(
        CRMContactCapturePosition(
            contact_id=first.contact.id,
            source_record_id=second_source.id,
            bundle_fingerprint="f" * 64,
            capture_ordinal=2,
            source_contact_id=first.position.source_contact_id,
            captured_at=NOW,
            capture_quality="complete",
            limitations_json="[]",
        )
    )
    await evidence_db.flush()

    with pytest.raises(ContactDataIntegrityError, match="evidence graph is invalid"):
        await _get_evidence(evidence_db, first.contact.id)


@pytest.mark.asyncio
async def test_evidence_rejects_missing_eight_cell_matrix(
    evidence_db: AsyncSession,
):
    graph = await _add_graph(evidence_db, 1)
    await evidence_db.delete(graph.sections[ContactSection.NOTES])
    await evidence_db.flush()

    with pytest.raises(ContactDataIntegrityError, match="evidence graph is invalid"):
        await _get_evidence(evidence_db, graph.contact.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quality", "row_count", "is_empty"),
    [
        ("complete", 0, False),
        ("complete", 1, True),
        ("complete", -1, False),
        ("unknown", 0, True),
    ],
)
async def test_evidence_rejects_contradictory_section_cells(
    evidence_db: AsyncSession,
    quality: str,
    row_count: int,
    is_empty: bool,
):
    graph = await _add_graph(evidence_db, 1)
    await evidence_db.execute(text("PRAGMA ignore_check_constraints=ON"))
    section = graph.sections[ContactSection.NOTES]
    section.capture_quality = quality
    section.row_count = row_count
    section.is_empty = is_empty
    await evidence_db.flush()

    with pytest.raises(ContactDataIntegrityError, match="evidence graph is invalid"):
        await _get_evidence(evidence_db, graph.contact.id)


@pytest.mark.asyncio
async def test_evidence_rejects_row_count_that_disagrees_with_owned_occurrences(
    evidence_db: AsyncSession,
):
    graph = await _add_graph(evidence_db, 1)
    graph.sections[ContactSection.NOTES].row_count = 1
    graph.sections[ContactSection.NOTES].is_empty = False
    await evidence_db.flush()

    with pytest.raises(ContactDataIntegrityError, match="evidence graph is invalid"):
        await _get_evidence(evidence_db, graph.contact.id)


async def _captured_evidence_call(
    db: AsyncSession,
    contact_id: int,
) -> tuple[ContactEvidence, tuple[str, ...], int]:
    statements: list[str] = []
    flushes = 0

    def capture(_connection, _cursor, statement, params, _context, _many):
        statements.append(f"{statement}\nPARAMS={params!r}")

    def before_flush(_session, _flush_context, _instances):
        nonlocal flushes
        flushes += 1

    assert db.bind is not None
    event.listen(db.bind.sync_engine, "before_cursor_execute", capture)
    event.listen(db.sync_session, "before_flush", before_flush)
    try:
        result = await _get_evidence(db, contact_id)
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", capture)
        event.remove(db.sync_session, "before_flush", before_flush)
    return result, tuple(statements), flushes


@pytest.mark.asyncio
async def test_evidence_query_count_is_fixed_at_one_and_101_global_positions(
    evidence_db: AsyncSession,
):
    requested = await _add_graph(evidence_db, 1, artifacts=True)
    pending = CRMContact(first_name="Pending", last_name="Caller", stage="lead")
    evidence_db.add(pending)

    one, one_statements, one_flushes = await _captured_evidence_call(
        evidence_db, requested.contact.id
    )

    assert len(one_statements) == 7
    assert one_flushes == 0
    assert pending in evidence_db.new and pending.id is None
    evidence_db.expunge(pending)
    for index in range(2, 102):
        await _add_graph(evidence_db, index, artifacts=True)
    pending = CRMContact(first_name="Pending", last_name="Scale", stage="lead")
    evidence_db.add(pending)

    many, many_statements, many_flushes = await _captured_evidence_call(
        evidence_db, requested.contact.id
    )

    assert len(many_statements) == len(one_statements) == 7
    assert many_flushes == 0
    assert pending in evidence_db.new and pending.id is None
    assert one.provider_contact_rows == 1
    assert many.provider_contact_rows == 101
    assert many.resolved_provider_identities == 101
    assert many.coalesced_aliases == 0
    assert len(many.capture_positions) == 1
    assert len(many.section_matrix) == 8
    assert len(many.sources) == 10
    artifact_sql = next(
        statement
        for statement in many_statements
        if "crm_source_record_artifacts" in statement
    )
    assert artifact_sql.count("crm_archive_artifacts.content_bytes") == 1
    assert "length(crm_archive_artifacts.content_bytes)" in artifact_sql.lower()
    assert SECRET not in "\n".join(many_statements)


@pytest.mark.asyncio
async def test_evidence_allows_timeline_payload_but_strictly_projects_other_tabs(
    evidence_db: AsyncSession,
):
    graph = await _add_graph(
        evidence_db,
        1,
        occurrence_sections=(ContactSection.TIMELINE, ContactSection.NOTES),
    )
    graph.occurrence_sources[ContactSection.TIMELINE].payload_json = "not json"
    await evidence_db.flush()

    result = await _get_evidence(evidence_db, graph.contact.id)

    assert result.section_matrix[0].section is ContactSection.TIMELINE
    graph.occurrence_sources[ContactSection.NOTES].payload_json = "not json"
    await evidence_db.flush()
    with pytest.raises(ContactDataIntegrityError) as captured:
        await _get_evidence(evidence_db, graph.contact.id)
    assert SECRET not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limitations",
    [
        "{}",
        "null",
        '["duplicate","duplicate"]',
        '[" leading"]',
        '["trailing "]',
        '["valid",1]',
        '["valid",NaN]',
        '[ "noncanonical" ]',
    ],
)
async def test_evidence_rejects_noncanonical_or_invalid_limitations(
    evidence_db: AsyncSession,
    limitations: str,
):
    graph = await _add_graph(evidence_db, 1)
    graph.sections[ContactSection.NOTES].limitations_json = limitations
    await evidence_db.flush()

    with pytest.raises(ContactDataIntegrityError, match="evidence graph is invalid"):
        await _get_evidence(evidence_db, graph.contact.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("quality", ["partial", "shell", "error"])
async def test_zero_row_nonempty_is_preserved_for_incomplete_capture_quality(
    evidence_db: AsyncSession,
    quality: str,
):
    graph = await _add_graph(
        evidence_db,
        1,
        section_qualities={ContactSection.NOTES: quality},
    )
    graph.sections[ContactSection.NOTES].is_empty = False
    await evidence_db.flush()

    result = await _get_evidence(evidence_db, graph.contact.id)

    expected = "partial" if quality == "partial" else "limitation"
    assert result.capture_quality == expected
    note = next(
        row for row in result.section_matrix if row.section is ContactSection.NOTES
    )
    assert note.row_count == 0 and note.is_empty is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["occurrence", "position_source", "section_source"])
async def test_evidence_rejects_cross_contact_or_wrong_domain_context(
    evidence_db: AsyncSession,
    mismatch: str,
):
    graph = await _add_graph(
        evidence_db, 1, occurrence_sections=(ContactSection.NOTES,)
    )
    if mismatch == "occurrence":
        other = CRMContact(first_name="Other", last_name="Contact", stage="lead")
        evidence_db.add(other)
        await evidence_db.flush()
        graph.occurrences[ContactSection.NOTES].contact_id = other.id
    elif mismatch == "position_source":
        graph.position_source.module = "wrong_module"
    else:
        graph.section_sources[ContactSection.NOTES].source_system = "wrong_system"
    await evidence_db.flush()

    with pytest.raises(ContactDataIntegrityError) as captured:
        await _get_evidence(evidence_db, graph.contact.id)
    assert SECRET not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "link_state",
    ["valid", "wrong_type", "dangling", "cross_contact", "multiple"],
)
async def test_evidence_validates_every_occurrence_entity_link_and_target(
    evidence_db: AsyncSession,
    link_state: str,
):
    graph = await _add_graph(
        evidence_db, 1, occurrence_sections=(ContactSection.NOTES,)
    )
    note_contact = graph.contact
    if link_state == "cross_contact":
        note_contact = CRMContact(first_name="Other", last_name="Owner", stage="lead")
        evidence_db.add(note_contact)
        await evidence_db.flush()
    note = CRMNote(contact_id=note_contact.id, body="Synthetic note")
    evidence_db.add(note)
    await evidence_db.flush()
    entity_type = "note"
    entity_id = note.id
    if link_state == "wrong_type":
        entity_type = "task"
    elif link_state == "dangling":
        entity_id = 999_999
    evidence_db.add(
        CRMEntitySource(
            entity_type=entity_type,
            entity_id=entity_id,
            source_record_id=graph.occurrence_sources[ContactSection.NOTES].id,
        )
    )
    if link_state == "multiple":
        task = CRMTask(contact_id=graph.contact.id, title="Synthetic task")
        evidence_db.add(task)
        await evidence_db.flush()
        evidence_db.add(
            CRMEntitySource(
                entity_type="task",
                entity_id=task.id,
                source_record_id=graph.occurrence_sources[ContactSection.NOTES].id,
            )
        )
    await evidence_db.flush()

    if link_state == "valid":
        result = await _get_evidence(evidence_db, graph.contact.id)
        assert graph.occurrence_sources[ContactSection.NOTES].id in {
            source.source_record_id for source in result.sources
        }
    else:
        with pytest.raises(ContactDataIntegrityError) as captured:
            await _get_evidence(evidence_db, graph.contact.id)
        assert SECRET not in str(captured.value)


@pytest.mark.asyncio
async def test_evidence_validates_timeline_event_link_without_parsing_body(
    evidence_db: AsyncSession,
):
    graph = await _add_graph(
        evidence_db, 1, occurrence_sections=(ContactSection.TIMELINE,)
    )
    source = graph.occurrence_sources[ContactSection.TIMELINE]
    source.payload_json = "not json"
    timeline = CRMContactTimelineEvent(
        contact_id=graph.contact.id,
        source_record_id=source.id,
        source_system="kw_command",
        source_event_key="synthetic-timeline-event",
        kind="note",
        title="Synthetic timeline event",
        body=SECRET,
        occurred_at=NOW,
        attributes_json="{}",
    )
    evidence_db.add(timeline)
    await evidence_db.flush()
    evidence_db.add(
        CRMEntitySource(
            entity_type="contact_timeline_event",
            entity_id=timeline.id,
            source_record_id=source.id,
        )
    )
    await evidence_db.flush()

    result = await _get_evidence(evidence_db, graph.contact.id)

    assert source.id in {metadata.source_record_id for metadata in result.sources}
    assert SECRET not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("link_state", ["missing", "cross_contact", "dangling"])
async def test_evidence_rejects_invalid_profile_ownership(
    evidence_db: AsyncSession,
    link_state: str,
):
    graph = await _add_graph(evidence_db, 1)
    link = await evidence_db.scalar(
        select(CRMEntitySource).where(
            CRMEntitySource.source_record_id == graph.profile_source.id
        )
    )
    assert link is not None
    if link_state == "missing":
        await evidence_db.delete(link)
    elif link_state == "cross_contact":
        other = CRMContact(first_name="Other", last_name="Owner", stage="lead")
        evidence_db.add(other)
        await evidence_db.flush()
        link.entity_id = other.id
    else:
        link.entity_id = 999_999
    await evidence_db.flush()

    with pytest.raises(ContactDataIntegrityError) as captured:
        await _get_evidence(evidence_db, graph.contact.id)
    assert SECRET not in str(captured.value)


@pytest.mark.asyncio
async def test_artifact_null_blob_metadata_remains_available_and_ordered(
    evidence_db: AsyncSession,
):
    graph = await _add_graph(evidence_db, 1)
    first = CRMArchiveArtifact(
        id=902,
        source_path=f"{SECRET}/null",
        domain="kw_command",
        artifact_type="html",
        filename=SECRET,
        sha256="b" * 64,
        size_bytes=4_321,
        text_preview=SECRET,
        content_bytes=None,
    )
    second_content = SECRET.encode()
    second = CRMArchiveArtifact(
        id=901,
        source_path=f"{SECRET}/blob",
        domain="kw_command",
        artifact_type="json",
        filename=SECRET,
        sha256=hashlib.sha256(second_content).hexdigest(),
        size_bytes=len(second_content),
        text_preview=SECRET,
        content_bytes=second_content,
    )
    evidence_db.add_all([first, second])
    await evidence_db.flush()
    evidence_db.add_all(
        [
            CRMSourceRecordArtifact(
                source_record_id=graph.profile_source.id,
                artifact_id=first.id,
                relation="evidence",
            ),
            CRMSourceRecordArtifact(
                source_record_id=graph.profile_source.id,
                artifact_id=second.id,
                relation="evidence",
            ),
        ]
    )
    await evidence_db.flush()

    result = await _get_evidence(evidence_db, graph.contact.id)

    profile = next(
        source
        for source in result.sources
        if source.source_record_id == graph.profile_source.id
    )
    assert tuple(artifact.artifact_id for artifact in profile.artifacts) == (901, 902)
    assert profile.artifacts[1].size_bytes == 4_321
    assert SECRET not in repr(profile)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("artifact_type", " json"),
        ("artifact_type", ""),
        ("sha256", "A" * 64),
        ("sha256", "a" * 63),
        ("size_bytes", -1),
        ("size_bytes", 999),
    ],
)
async def test_evidence_rejects_invalid_artifact_catalog_metadata_safely(
    evidence_db: AsyncSession,
    column: str,
    value: object,
):
    graph = await _add_graph(evidence_db, 1, artifacts=True)
    artifact_id = await evidence_db.scalar(
        select(CRMSourceRecordArtifact.artifact_id)
        .where(CRMSourceRecordArtifact.source_record_id == graph.profile_source.id)
        .limit(1)
    )
    assert artifact_id is not None
    await evidence_db.execute(
        text(f"UPDATE crm_archive_artifacts SET {column}=:value WHERE id=:id"),
        {"value": value, "id": artifact_id},
    )

    with pytest.raises(ContactDataIntegrityError) as captured:
        await _get_evidence(evidence_db, graph.contact.id)
    assert SECRET not in str(captured.value)
