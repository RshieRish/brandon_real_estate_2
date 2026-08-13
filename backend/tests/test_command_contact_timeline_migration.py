from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex

from models.booking import Booking
from models.command import CRMActivity, CRMContact
from models.command_contacts import CRMContactTimelineEvent
from models.command_provenance import CRMSourceRecord
from models.lead import Lead
from services.command_contact_identity import canonical_email


def _load_revision():
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "6c0e2f4a5b7d_add_timeline_query_support.py"
    )
    spec = importlib.util.spec_from_file_location(
        "command_contact_timeline_revision_6c0e2f4a5b7d", path
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def _create_prior_schema(connection) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "crm_contacts",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=True),
    )
    activities = sa.Table(
        "crm_activities",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("source_record_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    sa.Index(
        "uq_crm_activities_source_record_id",
        activities.c.source_record_id,
        unique=True,
    )
    sa.Table(
        "bookings",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(connection)


def _indexes(connection, table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        index["name"]: tuple(index["column_names"])
        for index in sa.inspect(connection).get_indexes(table_name)
        if index["name"]
    }


def test_timeline_revision_backfills_exact_canonical_email_and_downgrades_losslessly():
    revision = _load_revision()
    assert revision.revision == "6c0e2f4a5b7d"
    assert revision.down_revision == "5b9d1e2f3a4c"
    engine = sa.create_engine("sqlite://")
    raw_values = (
        "  ＡＶＥＲＹ＠Ｅｘａｍｐｌｅ．ＣＯＭ  ",
        "invalid",
        "none",
        None,
    )
    with engine.connect() as connection:
        _create_prior_schema(connection)
        connection.execute(
            sa.text(
                "INSERT INTO crm_contacts (id, email) VALUES (1, :one), (2, :two), (3, :three), (4, :four)"
            ),
            dict(zip(("one", "two", "three", "four"), raw_values, strict=True)),
        )
        connection.execute(
            sa.text(
                "INSERT INTO bookings (id, lead_id, email, scheduled_at) "
                "VALUES (1, NULL, :one, '2026-08-13 12:00:00'), "
                "(2, NULL, :two, '2026-08-13 11:00:00'), "
                "(3, NULL, :three, '2026-08-13 10:00:00')"
            ),
            {"one": raw_values[0], "two": raw_values[1], "three": raw_values[2]},
        )
        connection.commit()
        revision.op = Operations(MigrationContext.configure(connection))
        revision.upgrade()
        connection.commit()

        expected = [canonical_email(value) for value in raw_values]
        assert (
            connection.execute(
                sa.text("SELECT normalized_email FROM crm_contacts ORDER BY id")
            )
            .scalars()
            .all()
            == expected
        )
        assert (
            connection.execute(
                sa.text("SELECT normalized_email FROM bookings ORDER BY id")
            )
            .scalars()
            .all()
            == expected[:3]
        )
        assert _indexes(connection, "crm_contacts") == {
            "ix_crm_contacts_normalized_email_id": ("normalized_email", "id")
        }
        assert _indexes(connection, "crm_activities") == {
            "ix_crm_activities_timeline_order": (
                "contact_id",
                "created_at",
                "id",
            ),
            "uq_crm_activities_source_record_id": ("source_record_id",),
        }
        assert _indexes(connection, "bookings") == {
            "ix_bookings_timeline_email_order": (
                "normalized_email",
                "lead_id",
                "scheduled_at",
                "id",
            ),
            "ix_bookings_timeline_lead_order": (
                "lead_id",
                "scheduled_at",
                "id",
            ),
        }

        revision.downgrade()
        connection.commit()
        assert "normalized_email" not in {
            column["name"]
            for column in sa.inspect(connection).get_columns("crm_contacts")
        }
        assert "normalized_email" not in {
            column["name"] for column in sa.inspect(connection).get_columns("bookings")
        }
        assert connection.execute(
            sa.text("SELECT email FROM crm_contacts ORDER BY id")
        ).scalars().all() == list(raw_values)
        assert _indexes(connection, "crm_activities") == {
            "uq_crm_activities_source_record_id": ("source_record_id",)
        }


def test_timeline_revision_refuses_offline_upgrade_before_emitting_sql():
    revision = _load_revision()
    output = StringIO()
    revision.op = Operations(
        MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output},
        )
    )
    with pytest.raises(RuntimeError, match="online canonical backfill"):
        revision.upgrade()
    assert output.getvalue() == ""


def test_timeline_model_indexes_compile_for_postgresql():
    indexes = (
        *CRMContact.__table__.indexes,
        *CRMActivity.__table__.indexes,
        *Booking.__table__.indexes,
    )
    sql = "\n".join(
        str(CreateIndex(index).compile(dialect=postgresql.dialect())).upper()
        for index in indexes
    )
    assert "CREATE INDEX IX_CRM_CONTACTS_NORMALIZED_EMAIL_ID" in sql
    assert "CREATE INDEX IX_CRM_ACTIVITIES_TIMELINE_ORDER" in sql
    assert "CREATE INDEX IX_BOOKINGS_TIMELINE_LEAD_ORDER" in sql
    assert "CREATE INDEX IX_BOOKINGS_TIMELINE_EMAIL_ORDER" in sql


