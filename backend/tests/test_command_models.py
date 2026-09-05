from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from models.booking import Booking
from models.command import (
    AgreementStatus,
    CRMActivity,
    CRMAgreement,
    CRMAgreementEvent,
    CRMContact,
    CRMContactTag,
    CRMFileAsset,
    CRMGoal,
    CRMListingRecord,
    CRMNote,
    CRMOpportunity,
    CRMOpportunityContact,
    CRMReferral,
    CRMSavedSearch,
    CRMSmartPlanEnrollment,
    CRMTask,
    CRMTaskLink,
)
from schemas.command import (
    ArchiveBundleImportRequest,
    ContactCreate,
    ContactImportResult,
    ContactImportRow,
    ContactUpdate,
    ContactWorkspaceOpportunityOut,
    OpportunityUpdate,
    TaskUpdate,
)
from services.command_relationships import is_same_opportunity_contact
from services.command_task_links import task_link_display_name, task_link_model
from services.command_tasks import archive_task_source_key, task_activity_summary


def test_all_focused_contact_boundary_models_share_strict_extra_policy():
    from pydantic import BaseModel

    from schemas import command_contacts

    model_types = [
        value
        for value in vars(command_contacts).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value.__module__ == command_contacts.__name__
    ]
    assert model_types
    assert all(model.model_config.get("extra") == "forbid" for model in model_types)
    assert all(
        model.model_config.get("from_attributes") is True for model in model_types
    )


def test_focused_contact_compatibility_field_contracts_are_exact():
    from schemas.command_contacts import (
        ContactDeletedOut,
        ContactImportResultOut,
        ContactLegacySyncResultOut,
        ContactNoteCreatedOut,
        ContactSavedSearchCreatedOut,
        ContactTagAssignmentOut,
        ContactTagRemovalOut,
        ContactWorkspaceSummaryOut,
        LegacyContactOut,
        LegacyContactWorkspaceOut,
        SavedSearchOut,
    )

    assert tuple(LegacyContactOut.model_fields) == (
        "id", "first_name", "last_name", "email", "phone", "lead_id",
        "birthday", "anniversary", "stage",
    )
    assert tuple(LegacyContactWorkspaceOut.model_fields) == (
        "contact", "timeline", "tasks", "notes", "smart_plans",
        "opportunities", "saved_searches", "bookings", "tags",
    )
    assert tuple(ContactWorkspaceSummaryOut.model_fields) == (
        "open_tasks",
        "active_tasks",
        "completed_tasks",
        "cancelled_tasks",
        "archived_tasks",
        "archived_mutable_tasks",
        "archived_recovered_evidence",
        "active_smart_plans",
        "opportunities",
        "notes",
        "saved_searches",
        "bookings",
        "internal_counts",
        "recovered_counts",
    )
    assert tuple(ContactTagAssignmentOut.model_fields) == ("contact_id", "tag_id")
    assert tuple(ContactTagRemovalOut.model_fields) == (
        "contact_id", "tag_id", "removed",
    )
    assert tuple(ContactNoteCreatedOut.model_fields) == ("id", "body")
    assert tuple(ContactDeletedOut.model_fields) == ("deleted", "id")
    assert tuple(ContactSavedSearchCreatedOut.model_fields) == (
        "id", "name", "criteria",
    )
    assert tuple(ContactLegacySyncResultOut.model_fields) == (
        "created", "timeline_backfilled", "total_legacy_leads",
    )
    assert tuple(ContactImportResultOut.model_fields) == (
        "created", "skipped_duplicates",
    )
    assert tuple(SavedSearchOut.model_fields) == (
        "id", "name", "criteria", "contact_id", "contact_name", "updated_at",
    )


