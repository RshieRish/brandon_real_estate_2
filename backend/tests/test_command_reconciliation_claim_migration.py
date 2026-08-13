"""Migration contract for durable reconciliation worker claims."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def load_revision(filename: str, module_name: str):
    revision_path = Path(__file__).parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, revision_path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def test_reconciliation_claim_revision_upgrades_existing_runs_and_downgrades():
    engine = sa.create_engine("sqlite://")
    provenance = load_revision(
        "1d6e7f8a9b10_add_command_provenance.py",
        "command_provenance_revision_1d6e7f8a9b10_for_claims",
    )
    claims = load_revision(
        "2e7f9a0b1c2d_add_reconciliation_claims.py",
        "command_reconciliation_claim_revision_2e7f9a0b1c2d",
    )

    with engine.connect() as connection:
        metadata = sa.MetaData()
        sa.Table(
            "crm_archive_artifacts",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
        )
        metadata.create_all(connection)
        connection.commit()
        provenance.op = Operations(MigrationContext.configure(connection))
        provenance.upgrade()
        connection.execute(
            sa.text(
                """
                INSERT INTO crm_reconciliation_runs (
                    bundle_fingerprint, parser_version, mode, status
                ) VALUES (:fingerprint, 'command-v1', 'dry_run', 'failed')
                """
            ),
            {"fingerprint": "a" * 64},
        )
        connection.commit()

        claims.op = Operations(MigrationContext.configure(connection))
        claims.upgrade()
        connection.commit()

        columns = {
            column["name"]: column
            for column in sa.inspect(connection).get_columns("crm_reconciliation_runs")
        }
        assert columns["claim_token"]["nullable"] is False
        assert columns["claimed_at"]["nullable"] is True
        row = connection.execute(
            sa.text("SELECT claim_token, claimed_at FROM crm_reconciliation_runs")
        ).one()
        assert row.claim_token == ""
        assert row.claimed_at is None

        claims.downgrade()
        connection.commit()
        column_names = {
            column["name"]
            for column in sa.inspect(connection).get_columns("crm_reconciliation_runs")
        }
        assert "claim_token" not in column_names
        assert "claimed_at" not in column_names
