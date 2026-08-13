from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError

from database import Base
from models.command import CRMContact
from models.command_contacts import (
    CRMContactAddress,
    CRMContactAuditEvent,
    CRMContactCapturePosition,
    CRMContactMethod,
    CRMContactNeighborhood,
    CRMContactOwnership,
    CRMContactPreference,
    CRMContactProfile,
    CRMContactRelationship,
    CRMContactSectionCapture,
    CRMContactTimelineEvent,
    canonical_json_text,
)
from models.command_provenance import CRMSourceRecord
from models.lead import Lead


CONTACT_TABLES = {
    "crm_contact_profiles",
    "crm_contact_methods",
    "crm_contact_addresses",
    "crm_contact_neighborhoods",
    "crm_contact_ownerships",
    "crm_contact_relationships",
    "crm_contact_preferences",
    "crm_contact_capture_positions",
    "crm_contact_section_captures",
    "crm_contact_timeline_events",
    "crm_contact_audit_events",
}

CONTACT_MODELS = (
    CRMContactProfile,
    CRMContactMethod,
    CRMContactAddress,
    CRMContactNeighborhood,
    CRMContactOwnership,
    CRMContactRelationship,
    CRMContactPreference,
    CRMContactCapturePosition,
    CRMContactSectionCapture,
    CRMContactTimelineEvent,
    CRMContactAuditEvent,
)


def _unique_constraints(model) -> dict[str, tuple[str, ...]]:
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name
    }


def _checks(model) -> dict[str, str]:
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }


def _foreign_keys(model) -> dict[str, tuple[str, str | None]]:
    return {
        column.name: (next(iter(column.foreign_keys)).target_fullname, next(iter(column.foreign_keys)).ondelete)
        for column in model.__table__.columns
        if column.foreign_keys
    }


@pytest.fixture()
def contact_engine():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(
        engine,
        tables=(
            Lead.__table__,
            CRMContact.__table__,
            CRMSourceRecord.__table__,
            *(model.__table__ for model in CONTACT_MODELS),
        ),
    )
    return engine


@pytest.fixture()
def seeded_contact_engine(contact_engine):
    now = datetime(2026, 7, 27, 20, 0, tzinfo=timezone.utc)
    with contact_engine.begin() as connection:
        connection.execute(
            CRMContact.__table__.insert(),
            [
                {"id": 1, "first_name": "Avery", "last_name": "Lake"},
                {"id": 2, "first_name": "Jordan", "last_name": "Lee"},
            ],
        )
        connection.execute(
            CRMSourceRecord.__table__.insert(),
            [
                {
                    "id": source_id,
                    "source_system": "kw_command",
                    "module": "contacts",
                    "record_kind": "contact_fixture",
                    "source_key": f"fixture:{source_id}",
                    "evidence_level": "observed_record",
                    "capture_quality": "complete",
                    "parser_version": "contacts-v1",
                    "captured_at": now,
                }
                for source_id in range(1, 12)
            ],
        )
    return contact_engine


def test_contact_parity_models_register_every_additive_table():
    assert CONTACT_TABLES <= set(Base.metadata.tables)


def test_every_contact_model_instantiates_and_exposes_safe_json_state_defaults():
    for model in CONTACT_MODELS:
        assert isinstance(model(), model)

    assert CRMContactProfile.__table__.c.birth_year_quality.default.arg == "unknown"
    assert (
        CRMContactProfile.__table__.c.anniversary_year_quality.default.arg
        == "unknown"
    )
    assert CRMContactPreference.__table__.c.value_json.default.arg == "{}"
    assert CRMContactCapturePosition.__table__.c.limitations_json.default.arg == "[]"
    assert CRMContactSectionCapture.__table__.c.limitations_json.default.arg == "[]"
    assert CRMContactTimelineEvent.__table__.c.attributes_json.default.arg == "{}"
    assert CRMContactAuditEvent.__table__.c.before_json.default.arg == "{}"
    assert CRMContactAuditEvent.__table__.c.after_json.default.arg == "{}"


