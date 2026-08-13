from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

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

PREREQUISITE_TABLES = {
    "alembic_version",
    "leads",
    "crm_contacts",
    "crm_source_records",
    "crm_activities",
}


def load_revision():
    revision_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "4a8c0d1e2f3b_add_command_contact_parity.py"
    )
    spec = importlib.util.spec_from_file_location(
        "command_contact_parity_revision_4a8c0d1e2f3b",
        revision_path,
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def load_occurrence_revision():
    revision_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "5b9d1e2f3a4c_add_contact_occurrence_context.py"
    )
    spec = importlib.util.spec_from_file_location(
        "command_contact_occurrence_revision_5b9d1e2f3a4c",
        revision_path,
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def create_2e7f9a0b1c2d_prerequisites(connection):
    metadata = sa.MetaData()
    sa.Table(
        "alembic_version",
        metadata,
        sa.Column("version_num", sa.String(32), primary_key=True),
    )
    sa.Table(
        "leads",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    sa.Table(
        "crm_contacts",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), unique=True),
        sa.Column("first_name", sa.String(120), nullable=False),
        sa.Column("last_name", sa.String(120), nullable=False, server_default=""),
    )
    sa.Table(
        "crm_source_records",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    sa.Table(
        "crm_activities",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id")),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("metadata", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    metadata.create_all(connection)
    connection.execute(
        sa.text("INSERT INTO alembic_version (version_num) VALUES (:version_num)"),
        {"version_num": "2e7f9a0b1c2d"},
    )


def _check_names(inspector, table_name):
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table_name)
    }


def _named_unique_columns(inspector, table_name):
    return {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint["name"]
    }


def _index_columns(inspector, table_name):
    return {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes(table_name)
        if index["name"]
    }


def _foreign_key_deletes(inspector, table_name):
    return {
        tuple(foreign_key["constrained_columns"]): (
            foreign_key["referred_table"],
            foreign_key.get("options", {}).get("ondelete"),
        )
        for foreign_key in inspector.get_foreign_keys(table_name)
    }