def test_ordinary_insert_and_update_flushes_cannot_persist_normalized_email_drift():
    engine = sa.create_engine("sqlite://")
    from database import Base

    Base.metadata.create_all(
        engine,
        tables=(
            Lead.__table__,
            CRMContact.__table__,
            Booking.__table__,
            CRMSourceRecord.__table__,
            CRMActivity.__table__,
            CRMContactTimelineEvent.__table__,
        ),
    )
    offset = timezone(timedelta(hours=-4))
    local_noon = datetime(2026, 8, 13, 8, 0, tzinfo=offset)
    with Session(engine) as session:
        contact = CRMContact(
            first_name="Flush",
            last_name="Contact",
            email=" First@Example.Test ",
            normalized_email="tampered@example.test",
        )
        booking = Booking(
            name="Flush Booking",
            email=" First@Example.Test ",
            normalized_email="tampered@example.test",
            scheduled_at=local_noon,
        )
        source = CRMSourceRecord(
            source_system="kw_command",
            module="contacts",
            record_kind="contact_timeline_event",
            source_key="synthetic:flush",
            evidence_level="rendered_occurrence",
            display_label="Synthetic",
            payload_json="{}",
            capture_quality="complete",
            captured_at=local_noon,
            parser_version="contacts-v1",
        )
        session.add_all((contact, booking, source))
        session.flush()
        activity = CRMActivity(
            contact_id=contact.id,
            kind="explicit",
            summary="Explicit offset timestamp",
            created_at=local_noon,
        )
        recovered = CRMContactTimelineEvent(
            contact_id=contact.id,
            source_record_id=source.id,
            source_system="kw_command",
            source_event_key="synthetic:flush",
            kind="event",
            title="Explicit offset timestamp",
            occurred_at=local_noon,
            attributes_json="{}",
        )
        null_time = CRMContactTimelineEvent(
            contact_id=contact.id,
            source_record_id=source.id + 1,
            source_system="kw_command",
            source_event_key="synthetic:null",
            kind="event",
            title="No timestamp",
            occurred_at=None,
            attributes_json="{}",
        )
        second_source = CRMSourceRecord(
            id=source.id + 1,
            source_system="kw_command",
            module="contacts",
            record_kind="contact_timeline_event",
            source_key="synthetic:null",
            evidence_level="rendered_occurrence",
            display_label="Synthetic",
            payload_json="{}",
            capture_quality="complete",
            captured_at=local_noon,
            parser_version="contacts-v1",
        )
        session.add_all((activity, second_source, recovered, null_time))
        session.flush()
        assert contact.normalized_email == "first@example.test"
        assert booking.normalized_email == "first@example.test"
        assert booking.scheduled_at == datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
        assert activity.created_at == datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
        assert recovered.occurred_at == datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
        assert null_time.occurred_at is None

        contact.email = " ＳＥＣＯＮＤ@Example.Test "
        contact.normalized_email = "tampered@example.test"
        booking.email = " ＳＥＣＯＮＤ@Example.Test "
        booking.normalized_email = "tampered@example.test"
        session.flush()
        assert contact.normalized_email == "second@example.test"
        assert booking.normalized_email == "second@example.test"

        contact.normalized_email = "tampered@example.test"
        booking.normalized_email = "tampered@example.test"
        booking.scheduled_at = datetime(2026, 8, 14, 7, 0, tzinfo=offset)
        activity.created_at = datetime(2026, 8, 14, 7, 0, tzinfo=offset)
        recovered.occurred_at = datetime(2026, 8, 14, 7, 0, tzinfo=offset)
        session.flush()
        assert contact.normalized_email == "second@example.test"
        assert booking.normalized_email == "second@example.test"
        expected_update = datetime(2026, 8, 14, 11, 0, tzinfo=UTC)
        assert booking.scheduled_at == expected_update
        assert activity.created_at == expected_update
        assert recovered.occurred_at == expected_update

        booking_id = booking.id
        activity_id = activity.id
        recovered_id = recovered.id
        session.expire_all()
        stored_booking = session.get(Booking, booking_id)
        stored_activity = session.get(CRMActivity, activity_id)
        stored_recovered = session.get(CRMContactTimelineEvent, recovered_id)
        assert stored_booking is not None
        assert stored_activity is not None
        assert stored_recovered is not None
        assert stored_booking.scheduled_at.tzinfo is None
        assert stored_activity.created_at.tzinfo is None
        assert stored_recovered.occurred_at is not None
        assert stored_recovered.occurred_at.tzinfo is None
        assert stored_booking.scheduled_at.replace(tzinfo=UTC) == expected_update
        assert stored_activity.created_at.replace(tzinfo=UTC) == expected_update
        assert stored_recovered.occurred_at.replace(tzinfo=UTC) == expected_update
