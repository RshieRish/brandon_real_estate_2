from datetime import date

import pytest
from pydantic import ValidationError

from schemas.command import ArchiveBundleImportRequest, ContactCreate, ContactImportResult, ContactImportRow, ContactUpdate, ContactWorkspaceOpportunityOut, OpportunityUpdate, TaskUpdate
from models.command import AgreementStatus, CRMActivity, CRMAgreement, CRMAgreementEvent, CRMContact, CRMContactTag, CRMFileAsset, CRMGoal, CRMListingRecord, CRMNote, CRMOpportunity, CRMOpportunityContact, CRMReferral, CRMSavedSearch, CRMSmartPlanEnrollment, CRMTask, CRMTaskLink
from services.command_tasks import task_activity_summary
from services.command_relationships import is_same_opportunity_contact
from services.command_task_links import task_link_display_name, task_link_model


def test_command_models_expose_safe_defaults_and_links():
    contact = CRMContact(first_name="Brandon", last_name="Sweeney")
    task = CRMTask(title="Call Brandon")
    activity = CRMActivity(kind="note", summary="Created contact")

    assert contact.lead_id is None
    assert task.status == "open"
    assert activity.kind == "note"


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
    update = TaskUpdate(status="in_progress", priority="high", description="Call before noon", contact_id=12, due_at=None)
    assert update.priority == "high"
    assert update.contact_id == 12
    assert {"contact_id", "due_at"}.issubset(update.model_fields_set)
    with pytest.raises(ValidationError):
        TaskUpdate(status="deleted")
    with pytest.raises(ValidationError):
        TaskUpdate(priority="urgentish")


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
    bundle = ArchiveBundleImportRequest(contacts=[{"first_name": "Avery", "email": "avery@example.com"}], tasks=[{"title": "Call Avery", "contact_email": "avery@example.com"}], notes=[{"contact_email": "avery@example.com", "body": "Imported context"}], opportunities=[{"name": "Main Street", "contact_emails": ["avery@example.com"]}], referrals=[{"name": "Avery referral"}], listings=[{"address": "10 Main Street"}], templates=[{"name": "Buyer agreement"}], agreements=[{"title": "Buyer agreement", "contact_email": "avery@example.com", "template_name": "Buyer agreement"}])
    assert (len(bundle.contacts), len(bundle.tasks), len(bundle.agreements)) == (1, 1, 1)


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