def test_contact_models_have_the_exact_owned_field_contracts():
    expected_columns = {
        CRMContactProfile: {
            "id", "contact_id", "recovered_identity_hash", "legal_name",
            "preferred_name", "description", "company", "title", "lead_source",
            "account_name", "health_score", "last_contacted_at",
            "last_interaction_at", "birth_month", "birth_day", "birth_year",
            "birth_year_quality", "birth_raw", "anniversary_month",
            "anniversary_day", "anniversary_year", "anniversary_year_quality",
            "anniversary_raw", "created_at", "updated_at",
        },
        CRMContactMethod: {
            "id", "contact_id", "source_record_id", "source_key", "kind",
            "label", "raw_value", "normalized_value", "is_primary", "created_at",
            "updated_at",
        },
        CRMContactAddress: {
            "id", "contact_id", "source_record_id", "source_key", "address_type",
            "line1", "line2", "city", "state", "postal_code", "country",
            "formatted", "latitude", "longitude", "is_primary", "created_at",
            "updated_at",
        },
        CRMContactNeighborhood: {
            "id", "contact_id", "source_record_id", "source_key", "name",
            "latitude", "longitude", "created_at", "updated_at",
        },
        CRMContactOwnership: {
            "id", "contact_id", "source_record_id", "source_key", "role",
            "provider_actor_id", "display_name", "is_primary", "created_at",
            "updated_at",
        },
        CRMContactRelationship: {
            "id", "contact_id", "source_record_id", "source_key",
            "relationship_type", "display_name", "related_source_contact_id",
            "related_contact_id", "created_at", "updated_at",
        },
        CRMContactPreference: {
            "id", "contact_id", "source_record_id", "source_key", "preference_key",
            "value_json", "created_at", "updated_at",
        },
        CRMContactCapturePosition: {
            "id", "contact_id", "source_record_id", "bundle_fingerprint",
            "capture_ordinal", "source_contact_id", "captured_at", "capture_quality",
            "limitations_json", "created_at", "updated_at",
        },
        CRMContactSectionCapture: {
            "id", "capture_position_id", "source_record_id", "section_name",
            "captured_at", "capture_quality", "is_empty", "row_count",
            "limitations_json", "created_at", "updated_at",
        },
        CRMContactTimelineEvent: {
            "id", "contact_id", "source_record_id", "source_system",
            "source_event_key", "kind", "outcome", "title", "body", "actor_label",
            "channel", "occurred_at", "attributes_json", "created_at", "updated_at",
        },
        CRMContactAuditEvent: {
            "id", "contact_id", "actor_subject", "action", "before_json",
            "after_json", "created_at",
        },
    }

    for model, columns in expected_columns.items():
        assert set(model.__table__.columns.keys()) == columns


def test_capture_position_keeps_position_and_business_identity_separate():
    table = Base.metadata.tables["crm_contact_capture_positions"]
    assert {
        "capture_ordinal", "source_contact_id", "contact_id", "source_record_id",
    } <= set(table.c.keys())
    assert _unique_constraints(CRMContactCapturePosition) == {
        "uq_crm_contact_capture_bundle_ordinal": (
            "bundle_fingerprint", "capture_ordinal",
        ),
        "uq_crm_contact_capture_bundle_source": (
            "bundle_fingerprint", "source_contact_id",
        ),
        "uq_crm_contact_capture_source_record": ("source_record_id",),
    }


def test_contact_section_enum_is_database_constrained():
    checks = _checks(CRMContactSectionCapture)
    assert "ck_crm_contact_section_name" in checks
    for value in (
        "timeline", "opportunities", "smart_plans", "notes", "saved_searches",
        "tasks_to_do", "tasks_completed", "tasks_archived",
    ):
        assert value in checks["ck_crm_contact_section_name"]


def test_contact_models_have_all_named_uniqueness_contracts():
    for model in (
        CRMContactMethod,
        CRMContactAddress,
        CRMContactNeighborhood,
        CRMContactOwnership,
        CRMContactRelationship,
        CRMContactPreference,
    ):
        assert tuple(_unique_constraints(model).values()) == (("contact_id", "source_key"),)

    assert _unique_constraints(CRMContactSectionCapture) == {
        "uq_crm_contact_position_section": ("capture_position_id", "section_name"),
        "uq_crm_contact_section_source_record": ("source_record_id",),
    }
    assert _unique_constraints(CRMContactTimelineEvent) == {
        "uq_crm_contact_timeline_source_event": ("source_system", "source_event_key"),
        "uq_crm_contact_timeline_source_record": ("source_record_id",),
    }


