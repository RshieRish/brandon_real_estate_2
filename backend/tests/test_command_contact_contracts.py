from __future__ import annotations

import base64
import json
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import get_args, get_type_hints

import pytest

import services.command_contact_contracts as contact_contracts
from services.command_contact_contracts import (
    UNSET,
    CaptureQualityValue,
    ContactBulkAddTag,
    ContactBulkCommand,
    ContactBulkResult,
    ContactBulkSetStage,
    ContactCreateCommand,
    ContactDirectoryFilters,
    ContactImportCommand,
    ContactImportRowCommand,
    ContactMaterialized,
    ContactMutationResult,
    ContactNoteCreateCommand,
    ContactOriginFilter,
    ContactSavedSearchCreateCommand,
    ContactSection,
    ContactSmartView,
    ContactSortKey,
    ContactSourceFilter,
    ContactUpdateCommand,
    MaterializationStatus,
    SortDirection,
    TimelineCursorV1,
    TimelineOrigin,
    WorkspaceMutationResult,
    canonical_contact_audit_json,
    decode_timeline_cursor,
    encode_timeline_cursor,
    redact_contact_audit_value,
    timeline_position_is_after,
)


def test_materialized_section_entity_types_exclude_timeline():
    entity_type = get_type_hints(ContactMaterialized)["entity_type"]
    assert get_args(entity_type) == (
        "note",
        "saved_search",
        "task",
        "smart_plan",
        "opportunity",
    )


def test_exact_enum_values_are_stable():
    assert tuple(ContactSection) == tuple(
        ContactSection(value)
        for value in (
            "timeline", "opportunities", "smart_plans", "notes",
            "saved_searches", "tasks_to_do", "tasks_completed", "tasks_archived",
        )
    )
    assert {item.value for item in CaptureQualityValue} == {
        "complete", "partial", "shell", "error",
    }
    assert {item.value for item in MaterializationStatus} == {
        "source_only", "materialized",
    }
    assert {item.value for item in TimelineOrigin} == {
        "recovered", "internal_crm", "legacy_lead", "booking",
    }


def test_timeline_cursor_is_byte_exact_unpadded_and_round_trips():
    cursor = TimelineCursorV1(
        null_rank=0,
        occurred_at=datetime(2026, 7, 27, 20, 1, 2, 3456, tzinfo=UTC),
        origin_rank=2,
        entity_id=17,
    )
    expected_json = b'{"v":1,"n":0,"t":"2026-07-27T20:01:02.003456Z","o":2,"i":17}'
    expected = base64.urlsafe_b64encode(expected_json).decode().rstrip("=")
    assert encode_timeline_cursor(cursor) == expected
    assert "=" not in expected
    assert decode_timeline_cursor(expected) == cursor


@pytest.mark.parametrize(
    "raw",
    [
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1}=',
        '{"n":0,"v":1,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1}',
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02Z","o":0,"i":1}',
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02.000000+00:00","o":0,"i":1}',
        '{"v":1,"n":1,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1}',
        '{"v":1,"n":0,"t":null,"o":0,"i":1}',
        '{"v":1,"n":false,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1}',
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02.000000Z","o":true,"i":1}',
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":0}',
        '{"v":2,"n":0,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1}',
        '{"v":1,"n":0,"t":"2026-07-27T20:01:02.000000Z","o":0,"i":1,"x":2}',
        "a",
    ],
)
def test_timeline_cursor_rejects_every_noncanonical_form_without_echo(raw):
    encoded = raw if raw.endswith("=") else base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    with pytest.raises(ValueError) as error:
        decode_timeline_cursor(encoded)
    assert encoded not in str(error.value)


def test_null_cursor_and_after_semantics_match_total_order():
    cursor = TimelineCursorV1(1, None, 1, 50)
    assert decode_timeline_cursor(encode_timeline_cursor(cursor)) == cursor
    assert timeline_position_is_after(cursor, null_rank=1, occurred_at=None, origin_rank=2, entity_id=999)
    assert timeline_position_is_after(cursor, null_rank=1, occurred_at=None, origin_rank=1, entity_id=49)
    assert not timeline_position_is_after(cursor, null_rank=0, occurred_at=datetime.now(UTC), origin_rank=3, entity_id=1)