def test_contact_workspace_summary_requires_consistent_task_subtotals():
    from schemas.command_contacts import ContactWorkspaceSummaryOut

    valid = {
        "open_tasks": 3,
        "active_tasks": 3,
        "completed_tasks": 2,
        "cancelled_tasks": 1,
        "archived_tasks": 5,
        "archived_mutable_tasks": 2,
        "archived_recovered_evidence": 3,
        "active_smart_plans": 4,
        "opportunities": 5,
        "notes": 6,
        "saved_searches": 7,
        "bookings": 8,
    }
    assert ContactWorkspaceSummaryOut.model_validate(valid).model_dump() == {
        **valid, "internal_counts": None, "recovered_counts": None,
    }

    for invalid in (
        {**valid, "open_tasks": 4},
        {**valid, "archived_tasks": 4},
        {**valid, "cancelled_tasks": True},
        {**valid, "archived_mutable_tasks": -1},
    ):
        with pytest.raises(ValidationError):
            ContactWorkspaceSummaryOut.model_validate(invalid)


def test_archive_contact_parser_extracts_identity_and_profile_fields():
    from services.command_archive import parse_contact_capture

    record = parse_contact_capture("""Search Contacts
Adam Pappastergion
Last contact on 7 months ago
Primary Phone
+1 978 995 7104
Primary Email
apappastergion@gmail.com
Lead Source
Facebook
Birthday
August 30
Home Anniversary
September 23, 2022""")

    assert record == {
        "first_name": "Adam", "last_name": "Pappastergion", "email": "apappastergion@gmail.com",
        "phone": "+1 978 995 7104", "stage": "lead", "birthday": "08-30", "anniversary": "2022-09-23",
    }


def test_archive_inventory_is_checksum_backed_and_domain_classified(tmp_path):
    from services.command_archive import archive_inventory

    (tmp_path / "kw_command_full").mkdir()
    (tmp_path / "docusign_full").mkdir()
    (tmp_path / "kw_command_full" / "contact.snapshot.txt").write_text("Jane Doe")
    (tmp_path / "docusign_full" / "agreement.json").write_text('{"title":"Offer"}')

    rows = archive_inventory(tmp_path)

    assert [(row["domain"], row["artifact_type"], row["filename"]) for row in rows] == [
        ("docusign", "json", "agreement.json"),
        ("kw_command", "txt", "contact.snapshot.txt"),
    ]
    assert all(len(row["sha256"]) == 64 for row in rows)


def test_archive_artifact_can_hold_private_source_bytes():
    from models.command import CRMArchiveArtifact

    artifact = CRMArchiveArtifact(
        source_path="docusign_full/downloads/example.zip", domain="docusign", artifact_type="zip",
        filename="example.zip", sha256="a" * 64, size_bytes=3, content_bytes=b"zip",
    )

    assert artifact.content_bytes == b"zip"


def test_command_models_expose_safe_defaults_and_links():
    contact = CRMContact(first_name="Brandon", last_name="Sweeney")
    task = CRMTask(title="Call Brandon")
    activity = CRMActivity(kind="note", summary="Created contact")

    assert contact.lead_id is None
    assert task.status == "open"
    assert activity.kind == "note"