def test_contact_models_have_exact_lookup_indexes():
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for model in CONTACT_MODELS
        for index in model.__table__.indexes
        if index.name
    }
    assert indexes == {
        "ix_crm_contact_methods_kind_normalized": ("kind", "normalized_value"),
        "ix_crm_contact_capture_lookup": ("contact_id", "bundle_fingerprint"),
        "ix_crm_contact_section_lookup": ("capture_position_id", "section_name"),
        "ix_crm_contact_timeline_order": ("contact_id", "occurred_at", "id"),
        "ix_crm_contact_audit_order": ("contact_id", "created_at", "id"),
    }


def test_contact_foreign_keys_preserve_evidence_and_cascade_only_owned_children():
    assert _foreign_keys(CRMContactProfile) == {
        "contact_id": ("crm_contacts.id", "CASCADE"),
    }
    for model in (
        CRMContactMethod,
        CRMContactAddress,
        CRMContactNeighborhood,
        CRMContactOwnership,
        CRMContactPreference,
    ):
        assert _foreign_keys(model) == {
            "contact_id": ("crm_contacts.id", "CASCADE"),
            "source_record_id": ("crm_source_records.id", "RESTRICT"),
        }
    assert _foreign_keys(CRMContactRelationship) == {
        "contact_id": ("crm_contacts.id", "CASCADE"),
        "source_record_id": ("crm_source_records.id", "RESTRICT"),
        "related_contact_id": ("crm_contacts.id", "SET NULL"),
    }
    assert _foreign_keys(CRMContactCapturePosition) == {
        "contact_id": ("crm_contacts.id", "CASCADE"),
        "source_record_id": ("crm_source_records.id", "RESTRICT"),
    }
    assert _foreign_keys(CRMContactSectionCapture) == {
        "capture_position_id": ("crm_contact_capture_positions.id", "CASCADE"),
        "source_record_id": ("crm_source_records.id", "RESTRICT"),
    }
    assert _foreign_keys(CRMContactTimelineEvent) == {
        "contact_id": ("crm_contacts.id", "CASCADE"),
        "source_record_id": ("crm_source_records.id", "RESTRICT"),
    }
    assert _foreign_keys(CRMContactAuditEvent) == {
        "contact_id": ("crm_contacts.id", "CASCADE"),
    }


