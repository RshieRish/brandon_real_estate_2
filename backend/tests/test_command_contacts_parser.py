"""Pure parser tests for recovered Command contact evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path

import pytest

from models.command_provenance import CaptureQuality, EvidenceLevel
from services.command_contact_identity import IdentityConflict
from services.command_parsers.contact_extractors import (
    CONTACT_SECTIONS,
    ContactParseError,
    ParsedCelebration,
    canonical_occurrence_key,
    extract_source_contact_id,
    strip_application_boilerplate,
)
from services.command_parsers.contacts import ContactsParser
from services.command_provenance import ArchiveArtifactInput


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "command_contacts"


def artifacts_from(root: Path = FIXTURE_ROOT) -> tuple[ArchiveArtifactInput, ...]:
    artifacts = []
    for artifact_id, path in enumerate(
        sorted(item for item in root.rglob("*") if item.is_file()),
        start=1,
    ):
        content = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        artifacts.append(
            ArchiveArtifactInput(
                id=artifact_id,
                source_path=relative,
                domain="kw_command",
                artifact_type=path.suffix.removeprefix(".") or "unknown",
                filename=path.name,
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                content_bytes=content,
            )
        )
    return tuple(artifacts)


@pytest.fixture
def bundle() -> tuple[ArchiveArtifactInput, ...]:
    return artifacts_from()


def source_record(result, source_key: str):
    return next(record for record in result.records if record.source_key == source_key)


def replace_json_artifact(
    bundle: tuple[ArchiveArtifactInput, ...],
    source_path: str,
    transform,
) -> tuple[ArchiveArtifactInput, ...]:
    replaced = []
    for artifact in bundle:
        if artifact.source_path != source_path:
            replaced.append(artifact)
            continue
        payload = json.loads((artifact.content_bytes or b"").decode())
        transform(payload)
        content = json.dumps(payload, sort_keys=True).encode()
        replaced.append(
            replace(
                artifact,
                content_bytes=content,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    return tuple(replaced)


def test_extract_source_contact_id_requires_canonical_contact_url():
    assert (
        extract_source_contact_id(
            "https://console.command.kw.com/command/contacts/"
            "63ac84e09655a08ec4d5d3ef?page=2"
        )
        == "63ac84e09655a08ec4d5d3ef"
    )
    with pytest.raises(ContactParseError):
        extract_source_contact_id("https://example.com/contacts/not-an-id")


@pytest.mark.parametrize(
    "url",
    [
        "http://console.command.kw.com/command/contacts/63ac84e09655a08ec4d5d3ef",
        "https://console.command.kw.com/command/contacts/63AC84E09655A08EC4D5D3EF",
        "https://console.command.kw.com/command/contacts/63ac84e09655a08ec4d5d3ef/extra",
    ],
)
def test_extract_source_contact_id_rejects_noncanonical_variants(url):
    with pytest.raises(ContactParseError):
        extract_source_contact_id(url)


def test_parsed_celebration_is_frozen_and_slotted():
    value = ParsedCelebration(8, 30, None, "sentinel", "1900-08-30")
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.year = 1900


def test_strip_application_boilerplate_stops_before_overlay_content():
    text = "Profile fact\nWelcome to KWIQ\nsecret overlay fact"
    assert strip_application_boilerplate(text) == "Profile fact"


def test_canonical_occurrence_key_is_mapping_order_stable_and_ordinal_scoped():
    first = canonical_occurrence_key({"b": [2, 1], "a": "x"}, 1)
    second = canonical_occurrence_key({"a": "x", "b": [2, 1]}, 1)
    assert first == second
    assert first != canonical_occurrence_key({"a": "x", "b": [2, 1]}, 2)
    assert len(first) == 64


def test_parser_emits_one_profile_one_position_and_eight_sections_per_position(
    bundle,
):
    result = ContactsParser().parse(bundle, "contacts-v1")
    kinds = Counter(record.record_kind for record in result.records)
    assert kinds["contact_profile"] == 3
    assert kinds["contact_capture_position"] == 3
    assert kinds["contact_section_capture"] == 24
    assert result.metrics.observed_count == 2
    assert result.metrics.rendered_count == 3
    assert result.metrics.normalized_count == 0
    assert result.metrics.details["provider_contact_rows"] == 3
    assert result.metrics.details["capture_positions"] == 3
    assert result.metrics.details["section_artifacts"] == 24
    assert result.metrics.details["section_counts"] == {
        section: 3 for section in CONTACT_SECTIONS
    }
    assert result.metrics.details["identity_clusters"] == 2
    assert result.metrics.details["identity_aliases_coalesced"] == 1
    assert result.metrics.details["ambiguous_identities"] == 0
    assert result.metrics.details["unmatched_provider_rows"] == 0
    assert len(result.metrics.details["identity_cluster_hashes"]) == 2


def test_parser_marks_1900_birth_year_as_sentinel_without_inventing_a_date(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    profile = source_record(result, "contact:63ac84e09655a08ec4d5d3ef")
    assert profile.payload["birthday"] == {
        "month": 8,
        "day": 30,
        "year": None,
        "year_quality": "sentinel",
        "raw": "1900-08-30",
    }
    assert profile.payload["anniversary"] == {
        "month": 9,
        "day": 23,
        "year": 2022,
        "year_quality": "verified",
        "raw": "2022-09-23",
    }
    assert result.metrics.details["fabricated_celebrations"] == 0


def test_parser_preserves_yearless_and_displayed_placeholder_evidence(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    second = source_record(result, "contact:63ac84ec62224587b69e9bb4")
    third = source_record(result, "contact:63ac84f03f774d538e8593ca")
    assert second.payload["raw_fields"]["birthday"] == "--"
    assert second.payload["birthday"]["raw"] == "--"
    assert second.payload["birthday"]["year_quality"] == "unknown"
    assert third.payload["birthday"] == {
        "month": 4,
        "day": 15,
        "year": None,
        "year_quality": "yearless",
        "raw": "April 15",
    }
    assert third.payload["primary_email"] is None
    assert third.payload["primary_phone"] == "978-555-0199"


def test_structured_profile_precedes_conflicting_html_fallback(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    first = source_record(result, "contact:63ac84e09655a08ec4d5d3ef")
    assert first.payload["primary_email"] == "avery@example.test"
    assert first.payload["profile_source"] == "structured_json"


def test_profile_identity_candidate_uses_only_explicit_e164_phone(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    first = source_record(result, "contact:63ac84e09655a08ec4d5d3ef")
    second = source_record(result, "contact:63ac84ec62224587b69e9bb4")
    assert first.payload["identity_candidate"]["e164_phone"] == "+19785550101"
    assert second.payload["primary_phone"] == "+1 978 555 0101"
    assert second.payload["identity_candidate"]["e164_phone"] is None


def test_parser_blocks_conflicting_strong_identity_instead_of_falling_back(bundle):
    changed = []
    path = "kw_command_repaired/contacts/details/0000002.html"
    for artifact in bundle:
        if artifact.source_path != path:
            changed.append(artifact)
            continue
        content = (artifact.content_bytes or b"").replace(
            b"+1 978 555 0101", b"+19785550102"
        )
        changed.append(
            replace(
                artifact,
                content_bytes=content,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )

    with pytest.raises(IdentityConflict, match="conflicting phone") as captured:
        ContactsParser().parse(tuple(changed), "contacts-v1")
    assert captured.value.ambiguous_identities == 1


def test_parser_uses_accessibility_snapshot_when_visible_text_is_absent(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    section = source_record(
        result,
        "position:0000002:section:timeline",
    )
    assert section.payload["text_source"] == "accessibility_snapshot"
    assert "Avery Lake" in section.payload["exposed_text"]


def test_parser_does_not_treat_supporting_html_and_text_as_extra_occurrences(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    assert (
        Counter(record.record_kind for record in result.records)[
            "contact_section_capture"
        ]
        == 24
    )
    assert result.metrics.duplicate_content_count == 1


def test_parser_emits_child_rows_with_truthful_evidence_and_stable_keys(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    note = source_record(result, "contact:63ac84e09655a08ec4d5d3ef:note:note-1")
    task = next(
        record
        for record in result.records
        if record.source_key.startswith("contact:63ac84e09655a08ec4d5d3ef:task:to_do:")
    )
    smart_plan = next(
        record
        for record in result.records
        if record.source_key.startswith("contact:63ac84e09655a08ec4d5d3ef:smart-plan:")
    )
    assert note.evidence_level is EvidenceLevel.OBSERVED_RECORD
    assert task.evidence_level is EvidenceLevel.RENDERED_OCCURRENCE
    assert smart_plan.evidence_level is EvidenceLevel.RENDERED_OCCURRENCE
    assert task.payload["state"] == "to_do"
    assert note.artifact_paths == (
        "kw_command_repaired/contacts/nested/0000001/notes.json",
        "kw_command_repaired/contacts/sections/0000001/notes.html",
        "kw_command_repaired/contacts/sections/0000001/notes.json",
        "kw_command_repaired/contacts/sections/0000001/notes.txt",
    )


def test_completed_task_header_emits_every_rendered_completed_row(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    completed = [
        record
        for record in result.records
        if record.record_kind == "contact_task"
        and record.payload["state"] == "completed"
    ]
    assert len(completed) == 1
    assert completed[0].display_label == "Fixture completed task"
    assert completed[0].payload["values"] == {
        "title": "Fixture completed task",
        "assigned_to": "Fixture Owner",
        "priority": "None",
        "completed_date": "07/01/2026",
        "due_date": "06/30/2026",
        "completed_by": "Fixture Owner",
        "state": "completed",
    }
    assert completed[0].evidence_level is EvidenceLevel.RENDERED_OCCURRENCE


def test_accessibility_completed_table_emits_every_exposed_child_row(bundle):
    def completed_table(payload):
        payload.pop("rows", None)
        payload["visible_text"] = None
        payload[
            "accessibility_snapshot"
        ] = """- table:
  - rowgroup:
    - row "Task Sort Assigned To Priority Sort Date completed Sort Due Date Sort Completed by":
  - rowgroup:
    - row "First completed task BS Fixture Owner None 07/01/2026 06/30/2026 Fixture Owner":
      - cell "First completed task":
      - cell "BS Fixture Owner":
      - cell "None":
      - cell "07/01/2026":
      - cell "06/30/2026":
      - cell "Fixture Owner":
    - row "Second completed task BS Fixture Owner High 07/02/2026 07/01/2026 Fixture Owner":
      - cell "Second completed task":
      - cell "BS Fixture Owner":
      - cell "High":
      - cell "07/02/2026":
      - cell "07/01/2026":
      - cell "Fixture Owner":