def test_contact_parity_revision_upgrades_from_current_head_and_downgrades_only_it():
    engine = sa.create_engine("sqlite://")
    revision = load_revision()

    assert revision.revision == "4a8c0d1e2f3b"
    assert revision.down_revision == "2e7f9a0b1c2d"

    with engine.connect() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        connection.commit()
        create_2e7f9a0b1c2d_prerequisites(connection)
        connection.commit()

        revision.op = Operations(MigrationContext.configure(connection))
        revision.upgrade()
        connection.commit()

        inspector = sa.inspect(connection)
        assert set(inspector.get_table_names()) == PREREQUISITE_TABLES | CONTACT_TABLES
        expected_checks = {
            "crm_contact_profiles": {
                "ck_crm_contact_profile_health_score",
                "ck_crm_contact_profile_birth_month",
                "ck_crm_contact_profile_birth_day",
                "ck_crm_contact_profile_anniversary_month",
                "ck_crm_contact_profile_anniversary_day",
                "ck_crm_contact_profile_birth_year_quality",
                "ck_crm_contact_profile_anniversary_year_quality",
            },
            "crm_contact_methods": {"ck_crm_contact_method_kind"},
            "crm_contact_addresses": {
                "ck_crm_contact_address_latitude",
                "ck_crm_contact_address_longitude",
            },
            "crm_contact_neighborhoods": {
                "ck_crm_contact_neighborhood_latitude",
                "ck_crm_contact_neighborhood_longitude",
            },
            "crm_contact_ownerships": {"ck_crm_contact_ownership_role"},
            "crm_contact_relationships": set(),
            "crm_contact_preferences": set(),
            "crm_contact_capture_positions": {
                "ck_crm_contact_capture_ordinal",
                "ck_crm_contact_capture_source_contact_id",
                "ck_crm_contact_capture_quality",
            },
            "crm_contact_section_captures": {
                "ck_crm_contact_section_name",
                "ck_crm_contact_section_quality",
                "ck_crm_contact_section_row_count",
            },
            "crm_contact_timeline_events": set(),
            "crm_contact_audit_events": set(),
        }
        assert {
            table_name: _check_names(inspector, table_name)
            for table_name in CONTACT_TABLES
        } == expected_checks

        expected_named_uniques = {
            "crm_contact_methods": {
                "uq_crm_contact_method_source_key": ("contact_id", "source_key")
            },
            "crm_contact_addresses": {
                "uq_crm_contact_address_source_key": ("contact_id", "source_key")
            },
            "crm_contact_neighborhoods": {
                "uq_crm_contact_neighborhood_source_key": (
                    "contact_id", "source_key",
                )
            },
            "crm_contact_ownerships": {
                "uq_crm_contact_ownership_source_key": ("contact_id", "source_key")
            },
            "crm_contact_relationships": {
                "uq_crm_contact_relationship_source_key": (
                    "contact_id", "source_key",
                )
            },
            "crm_contact_preferences": {
                "uq_crm_contact_preference_source_key": (
                    "contact_id", "source_key",
                )
            },
            "crm_contact_capture_positions": {
                "uq_crm_contact_capture_bundle_ordinal": (
                    "bundle_fingerprint", "capture_ordinal",
                ),
                "uq_crm_contact_capture_bundle_source": (
                    "bundle_fingerprint", "source_contact_id",
                ),
                "uq_crm_contact_capture_source_record": ("source_record_id",),
            },
            "crm_contact_section_captures": {
                "uq_crm_contact_position_section": (
                    "capture_position_id", "section_name",
                ),
                "uq_crm_contact_section_source_record": ("source_record_id",),
            },
            "crm_contact_timeline_events": {
                "uq_crm_contact_timeline_source_event": (
                    "source_system", "source_event_key",
                ),
                "uq_crm_contact_timeline_source_record": ("source_record_id",),
            },
        }
        assert {
            table_name: _named_unique_columns(inspector, table_name)
            for table_name in expected_named_uniques
        } == expected_named_uniques

        assert _index_columns(inspector, "crm_contact_methods") == {
            "ix_crm_contact_methods_kind_normalized": ("kind", "normalized_value"),
        }
        assert _index_columns(inspector, "crm_contact_capture_positions") == {
            "ix_crm_contact_capture_lookup": ("contact_id", "bundle_fingerprint"),
        }
        assert _index_columns(inspector, "crm_contact_section_captures") == {
            "ix_crm_contact_section_lookup": (
                "capture_position_id", "section_name",
            ),
        }
        assert _index_columns(inspector, "crm_contact_timeline_events") == {
            "ix_crm_contact_timeline_order": (
                "contact_id", "occurred_at", "id",
            ),
        }
        assert _index_columns(inspector, "crm_contact_audit_events") == {
            "ix_crm_contact_audit_order": ("contact_id", "created_at", "id"),
        }

        assert _foreign_key_deletes(inspector, "crm_contact_methods") == {
            ("contact_id",): ("crm_contacts", "CASCADE"),
            ("source_record_id",): ("crm_source_records", "RESTRICT"),
        }
        assert _foreign_key_deletes(inspector, "crm_contact_relationships") == {
            ("contact_id",): ("crm_contacts", "CASCADE"),
            ("source_record_id",): ("crm_source_records", "RESTRICT"),
            ("related_contact_id",): ("crm_contacts", "SET NULL"),
        }
        assert _foreign_key_deletes(inspector, "crm_contact_section_captures") == {
            ("capture_position_id",): (
                "crm_contact_capture_positions", "CASCADE",
            ),
            ("source_record_id",): ("crm_source_records", "RESTRICT"),
        }

        revision.downgrade()
        connection.commit()

        assert set(sa.inspect(connection).get_table_names()) == PREREQUISITE_TABLES
        assert connection.scalar(
            sa.text("SELECT version_num FROM alembic_version")
        ) == "2e7f9a0b1c2d"


def test_contact_parity_revision_compiles_postgresql_restrict_and_owned_cascades():
    revision = load_revision()
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    revision.op = Operations(context)
    revision.upgrade()

    sql = output.getvalue().upper()
    assert "CREATE TABLE CRM_CONTACT_PROFILES" in sql
    assert "CREATE TABLE CRM_CONTACT_AUDIT_EVENTS" in sql
    assert sql.count("ON DELETE RESTRICT") == 9
    assert sql.count("ON DELETE CASCADE") == 11
    assert sql.count("ON DELETE SET NULL") == 1
    assert (
        "FOREIGN KEY(SOURCE_RECORD_ID) REFERENCES CRM_SOURCE_RECORDS (ID) "
        "ON DELETE RESTRICT"
    ) in sql
    assert (
        "FOREIGN KEY(CONTACT_ID) REFERENCES CRM_CONTACTS (ID) ON DELETE CASCADE"
    ) in sql