def test_directory_filters_trim_and_canonicalize_set_like_fields():
    value = ContactDirectoryFilters(
        query="  Lake  ",
        tag_ids=(9, 2, 9),
        sources=(ContactSourceFilter.LEGACY_LEAD, ContactSourceFilter.KW_COMMAND, ContactSourceFilter.KW_COMMAND),
        origins=(ContactOriginFilter.LEAD_BACKED, ContactOriginFilter.RECOVERED, ContactOriginFilter.LEAD_BACKED),
        smart_view=ContactSmartView.NEVER_CONTACTED,
        sort=ContactSortKey.UPDATED_AT,
        direction=SortDirection.DESC,
    )
    assert value.query == "Lake"
    assert value.tag_ids == (2, 9)
    assert value.sources == (ContactSourceFilter.KW_COMMAND, ContactSourceFilter.LEGACY_LEAD)
    assert value.origins == (
        ContactOriginFilter.LEAD_BACKED,
        ContactOriginFilter.RECOVERED,
    )
    with pytest.raises(FrozenInstanceError):
        value.page = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0}, {"page_size": 101}, {"query": "x" * 201},
        {"owner_actor_id": "x" * 256}, {"tag_ids": (True,)},
        {"health_min": -1}, {"health_max": 101},
        {"health_min": 80, "health_max": 20}, {"birthday_month": 0},
        {"anniversary_month": 13},
    ],
)
def test_directory_filters_reject_invalid_boundaries(kwargs):
    with pytest.raises(ValueError):
        ContactDirectoryFilters(**kwargs)