"""

    changed = replace_json_artifact(
        bundle,
        "kw_command_repaired/contacts/sections/0000002/tasks/completed.json",
        completed_table,
    )
    result = ContactsParser().parse(changed, "contacts-v1")
    completed = [
        record
        for record in result.records
        if record.record_kind == "contact_task"
        and record.payload["capture_ordinal"] == "0000002"
        and record.payload["state"] == "completed"
    ]
    assert [record.display_label for record in completed] == [
        "First completed task",
        "Second completed task",
    ]
    assert [record.payload["values"]["completed_date"] for record in completed] == [
        "07/01/2026",
        "07/02/2026",
    ]


def test_only_profile_and_stable_note_id_are_observed_records(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    observed_children = [
        record
        for record in result.records
        if record.record_kind not in {"contact_profile"}
        and record.evidence_level is EvidenceLevel.OBSERVED_RECORD
    ]
    assert [
        (record.record_kind, record.source_key) for record in observed_children
    ] == [("contact_note", "contact:63ac84e09655a08ec4d5d3ef:note:note-1")]


def test_stable_ids_outside_note_remain_rendered_occurrences(bundle):
    def add_ids(payload):
        for row in payload["rows"]:
            row["id"] = "provider-row-id"

    changed = bundle
    for path in (
        "kw_command_repaired/contacts/sections/0000001/timeline.json",
        "kw_command_repaired/contacts/sections/0000001/smartplans.json",
        "kw_command_repaired/contacts/sections/0000001/tasks/to_do.json",
    ):
        changed = replace_json_artifact(changed, path, add_ids)
    result = ContactsParser().parse(changed, "contacts-v1")
    rows = [
        record
        for record in result.records
        if record.source_key.endswith("provider-row-id")
    ]
    assert {record.record_kind for record in rows} == {
        "contact_timeline_event",
        "contact_smart_plan",
        "contact_task",
    }
    assert all(
        record.evidence_level is EvidenceLevel.RENDERED_OCCURRENCE for record in rows
    )


def test_rendered_note_uses_matching_stable_nested_note_evidence(bundle):
    def rendered_note(payload):
        payload.pop("rows", None)
        payload["visible_text"] = (
            "Search Contacts\nAvery Lake\nNotes\nMost Recent\nAdd Note\n"
            "NOTE\n3:11 PM\nCreated\nBy Fixture Owner\n"
            "Fixture note\nSynthetic note body\nDelete\nEdit"
        )

    changed = replace_json_artifact(
        bundle,
        "kw_command_repaired/contacts/sections/0000001/notes.json",
        rendered_note,
    )
    result = ContactsParser().parse(changed, "contacts-v1")
    note = source_record(result, "contact:63ac84e09655a08ec4d5d3ef:note:note-1")
    assert note.evidence_level is EvidenceLevel.OBSERVED_RECORD
    assert note.payload["stable_id"] == "note-1"


def test_parser_records_partial_section_quality_and_limitations(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    section = source_record(
        result,
        "position:0000003:section:opportunities",
    )
    assert section.capture_quality is CaptureQuality.PARTIAL
    assert section.payload["limitations"] == (
        "capture ended while details were loading",
    )


def test_parser_extracts_rendered_opportunity_cards_without_structured_rows(bundle):
    def opportunity_capture(payload):
        payload.pop("rows")
        payload["visible_text"] = (
            "Search Contacts\nAvery Lake\nSaved Searches\nMost Recent\n"
            "All Opportunities\nCreate Opportunity\nDEC 12, 2025\n"
            "Lake - Buyer\nStage\nScheduled\nPhase\nAppointment\nBudget\n$0.00"
        )

    changed = replace_json_artifact(
        bundle,
        "kw_command_repaired/contacts/sections/0000001/opportunities.json",
        opportunity_capture,
    )
    result = ContactsParser().parse(changed, "contacts-v1")
    opportunity = next(
        record
        for record in result.records
        if record.record_kind == "contact_opportunity"
    )
    assert opportunity.display_label == "Lake - Buyer"
    assert opportunity.payload["values"]["stage"] == "Scheduled"
    assert opportunity.payload["values"]["phase"] == "Appointment"


def test_parser_extracts_rendered_saved_search_cards_without_structured_rows(bundle):
    def saved_search_capture(payload):
        payload.pop("rows")
        payload["visible_text"] = (
            "Search Contacts\nAvery Lake\nSaved Searches\n1\n"
            "Create Saved Search\nMap area\nCreated by: Avery Lake\n"
            "Price\n$600,000 or more\nBeds\n2 +"
        )

    changed = replace_json_artifact(
        bundle,
        "kw_command_repaired/contacts/sections/0000001/saved_searches.json",
        saved_search_capture,
    )
    result = ContactsParser().parse(changed, "contacts-v1")
    saved_search = next(
        record
        for record in result.records
        if record.record_kind == "contact_saved_search"
    )
    assert saved_search.display_label == "Map area"
    assert saved_search.payload["values"]["created_by"] == "Avery Lake"
    assert saved_search.payload["values"]["price"] == "$600,000 or more"


def test_parser_extracts_timeline_rows_from_accessibility_capture(bundle):
    def accessibility_timeline(payload):
        payload.pop("rows")
        payload["visible_text"] = None
        payload["accessibility_snapshot"] = (
            '- generic: Saved Searches\n- button "All Time": All Time\n'
            '- heading "Apr 2, 2026" [level=5]\n- generic: Note\n'
            "- generic: 8:20 PM\n- generic: Created\n"
            "- generic: By Fixture Owner\n- separator\n- generic: Fixture note\n"
            '- heading "Notifications" [level=2]'
        )

    changed = replace_json_artifact(
        bundle,
        "kw_command_repaired/contacts/sections/0000002/timeline.json",
        accessibility_timeline,
    )
    result = ContactsParser().parse(changed, "contacts-v1")
    events = [
        record
        for record in result.records
        if record.record_kind == "contact_timeline_event"
        and record.payload["capture_ordinal"] == "0000002"
    ]
    assert len(events) == 1
    assert events[0].payload["values"]["kind"] == "NOTE"
    assert "Fixture note" in events[0].payload["values"]["raw_lines"]


@pytest.mark.parametrize(
    ("path", "empty_text", "source_key"),
    [
        (
            "kw_command_repaired/contacts/sections/0000002/smartplans.json",
            "It looks like Avery Lake doesn’t have any SmartPlans yet.",
            "position:0000002:section:smart_plans",
        ),
        (
            "kw_command_repaired/contacts/sections/0000002/tasks/to_do.json",
            "No Tasks\nCreate a new task to start a to-do list for this Contact.",
            "position:0000002:section:tasks_to_do",
        ),
        (
            "kw_command_repaired/contacts/sections/0000002/notes.json",
            "Most Recent\nAdd Note",
            "position:0000002:section:notes",
        ),
    ],
)
def test_real_empty_state_variants_remain_complete_empty_sections(
    bundle, path, empty_text, source_key
):
    def replace_empty(payload):
        payload["visible_text"] = f"Search Contacts\nAvery Lake\n{empty_text}"
        payload.pop("accessibility_snapshot", None)
        payload.pop("rows", None)

    changed = replace_json_artifact(bundle, path, replace_empty)
    result = ContactsParser().parse(changed, "contacts-v1")
    section = source_record(result, source_key)
    assert section.payload["is_empty"] is True
    assert section.capture_quality is CaptureQuality.COMPLETE
    assert section.payload["row_count"] == 0


def test_section_and_child_link_all_deterministic_supporting_evidence(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    section = source_record(result, "position:0000001:section:notes")
    child = source_record(result, "contact:63ac84e09655a08ec4d5d3ef:note:note-1")
    expected = (
        "kw_command_repaired/contacts/nested/0000001/notes.json",
        "kw_command_repaired/contacts/sections/0000001/notes.html",
        "kw_command_repaired/contacts/sections/0000001/notes.json",
        "kw_command_repaired/contacts/sections/0000001/notes.txt",
    )
    assert section.artifact_paths == expected
    assert child.artifact_paths == expected


def test_profile_links_all_contributing_structured_and_rendered_artifacts(bundle):
    result = ContactsParser().parse(bundle, "contacts-v1")
    profile = source_record(result, "contact:63ac84e09655a08ec4d5d3ef")
    assert profile.artifact_paths == (
        "kw_command_repaired/contacts/details/0000001.html",
        "kw_command_repaired/contacts/nested/0000001/contact.json",
        "kw_command_repaired/contacts/sections/0000001/timeline.json",
    )


def test_parser_propagates_version_and_orders_output_stably(bundle):
    forward = ContactsParser().parse(bundle, "contacts-v7")
    reverse = ContactsParser().parse(tuple(reversed(bundle)), "contacts-v7")
    assert all(record.parser_version == "contacts-v7" for record in forward.records)
    assert tuple(record.identity for record in forward.records) == tuple(
        record.identity for record in reverse.records
    )
    assert tuple(record.payload_json for record in forward.records) == tuple(
        record.payload_json for record in reverse.records
    )
    assert forward.metrics.details == reverse.metrics.details


def test_parser_rejects_missing_canonical_section(bundle):
    incomplete = tuple(
        artifact
        for artifact in bundle
        if artifact.source_path
        != "kw_command_repaired/contacts/sections/0000002/smartplans.json"
    )
    with pytest.raises(ContactParseError, match="missing canonical section"):
        ContactsParser().parse(incomplete, "contacts-v1")


def test_parser_rejects_duplicate_canonical_capture_path(bundle):
    duplicate = replace(bundle[0], id=999)
    with pytest.raises(ContactParseError, match="duplicate artifact path"):
        ContactsParser().parse((*bundle, duplicate), "contacts-v1")


def test_parser_rejects_ambiguous_source_ids_within_one_position(bundle):
    ambiguous = replace_json_artifact(
        bundle,
        "kw_command_repaired/contacts/sections/0000002/notes.json",
        lambda payload: payload.__setitem__(
            "url",
            "https://console.command.kw.com/command/contacts/"
            "63ac84f03f774d538e8593ca",
        ),
    )
    with pytest.raises(ContactParseError, match="ambiguous source contact IDs"):
        ContactsParser().parse(ambiguous, "contacts-v1")


@pytest.mark.parametrize("parser_version", ["", " \t", None])
def test_parser_rejects_blank_version(bundle, parser_version):
    with pytest.raises(ContactParseError, match="parser_version"):
        ContactsParser().parse(bundle, parser_version)