def test_occurrence_revision_upgrades_and_losslessly_downgrades_sqlite():
    engine = sa.create_engine("sqlite://")
    contact_revision = load_revision()
    occurrence_revision = load_occurrence_revision()
    assert occurrence_revision.revision == "5b9d1e2f3a4c"
    assert occurrence_revision.down_revision == "4a8c0d1e2f3b"

    with engine.connect() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        connection.commit()
        create_2e7f9a0b1c2d_prerequisites(connection)
        contact_revision.op = Operations(MigrationContext.configure(connection))
        contact_revision.upgrade()
        connection.execute(
            sa.text(
                "INSERT INTO crm_activities (id, kind, summary, metadata) "
                "VALUES (1, 'legacy', 'kept', '{}'), (2, 'legacy', 'kept', '{}')"
            )
        )
        occurrence_revision.op = Operations(MigrationContext.configure(connection))
        occurrence_revision.upgrade()
        connection.commit()

        inspector = sa.inspect(connection)
        assert "crm_contact_source_occurrences" in inspector.get_table_names()
        assert next(
            column for column in inspector.get_columns("crm_contact_timeline_events")
            if column["name"] == "occurred_at"
        )["nullable"] is True
        assert _index_columns(inspector, "crm_activities")[
            "uq_crm_activities_source_record_id"
        ] == ("source_record_id",)
        assert _foreign_key_deletes(inspector, "crm_contact_source_occurrences") == {
            ("contact_id",): ("crm_contacts", "CASCADE"),
            ("section_capture_id",): ("crm_contact_section_captures", "CASCADE"),
            ("source_record_id",): ("crm_source_records", "RESTRICT"),
        }
        assert connection.execute(
            sa.text("SELECT source_record_id FROM crm_activities ORDER BY id")
        ).scalars().all() == [None, None]

        occurrence_revision.downgrade()
        connection.commit()
        inspector = sa.inspect(connection)
        assert "crm_contact_source_occurrences" not in inspector.get_table_names()
        assert "source_record_id" not in {
            column["name"] for column in inspector.get_columns("crm_activities")
        }
        assert next(
            column for column in inspector.get_columns("crm_contact_timeline_events")
            if column["name"] == "occurred_at"
        )["nullable"] is False


def test_occurrence_revision_refuses_lossy_downgrade_and_compiles_postgresql():
    occurrence_revision = load_occurrence_revision()
    contact_revision = load_revision()
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        connection.commit()
        create_2e7f9a0b1c2d_prerequisites(connection)
        contact_revision.op = Operations(MigrationContext.configure(connection))
        contact_revision.upgrade()
        occurrence_revision.op = Operations(MigrationContext.configure(connection))
        occurrence_revision.upgrade()
        connection.execute(
            sa.text(
                "INSERT INTO crm_contacts (id, first_name, last_name) "
                "VALUES (1, 'Synthetic', 'Contact')"
            )
        )
        connection.execute(sa.text("INSERT INTO crm_source_records (id) VALUES (1)"))
        connection.execute(
            sa.text(
                "INSERT INTO crm_contact_timeline_events "
                "(contact_id, source_record_id, source_system, source_event_key, "
                "kind, title, occurred_at) VALUES "
                "(1, 1, 'kw_command', 'synthetic:null-time', 'contact', "
                "'No source timestamp', NULL)"
            )
        )
        connection.commit()
        with pytest.raises(RuntimeError, match="cannot restore"):
            occurrence_revision.downgrade()
        inspector = sa.inspect(connection)
        assert "crm_contact_source_occurrences" in inspector.get_table_names()
        assert "source_record_id" in {
            column["name"] for column in inspector.get_columns("crm_activities")
        }
        assert next(
            column for column in inspector.get_columns("crm_contact_timeline_events")
            if column["name"] == "occurred_at"
        )["nullable"] is True

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    occurrence_revision.op = Operations(context)
    occurrence_revision.upgrade()
    sql = output.getvalue().upper()
    assert "CREATE TABLE CRM_CONTACT_SOURCE_OCCURRENCES" in sql
    assert "ALTER TABLE CRM_ACTIVITIES ADD COLUMN SOURCE_RECORD_ID" in sql
    assert "CREATE UNIQUE INDEX UQ_CRM_ACTIVITIES_SOURCE_RECORD_ID" in sql
    assert "ALTER COLUMN OCCURRED_AT DROP NOT NULL" in sql

    downgrade_output = StringIO()
    downgrade_context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": downgrade_output},
    )
    occurrence_revision.op = Operations(downgrade_context)
    with pytest.raises(RuntimeError, match="online losslessness preflight"):
        occurrence_revision.downgrade()
    assert downgrade_output.getvalue() == ""