def test_every_contact_table_accepts_a_valid_row_and_json_is_canonical(
    seeded_contact_engine,
):
    now = datetime(2026, 7, 27, 20, 0, tzinfo=timezone.utc)
    canonical = canonical_json_text({"z": [2, 1], "a": {"b": True, "a": None}})
    assert canonical == '{"a":{"a":null,"b":true},"z":[2,1]}'
    assert canonical == canonical_json_text({"a": {"a": None, "b": True}, "z": [2, 1]})

    with seeded_contact_engine.begin() as connection:
        connection.execute(
            CRMContactProfile.__table__.insert(),
            {
                "contact_id": 1,
                "recovered_identity_hash": "a" * 64,
                "health_score": 87,
                "birth_month": 8,
                "birth_day": 30,
                "birth_year_quality": "sentinel",
                "birth_raw": "1900-08-30",
                "anniversary_month": 9,
                "anniversary_day": 23,
                "anniversary_year": 2022,
                "anniversary_year_quality": "verified",
            },
        )
        connection.execute(
            CRMContactMethod.__table__.insert(),
            {
                "contact_id": 1, "source_record_id": 1, "source_key": "email:1",
                "kind": "email", "raw_value": "Avery@Example.com",
                "normalized_value": "avery@example.com", "is_primary": True,
            },
        )
        connection.execute(
            CRMContactAddress.__table__.insert(),
            {
                "contact_id": 1, "source_record_id": 2, "source_key": "address:1",
                "formatted": "1 Main St", "latitude": Decimal("42.1234567"),
                "longitude": Decimal("-71.1234567"), "is_primary": True,
            },
        )
        connection.execute(
            CRMContactNeighborhood.__table__.insert(),
            {
                "contact_id": 1, "source_record_id": 3,
                "source_key": "neighborhood:1", "name": "Lake View",
                "latitude": Decimal("42.1234567"),
                "longitude": Decimal("-71.1234567"),
            },
        )
        connection.execute(
            CRMContactOwnership.__table__.insert(),
            {
                "contact_id": 1, "source_record_id": 4, "source_key": "owner:1",
                "role": "owner", "display_name": "Brandon", "is_primary": True,
            },
        )
        connection.execute(
            CRMContactRelationship.__table__.insert(),
            {
                "contact_id": 1, "source_record_id": 5,
                "source_key": "relationship:1", "relationship_type": "spouse",
                "display_name": "Jordan Lee", "related_contact_id": 2,
            },
        )
        connection.execute(
            CRMContactPreference.__table__.insert(),
            {
                "contact_id": 1, "source_record_id": 6,
                "source_key": "preference:1", "preference_key": "search",
                "value_json": canonical,
            },
        )
        capture_id = connection.execute(
            CRMContactCapturePosition.__table__.insert().returning(
                CRMContactCapturePosition.id
            ),
            {
                "contact_id": 1, "source_record_id": 7,
                "bundle_fingerprint": "b" * 64, "capture_ordinal": 1,
                "source_contact_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
                "captured_at": now, "capture_quality": "complete",
                "limitations_json": "[]",
            },
        ).scalar_one()
        connection.execute(
            CRMContactSectionCapture.__table__.insert(),
            {
                "capture_position_id": capture_id, "source_record_id": 8,
                "section_name": "timeline", "captured_at": now,
                "capture_quality": "complete", "is_empty": False, "row_count": 1,
                "limitations_json": "[]",
            },
        )
        connection.execute(
            CRMContactTimelineEvent.__table__.insert(),
            {
                "contact_id": 1, "source_record_id": 9,
                "source_system": "kw_command", "source_event_key": "event:1",
                "kind": "note", "title": "Observed note", "occurred_at": now,
                "attributes_json": canonical,
            },
        )
        connection.execute(
            CRMContactAuditEvent.__table__.insert(),
            {
                "contact_id": 1, "actor_subject": "admin:test", "action": "import",
                "before_json": "{}", "after_json": canonical,
            },
        )

    with seeded_contact_engine.connect() as connection:
        for model in CONTACT_MODELS:
            assert connection.scalar(select(func.count()).select_from(model)) == 1


@pytest.mark.parametrize(
    ("table", "values", "message"),
    [
        (CRMContactProfile, {"contact_id": 1, "health_score": 101}, "health"),
        (CRMContactProfile, {"contact_id": 1, "birth_month": 13}, "month"),
        (CRMContactProfile, {"contact_id": 1, "birth_day": 32}, "day"),
        (
            CRMContactProfile,
            {"contact_id": 1, "birth_year_quality": "invented"},
            "year quality",
        ),
        (
            CRMContactMethod,
            {"contact_id": 1, "source_key": "method:x", "kind": "fax"},
            "method kind",
        ),
        (
            CRMContactAddress,
            {"contact_id": 1, "source_key": "address:x", "latitude": 91},
            "latitude",
        ),
        (
            CRMContactNeighborhood,
            {"contact_id": 1, "source_key": "neighborhood:x", "longitude": 181},
            "longitude",
        ),
        (
            CRMContactOwnership,
            {"contact_id": 1, "source_key": "owner:x", "role": "viewer"},
            "ownership role",
        ),
        (
            CRMContactCapturePosition,
            {
                "contact_id": 1, "source_record_id": 1,
                "bundle_fingerprint": "b" * 64, "capture_ordinal": 0,
                "source_contact_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
                "capture_quality": "complete",
            },
            "ordinal",
        ),
        (
            CRMContactCapturePosition,
            {
                "contact_id": 1, "source_record_id": 1,
                "bundle_fingerprint": "b" * 64, "capture_ordinal": 1,
                "source_contact_id": "AAAAAAAAAAAAAAAAAAAAAAAA",
                "capture_quality": "complete",
            },
            "provider id",
        ),
        (
            CRMContactCapturePosition,
            {
                "contact_id": 1, "source_record_id": 1,
                "bundle_fingerprint": "b" * 64, "capture_ordinal": 1,
                "source_contact_id": "aaaaaaaaaaaaaaaaaaaaaaag",
                "capture_quality": "complete",
            },
            "provider id",
        ),
        (
            CRMContactCapturePosition,
            {
                "contact_id": 1, "source_record_id": 1,
                "bundle_fingerprint": "b" * 64, "capture_ordinal": 1,
                "source_contact_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
                "capture_quality": "unknown",
            },
            "quality",
        ),
    ],
)
def test_contact_database_rejects_invalid_constrained_values(
    seeded_contact_engine,
    table,
    values,
    message,
):
    del message
    with pytest.raises(IntegrityError):
        with seeded_contact_engine.begin() as connection:
            connection.execute(table.__table__.insert(), values)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"section_name": "bookings"}, "section"),
        ({"capture_quality": "unknown"}, "quality"),
        ({"row_count": -1}, "row count"),
    ],
)
def test_contact_database_rejects_invalid_section_capture_values(
    seeded_contact_engine,
    overrides,
    message,
):
    del message
    with seeded_contact_engine.begin() as connection:
        capture_id = connection.execute(
            CRMContactCapturePosition.__table__.insert().returning(
                CRMContactCapturePosition.id
            ),
            {
                "contact_id": 1,
                "source_record_id": 1,
                "bundle_fingerprint": "b" * 64,
                "capture_ordinal": 1,
                "source_contact_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
                "capture_quality": "complete",
            },
        ).scalar_one()

    values = {
        "capture_position_id": capture_id,
        "source_record_id": 2,
        "section_name": "timeline",
        "capture_quality": "complete",
        "is_empty": True,
        "row_count": 0,
        **overrides,
    }
    with pytest.raises(IntegrityError):
        with seeded_contact_engine.begin() as connection:
            connection.execute(CRMContactSectionCapture.__table__.insert(), values)