def test_mutation_commands_enforce_exact_bounds_and_deep_freeze_criteria():
    created = ContactCreateCommand("  Avery  ", last_name=" Lake ", stage=" lead ")
    assert (created.first_name, created.last_name, created.stage) == ("Avery", "Lake", "lead")
    criteria = {"nested": {"tags": ["one", "two"]}}
    search = ContactSavedSearchCreateCommand("  My search ", criteria)
    criteria["nested"] = {"changed": True}
    assert isinstance(search.criteria, MappingProxyType)
    assert search.criteria["nested"]["tags"] == ("one", "two")
    update = ContactUpdateCommand(email=None)
    assert update.email is None
    assert update.first_name is UNSET


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ContactCreateCommand(""),
        lambda: ContactCreateCommand("x" * 121),
        lambda: ContactCreateCommand("A", email="x" * 256),
        lambda: ContactCreateCommand("A", phone="x" * 51),
        lambda: ContactCreateCommand("A", stage=""),
        lambda: ContactUpdateCommand(),
        lambda: ContactUpdateCommand(first_name=None),
        lambda: ContactNoteCreateCommand(""),
        lambda: ContactNoteCreateCommand("x" * 20_001),
        lambda: ContactSavedSearchCreateCommand("x" * 256, {}),
        lambda: ContactSavedSearchCreateCommand("ok", {"bad": float("nan")}),
        lambda: ContactBulkCommand((), ContactBulkSetStage("set_stage", "lead")),
        lambda: ContactBulkCommand((1, 1), ContactBulkSetStage("set_stage", "lead")),
        lambda: ContactBulkCommand(tuple(range(1, 202)), ContactBulkSetStage("set_stage", "lead")),
        lambda: ContactBulkCommand((1,), ContactBulkAddTag("add_tag", 0)),
        lambda: ContactImportCommand(()),
    ],
)
def test_mutation_commands_reject_invalid_or_ambiguous_input(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_import_rows_are_immutable_validated_and_limited():
    row = ContactImportRowCommand("A", "", None, None, "lead", date(2000, 1, 2), None)
    command = ContactImportCommand((row,))
    assert command.contacts == (row,)
    assert {field.name for field in fields(ContactCreateCommand)}.isdisjoint(
        {"lead_id", "source_record_id", "audit_event_id", "recovered_profile"}
    )


AUDIT_DOMAINS = {
    "first_name": "command-contact-audit-v1:first_name",
    "last_name": "command-contact-audit-v1:last_name",
    "email": "command-contact-audit-v1:email",
    "phone": "command-contact-audit-v1:phone",
    "note_body": "command-contact-audit-v1:note_body",
    "saved_search_name": "command-contact-audit-v1:saved_search_name",
    "saved_search_criteria": "command-contact-audit-v1:saved_search_criteria",
}


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(field: str, value: str | None) -> dict[str, object]:
    material = b"" if value is None else value.encode("utf-8")
    return {
        "length": len(material),
        "present": value is not None,
        "sha256": __import__("hashlib").sha256(
            AUDIT_DOMAINS[field].encode("ascii") + b"\0" + material
        ).hexdigest(),
    }


def _encoded_contact_fields(
    action: str,
    fields: tuple[str, ...],
    raw: dict[str, object],
) -> dict[str, object]:
    result: dict[str, object] = {
        "action": action,
        "changed_fields": sorted(fields),
    }
    for field in fields:
        value = raw[field]
        if field in {"first_name", "last_name", "email", "phone"}:
            result[field] = _fingerprint(field, value)  # type: ignore[arg-type]
        elif field in {"birthday", "anniversary"}:
            result[field] = value.isoformat() if value is not None else None
        else:
            result[field] = value
    return result


def test_audit_redaction_pins_ascii_domain_nul_and_utf8_byte_length():
    value = "Privaté"
    rendered = redact_contact_audit_value(value, domain=AUDIT_DOMAINS["first_name"])
    assert rendered == _fingerprint("first_name", value)
    assert rendered["length"] == len(value.encode("utf-8"))
    assert redact_contact_audit_value(
        None, domain=AUDIT_DOMAINS["email"]
    ) == _fingerprint("email", None)


@pytest.mark.parametrize(
    ("value", "domain"),
    [
        (b"private", AUDIT_DOMAINS["email"]),
        ({"private": True}, AUDIT_DOMAINS["email"]),
        (True, AUDIT_DOMAINS["email"]),
        (7, AUDIT_DOMAINS["email"]),
        ("private", "contact.email"),
        ("private", f" {AUDIT_DOMAINS['email']}"),
        ("private", f"{AUDIT_DOMAINS['email']} "),
        ("private", "command-contact-audit-v1:unknown"),
    ],
)
def test_audit_redaction_rejects_non_string_values_and_unlisted_domains(
    value, domain
):
    with pytest.raises((TypeError, ValueError)):
        redact_contact_audit_value(value, domain=domain)


CONTACT_AUDIT_CASES = (
    (
        "contact.created",
        {},
        {
            "anniversary": date(2020, 1, 2),
            "birthday": date(1990, 3, 4),
            "email": "private@example.test",
            "first_name": "Private",
            "last_name": "Person",
            "phone": "+15550000000",
            "stage": "lead",
        },
    ),
    (
        "contact.updated",
        {"changed_fields": ("first_name", "stage"), "stage": "lead", "first_name": "Old"},
        {"changed_fields": ("first_name", "stage"), "stage": "active", "first_name": "New"},
    ),
    (
        "contact.legacy_sync_applied",
        {},
        {
            "email": "private@example.test",
            "first_name": "Private",
            "last_name": "Lead",
            "phone": None,
            "stage": "lead",
            "lead_id": 17,
        },
    ),
    (
        "contact.legacy_sync_applied",
        {"activity_present": False, "lead_id": 17},
        {"activity_present": True, "activity_id": 31, "lead_id": 17},
    ),
    (
        "contact.legacy_import_applied",
        {},
        {
            "anniversary": None,
            "birthday": None,
            "email": "private@example.test",
            "first_name": "Private",
            "last_name": "Import",
            "phone": None,
            "stage": "lead",
        },
    ),
    (
        "contact.archive_import_applied",
        {},
        {
            "anniversary": None,
            "birthday": None,
            "email": "private@example.test",
            "first_name": "Private",
            "last_name": "Archive",
            "phone": None,
            "stage": "lead",
        },
    ),
    ("contact.bulk_stage_set", {"stage": "lead"}, {"stage": "active"}),
    ("contact.bulk_tag_added", {"present": False, "tag_id": 5}, {"present": True, "tag_id": 5}),
    ("contact.bulk_tag_removed", {"present": True, "tag_id": 5}, {"present": False, "tag_id": 5}),
    ("contact.tag_added", {"present": False, "tag_id": 5}, {"present": True, "tag_id": 5}),
    ("contact.tag_removed", {"present": True, "tag_id": 5}, {"present": False, "tag_id": 5}),
    ("contact.note_created", {"body": "private body", "note_id": 9, "present": False}, {"body": "private body", "note_id": 9, "present": True}),
    ("contact.note_deleted", {"body": "private body", "note_id": 9, "present": True}, {"body": "private body", "note_id": 9, "present": False}),
    ("contact.saved_search_created", {"criteria": '{"private":true}', "name": "Private search", "present": False, "search_id": 11}, {"criteria": '{"private":true}', "name": "Private search", "present": True, "search_id": 11}),
    ("contact.saved_search_deleted", {"criteria": '{"private":true}', "name": "Private search", "present": True, "search_id": 11}, {"criteria": '{"private":true}', "name": "Private search", "present": False, "search_id": 11}),
)


def _expected_audit_payload(action: str, payload: dict[str, object]) -> dict[str, object]:
    if not payload:
        return {}
    if action in {
        "contact.created",
        "contact.updated",
        "contact.legacy_import_applied",
        "contact.archive_import_applied",
    } or (
        action == "contact.legacy_sync_applied"
        and "activity_present" not in payload
    ):
        fields = tuple(payload.get("changed_fields", tuple(payload)))
        raw = {key: value for key, value in payload.items() if key != "changed_fields"}
        return _encoded_contact_fields(action, fields, raw)
    if action.startswith("contact.note_"):
        return {
            "action": action,
            "body": _fingerprint("note_body", payload["body"]),  # type: ignore[arg-type]
            "note_id": payload["note_id"],
            "present": payload["present"],
        }
    if action.startswith("contact.saved_search_"):
        return {
            "action": action,
            "criteria": _fingerprint("saved_search_criteria", payload["criteria"]),  # type: ignore[arg-type]
            "name": _fingerprint("saved_search_name", payload["name"]),  # type: ignore[arg-type]
            "present": payload["present"],
            "search_id": payload["search_id"],
        }
    return {"action": action, **payload}


@pytest.mark.parametrize(("action", "before", "after"), CONTACT_AUDIT_CASES)
def test_contact_audit_builder_snapshots_all_fifteen_action_shapes(
    action, before, after
):
    rendered_before = canonical_contact_audit_json(
        action=action, phase="before", payload=before
    )
    rendered_after = canonical_contact_audit_json(
        action=action, phase="after", payload=after
    )
    assert rendered_before == _canonical(_expected_audit_payload(action, before))
    assert rendered_after == _canonical(_expected_audit_payload(action, after))
    private_values = (
        "private@example.test",
        "+15550000000",
        "private body",
        "Private search",
        '{"private":true}',
    )
    assert all(value not in rendered_before + rendered_after for value in private_values)


@pytest.mark.parametrize(
    ("action", "phase", "payload"),
    [
        ("contact.created", "before", {"actor_subject": "7"}),
        ("contact.created", "after", {"first_name": "Private"}),
        ("contact.updated", "before", {"changed_fields": ("stage", "stage"), "stage": "lead"}),
        ("contact.updated", "before", {"changed_fields": ("stage", "first_name"), "stage": "lead", "first_name": "Private"}),
        ("contact.updated", "after", {"changed_fields": ("stage",), "stage": "lead", "email": "private"}),
        ("contact.tag_added", "before", {"present": False, "tag_id": 1, "lead_id": 2}),
        ("contact.bulk_stage_set", "before", {"stage": None}),
        ("contact.note_created", "before", {"body": b"private", "note_id": 1, "present": False}),
        ("command_contact_overlap_reviewed", "before", {}),
    ],
)
def test_contact_audit_builder_rejects_wrong_phase_shape_and_key_smuggling(
    action, phase, payload
):
    with pytest.raises((TypeError, ValueError)):
        canonical_contact_audit_json(action=action, phase=phase, payload=payload)


def test_workspace_saved_search_activity_builder_is_exact_and_actor_attributed():
    rendered = contact_contracts.canonical_workspace_saved_search_activity_json(
        actor_subject="7",
        search_id=11,
        name="Private search",
    )
    assert rendered == _canonical(
        {
            "action": "workspace.saved_search_deleted",
            "actor_subject": "7",
            "saved_search": _fingerprint("saved_search_name", "Private search"),
            "search_id": 11,
        }
    )
    assert "Private search" not in rendered


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ContactCreateCommand(
            "A", birthday=datetime(2000, 1, 1, tzinfo=UTC)
        ),
        lambda: ContactCreateCommand("A", anniversary="2000-01-01"),
        lambda: ContactUpdateCommand(
            birthday=datetime(2000, 1, 1, tzinfo=UTC)
        ),
        lambda: ContactUpdateCommand(anniversary="2000-01-01"),
        lambda: ContactImportRowCommand(
            "A",
            "",
            None,
            None,
            "lead",
            datetime(2000, 1, 1, tzinfo=UTC),
            None,
        ),
    ],
)
def test_mutation_date_commands_require_exact_date_instances(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ContactMutationResult(1, 2, True, None, None),
        lambda: ContactMutationResult(1, 2, False, "contact_audit", 3),
        lambda: ContactMutationResult(True, 2, False, None, None),
        lambda: ContactMutationResult(1, 0, False, None, None),
        lambda: WorkspaceMutationResult(1, False, "workspace_activity", 2),
        lambda: WorkspaceMutationResult(1, True, "workspace_activity", None),
        lambda: WorkspaceMutationResult(0, True, "workspace_activity", 2),
    ],
)
def test_mutation_result_dtos_reject_contradictory_or_invalid_states(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ContactBulkResult((2, 1), (1,), "set_stage"),
        lambda: ContactBulkResult((1, 1), (1,), "set_stage"),
        lambda: ContactBulkResult((1,), (2,), "set_stage"),
        lambda: ContactBulkResult((1,), (1, 1), "set_stage"),
        lambda: ContactBulkResult((True,), (), "set_stage"),
        lambda: ContactBulkResult(tuple(range(1, 202)), (), "set_stage"),
        lambda: ContactBulkResult((1,), (), "unknown"),
    ],
)
def test_bulk_result_rejects_unsorted_duplicate_or_inconsistent_ids(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


@pytest.mark.parametrize("domain", tuple(AUDIT_DOMAINS.values()))
def test_each_exact_contact_audit_domain_is_accepted(domain):
    rendered = redact_contact_audit_value("private", domain=domain)
    assert rendered["length"] == 7


def test_contact_audit_fingerprint_rejects_string_subclasses():
    class StringSubclass(str):
        pass

    with pytest.raises(TypeError):
        redact_contact_audit_value(
            StringSubclass("private"), domain=AUDIT_DOMAINS["email"]
        )


def test_contact_audit_builder_fingerprints_exact_raw_text_without_trimming():
    rendered = canonical_contact_audit_json(
        action="contact.updated",
        phase="before",
        payload={
            "changed_fields": ("first_name",),
            "first_name": " Private ",
        },
    )
    assert json.loads(rendered)["first_name"] == _fingerprint(
        "first_name", " Private "
    )