def test_timeline_linkage_models_sync_exact_normalized_primary_email():
    contact = CRMContact(
        first_name="Avery", email="  ＡＶＥＲＹ＠Ｅｘａｍｐｌｅ．ＣＯＭ  "
    )
    booking = Booking(
        name="Avery",
        email="  ＡＶＥＲＹ＠Ｅｘａｍｐｌｅ．ＣＯＭ  ",
        scheduled_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    assert contact.normalized_email == "avery@example.com"
    assert booking.normalized_email == "avery@example.com"

    contact.email = "invalid"
    booking.email = "invalid"
    assert contact.normalized_email is None
    assert booking.normalized_email is None

    overridden_contact = CRMContact(
        first_name="Avery",
        email="owner@example.test",
        normalized_email="tampered@example.test",
    )
    overridden_booking = Booking(
        name="Avery",
        email="owner@example.test",
        normalized_email="tampered@example.test",
        scheduled_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    assert overridden_contact.normalized_email == "tampered@example.test"
    assert overridden_booking.normalized_email == "tampered@example.test"


def test_timeline_linkage_models_have_exact_query_indexes():
    assert {
        index.name: tuple(column.name for column in index.columns)
        for index in CRMContact.__table__.indexes
    } == {
        "ix_crm_contacts_normalized_email_id": ("normalized_email", "id"),
    }
    assert {
        index.name: tuple(column.name for column in index.columns)
        for index in CRMActivity.__table__.indexes
    }.items() >= {
        "ix_crm_activities_timeline_order": (
            "contact_id",
            "created_at",
            "id",
        ),
    }.items()
    assert {
        index.name: tuple(column.name for column in index.columns)
        for index in Booking.__table__.indexes
    } == {
        "ix_bookings_timeline_lead_order": (
            "lead_id",
            "scheduled_at",
            "id",
        ),
        "ix_bookings_timeline_email_order": (
            "normalized_email",
            "lead_id",
            "scheduled_at",
            "id",
        ),
    }


def test_agreement_statuses_only_include_internal_lifecycle():
    assert {status.value for status in AgreementStatus} == {
        "draft", "in_review", "ready", "shared", "viewed", "completed", "voided", "expired"
    }


def test_contact_workspace_opportunity_serializes_linked_record_context():
    item = ContactWorkspaceOpportunityOut(
        id=12,
        name="15 Oak Street purchase",
        stage="offer",
        value_cents=75000000,
        role="buyer",
    )

    assert item.model_dump() == {
        "id": 12,
        "name": "15 Oak Street purchase",
        "stage": "offer",
        "value_cents": 75000000,
        "role": "buyer",
    }


def test_agreement_files_and_events_are_scoped_to_an_internal_agreement():
    asset = CRMFileAsset(
        filename="buyer-agreement.pdf",
        storage_key="command-files/buyer-agreement.pdf",
        agreement_id=4,
    )
    event = CRMAgreementEvent(agreement_id=4, event_type="in_review")

    assert asset.agreement_id == 4
    assert event.agreement_id == 4


def test_task_link_connects_a_task_to_an_internal_record_without_copying_data():
    link = CRMTaskLink(task_id=3, entity_type="opportunity", entity_id=8)
    assert (link.task_id, link.entity_type, link.entity_id) == (3, "opportunity", 8)


def test_referral_is_an_internal_record_with_a_lifecycle():
    referral = CRMReferral(name="Buyer introduction", status="new")
    assert referral.status == "new"


def test_referral_lifecycle_is_limited_to_the_workspace_statuses():
    from schemas.command import ReferralUpdate
    assert ReferralUpdate(status="converted").status == "converted"
    with pytest.raises(ValidationError):
        ReferralUpdate(status="untracked")


def test_contact_can_store_private_birthday_and_anniversary_dates():
    contact = CRMContact(first_name="Avery", birthday=date(1990, 8, 12), anniversary=date(2020, 6, 1))
    payload = ContactCreate(first_name="Avery", birthday=date(1990, 8, 12), anniversary=date(2020, 6, 1))

    assert contact.birthday == date(1990, 8, 12)
    assert payload.anniversary == date(2020, 6, 1)


def test_contact_profile_updates_keep_explicit_optional_field_clears():
    update = ContactUpdate(email=None, phone=None, birthday=None, anniversary=None)
    assert update.model_fields_set == {"email", "phone", "birthday", "anniversary"}


def test_task_updates_only_allow_internal_task_lifecycle_and_priorities():
    update = TaskUpdate(
        expected_version=1,
        status="in_progress",
        priority="high",
        description="Call before noon",
        contact_id=12,
        due_at=None,
    )
    assert update.expected_version == 1
    assert update.priority == "high"
    assert update.contact_id == 12
    assert {"contact_id", "due_at"}.issubset(update.model_fields_set)
    with pytest.raises(ValidationError):
        TaskUpdate(expected_version=1, status="deleted")
    with pytest.raises(ValidationError):
        TaskUpdate(expected_version=1, priority="urgentish")


def test_task_audit_summary_describes_the_persisted_changed_fields():
    assert task_activity_summary({"priority": "high", "due_at": "2026-08-12T15:00:00Z"}) == "Updated task priority and due date"


def test_goal_is_an_internal_target_with_a_measurable_progress_value():
    goal = CRMGoal(name="August appointments", target_value=12, current_value=4, period="monthly")

    assert (goal.target_value, goal.current_value, goal.period) == (12, 4, "monthly")


def test_opportunity_stage_is_limited_to_the_internal_pipeline():
    assert OpportunityUpdate(stage="under_contract").stage == "under_contract"
    with pytest.raises(ValidationError):
        OpportunityUpdate(stage="outside_pipeline")


def test_opportunity_contact_identity_includes_the_role():
    assert is_same_opportunity_contact(8, "buyer", 8, "buyer")
    assert not is_same_opportunity_contact(8, "buyer", 8, "seller")


def test_opportunity_contact_table_has_a_database_uniqueness_contract():
    constraint_columns = {tuple(column.name for column in constraint.columns) for constraint in CRMOpportunityContact.__table__.constraints if getattr(constraint, "columns", None)}
    assert ("opportunity_id", "contact_id", "role") in constraint_columns


def test_task_link_types_resolve_to_internal_persistence_models():
    assert task_link_model("agreement").__tablename__ == "crm_agreements"
    assert task_link_model("unsupported") is None


def test_contact_import_supports_private_celebration_dates():
    row = ContactImportRow(first_name="Avery", birthday=date(1990, 8, 12), anniversary=date(2020, 6, 1))
    assert row.birthday == date(1990, 8, 12)
    assert row.anniversary == date(2020, 6, 1)
    assert ContactImportResult(created=1, skipped_duplicates=2).model_dump() == {"created": 1, "skipped_duplicates": 2}


def test_archive_bundle_accepts_every_internal_record_collection():
    bundle = ArchiveBundleImportRequest(source_id="complete-bundle-fixture", contacts=[{"first_name": "Avery", "email": "avery@example.com"}], tasks=[{"source_row_id": "call-avery", "title": "Call Avery", "contact_email": "avery@example.com"}], notes=[{"contact_email": "avery@example.com", "body": "Imported context"}], opportunities=[{"name": "Main Street", "contact_emails": ["avery@example.com"]}], referrals=[{"name": "Avery referral"}], listings=[{"address": "10 Main Street"}], templates=[{"name": "Buyer agreement"}], agreements=[{"title": "Buyer agreement", "contact_email": "avery@example.com", "template_name": "Buyer agreement"}])
    assert (len(bundle.contacts), len(bundle.tasks), len(bundle.agreements)) == (1, 1, 1)


@pytest.mark.parametrize(
    ("source_id", "source_row_id"),
    [("   ", "row-1"), ("source-1", "\n\t")],
)
def test_archive_task_source_key_rejects_whitespace_only_identities(
    source_id: str, source_row_id: str
):
    with pytest.raises(ValueError):
        archive_task_source_key(source_id, source_row_id)


def test_smart_plan_enrollment_has_one_canonical_row_per_contact_and_plan():
    constraint_columns = {tuple(column.name for column in constraint.columns) for constraint in CRMSmartPlanEnrollment.__table__.constraints if getattr(constraint, "columns", None)}
    assert ("smart_plan_id", "contact_id") in constraint_columns


def test_task_link_identity_and_display_name_are_canonical():
    constraint_columns = {tuple(column.name for column in constraint.columns) for constraint in CRMTaskLink.__table__.constraints if getattr(constraint, "columns", None)}
    assert ("task_id", "entity_type", "entity_id") in constraint_columns
    assert task_link_display_name("contact", CRMContact(first_name="Avery", last_name="Lake")) == "Avery Lake"
    assert task_link_display_name("opportunity", CRMOpportunity(name="Lake purchase")) == "Lake purchase"
    assert task_link_display_name("agreement", CRMAgreement(title="Buyer agreement")) == "Buyer agreement"
    assert task_link_display_name("listing", CRMListingRecord(address="10 Main Street")) == "10 Main Street"


def test_saved_search_belongs_to_optional_canonical_contact_context():
    search = CRMSavedSearch(name="Follow up", contact_id=9, criteria_json='{"stage":"lead"}')
    assert (search.contact_id, search.criteria_json) == (9, '{"stage":"lead"}')


def test_contact_notes_and_tag_assignments_remain_scoped_to_the_contact():
    assert CRMNote(contact_id=7, body="Follow up Friday").contact_id == 7
    assert CRMContactTag(contact_id=7, tag_id=3).contact_id == 7
