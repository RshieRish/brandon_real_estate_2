from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from models.command import (
    CRMNote,
    CRMOpportunityContact,
    CRMSavedSearch,
    CRMSmartPlanEnrollment,
    CRMTask,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

EXPECTED_INDEXES = {
    "ix_crm_tasks_contact_status_id": (
        "crm_tasks",
        ("contact_id", "status", "id"),
    ),
    "ix_crm_notes_contact_id": (
        "crm_notes",
        ("contact_id", "id"),
    ),
    "ix_crm_saved_searches_contact_id": (
        "crm_saved_searches",
        ("contact_id", "id"),
    ),
    "ix_crm_smart_plan_enrollments_contact_status_id": (
        "crm_smart_plan_enrollments",
        ("contact_id", "status", "id"),
    ),
    "ix_crm_opportunity_contacts_contact_opportunity": (
        "crm_opportunity_contacts",
        ("contact_id", "opportunity_id"),
    ),
}


def _load_revision():
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "7d1f3a5b6c8e_add_contact_workspace_summary_indexes.py"
    )
    assert path.is_file(), f"missing contact summary index revision: {path.name}"
    spec = importlib.util.spec_from_file_location(
        "command_contact_summary_revision_7d1f3a5b6c8e", path
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def _create_prior_schema(connection) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "crm_tasks",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
    )
    sa.Table(
        "crm_notes",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
    )
    sa.Table(
        "crm_saved_searches",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
    )
    sa.Table(
        "crm_smart_plan_enrollments",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
    )
    sa.Table(
        "crm_opportunity_contacts",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
    )
    metadata.create_all(connection)


def _indexes(connection, table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        index["name"]: tuple(index["column_names"])
        for index in sa.inspect(connection).get_indexes(table_name)
        if index["name"]
    }


def test_contact_summary_models_have_exact_query_indexes():
    models = (
        CRMTask,
        CRMNote,
        CRMSavedSearch,
        CRMSmartPlanEnrollment,
        CRMOpportunityContact,
    )
    actual = {
        index.name: (
            model.__tablename__,
            tuple(column.name for column in index.columns),
        )
        for model in models
        for index in model.__table__.indexes
        if index.name in EXPECTED_INDEXES
    }
    assert actual == EXPECTED_INDEXES


def test_contact_summary_revision_adds_only_indexes_and_downgrades_losslessly():
    revision = _load_revision()
    assert revision.revision == "7d1f3a5b6c8e"
    assert revision.down_revision == "6c0e2f4a5b7d"

    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        _create_prior_schema(connection)
        for table_name, columns in EXPECTED_INDEXES.values():
            values = {
                column: (
                    "open" if column == "status" else 1
                )
                for column in columns
            }
            connection.execute(
                sa.text(
                    f"INSERT INTO {table_name} "
                    f"({', '.join(columns)}) VALUES "
                    f"({', '.join(f':{column}' for column in columns)})"
                ),
                values,
            )
        connection.commit()

        revision.op = Operations(MigrationContext.configure(connection))
        revision.upgrade()
        connection.commit()

        for index_name, (table_name, columns) in EXPECTED_INDEXES.items():
            assert _indexes(connection, table_name) == {index_name: columns}
            assert connection.scalar(
                sa.text(f"SELECT COUNT(*) FROM {table_name}")
            ) == 1

        revision.downgrade()
        connection.commit()
        for table_name, _columns in EXPECTED_INDEXES.values():
            assert _indexes(connection, table_name) == {}
            assert connection.scalar(
                sa.text(f"SELECT COUNT(*) FROM {table_name}")
            ) == 1


def test_contact_summary_indexes_compile_for_postgresql_online_and_offline():
    revision = _load_revision()
    models = (
        CRMTask,
        CRMNote,
        CRMSavedSearch,
        CRMSmartPlanEnrollment,
        CRMOpportunityContact,
    )
    model_sql = "\n".join(
        str(CreateIndex(index).compile(dialect=postgresql.dialect())).upper()
        for model in models
        for index in model.__table__.indexes
        if index.name in EXPECTED_INDEXES
    )
    for index_name in EXPECTED_INDEXES:
        assert f"CREATE INDEX {index_name.upper()}" in model_sql

    upgrade_output = StringIO()
    revision.op = Operations(
        MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": upgrade_output},
        )
    )
    revision.upgrade()
    upgrade_sql = upgrade_output.getvalue().upper()
    for index_name, (table_name, columns) in EXPECTED_INDEXES.items():
        assert (
            f"CREATE INDEX {index_name.upper()} ON {table_name.upper()} "
            f"({', '.join(column.upper() for column in columns)})"
        ) in upgrade_sql

    downgrade_output = StringIO()
    revision.op = Operations(
        MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": downgrade_output},
        )
    )
    revision.downgrade()
    downgrade_sql = downgrade_output.getvalue().upper()
    for index_name in EXPECTED_INDEXES:
        assert f"DROP INDEX {index_name.upper()}" in downgrade_sql