def test_contact_database_enforces_uniqueness_and_evidence_restriction(
    seeded_contact_engine,
):
    with seeded_contact_engine.begin() as connection:
        connection.execute(
            CRMContactMethod.__table__.insert(),
            {
                "contact_id": 1, "source_record_id": 1, "source_key": "email:1",
                "kind": "email",
            },
        )

    with pytest.raises(IntegrityError):
        with seeded_contact_engine.begin() as connection:
            connection.execute(
                CRMContactMethod.__table__.insert(),
                {
                    "contact_id": 1, "source_record_id": 2,
                    "source_key": "email:1", "kind": "email",
                },
            )

    with pytest.raises(IntegrityError):
        with seeded_contact_engine.begin() as connection:
            connection.execute(
                CRMSourceRecord.__table__.delete().where(CRMSourceRecord.id == 1)
            )


@pytest.mark.parametrize(
    "values",
    [
        {"contact_id": 999, "source_key": "missing:contact", "kind": "email"},
        {
            "contact_id": 1,
            "source_record_id": 999,
            "source_key": "missing:evidence",
            "kind": "email",
        },
    ],
)
def test_contact_database_rejects_orphaned_owned_or_evidence_links(
    seeded_contact_engine,
    values,
):
    with pytest.raises(IntegrityError):
        with seeded_contact_engine.begin() as connection:
            connection.execute(CRMContactMethod.__table__.insert(), values)


def test_deleting_owned_contact_cascades_children_but_related_party_sets_null(
    seeded_contact_engine,
):
    with seeded_contact_engine.begin() as connection:
        connection.execute(
            CRMContactProfile.__table__.insert(),
            {"contact_id": 1, "recovered_identity_hash": "c" * 64},
        )
        relationship_id = connection.execute(
            CRMContactRelationship.__table__.insert().returning(
                CRMContactRelationship.id
            ),
            {
                "contact_id": 1,
                "source_key": "relationship:related",
                "relationship_type": "related",
                "related_contact_id": 2,
            },
        ).scalar_one()

    with seeded_contact_engine.begin() as connection:
        connection.execute(CRMContact.__table__.delete().where(CRMContact.id == 2))

    with seeded_contact_engine.connect() as connection:
        assert connection.scalar(
            select(CRMContactRelationship.related_contact_id).where(
                CRMContactRelationship.id == relationship_id
            )
        ) is None

    with seeded_contact_engine.begin() as connection:
        connection.execute(CRMContact.__table__.delete().where(CRMContact.id == 1))

    with seeded_contact_engine.connect() as connection:
        assert connection.scalar(select(CRMContactProfile.id)) is None
        assert connection.scalar(select(CRMContactRelationship.id)) is None
