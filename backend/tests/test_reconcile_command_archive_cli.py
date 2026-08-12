"""Safety and output contracts for the Command archive reconciliation CLI."""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import func, select

from command_db import archive_artifact_row, command_db as command_db_session
from models.command_provenance import (
    CRMReconciliationResult,
    CRMReconciliationRun,
    CRMSourceRecord,
)
from services.command_parsers import ModuleMetrics
from services.command_provenance import bundle_fingerprint
from services.command_reconciliation import ReconciliationSummary


command_db = pytest.fixture(name="command_db")(command_db_session)


def test_cli_requires_exactly_one_mode():
    from scripts.reconcile_command_archive import parse_args

    with pytest.raises(SystemExit):
        parse_args([])
    with pytest.raises(SystemExit):
        parse_args(["--dry-run", "--apply", "--parser-version", "command-v1"])


def test_cli_requires_parser_version():
    from scripts.reconcile_command_archive import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--dry-run"])


def test_cli_apply_requires_explicit_bundle_fingerprint():
    from scripts.reconcile_command_archive import parse_args, validate_apply_args

    args = parse_args(["--apply", "--parser-version", "command-v1"])

    with pytest.raises(ValueError, match="--expect-fingerprint"):
        validate_apply_args(args)


def test_cli_supports_bounded_module_and_resume():
    from scripts.reconcile_command_archive import parse_args

    args = parse_args(
        [
            "--dry-run",
            "--parser-version",
            "command-v1",
            "--module",
            "contacts",
            "--module",
            "tasks",
            "--resume",
            "7",
        ]
    )

    assert args.modules == ["contacts", "tasks"]
    assert args.resume == 7


@pytest.mark.asyncio
async def test_artifacts_are_loaded_with_private_bytes_in_source_path_order(command_db):
    from scripts.reconcile_command_archive import load_artifacts

    command_db.add_all(
        [
            archive_artifact_row(source_path="zeta/page.json", content=b"zeta"),
            archive_artifact_row(source_path="alpha/page.json", content=b"alpha"),
        ]
    )
    await command_db.commit()

    artifacts = await load_artifacts(command_db)

    assert [artifact.source_path for artifact in artifacts] == [
        "alpha/page.json",
        "zeta/page.json",
    ]
    assert [artifact.content_bytes for artifact in artifacts] == [b"alpha", b"zeta"]


@pytest.mark.asyncio
async def test_apply_refuses_fingerprint_mismatch_before_creating_a_run(command_db):
    from scripts.reconcile_command_archive import parse_args, run_reconciliation

    command_db.add(
        archive_artifact_row(source_path="contacts/contact.json", content=b"contact")
    )
    await command_db.commit()
    args = parse_args(
        [
            "--apply",
            "--parser-version",
            "command-v1",
            "--expect-fingerprint",
            "0" * 64,
        ]
    )

    with pytest.raises(ValueError, match="fingerprint"):
        await run_reconciliation(command_db, args)

    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMReconciliationRun)
        )
        == 0
    )
    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord))
        == 0
    )


@pytest.mark.asyncio
async def test_apply_accepts_only_the_exact_computed_fingerprint(command_db):
    from scripts.reconcile_command_archive import (
        load_artifacts,
        parse_args,
        run_reconciliation,
    )

    command_db.add(
        archive_artifact_row(source_path="contacts/contact.json", content=b"contact")
    )
    await command_db.commit()
    fingerprint = bundle_fingerprint(await load_artifacts(command_db))
    args = parse_args(
        [
            "--apply",
            "--parser-version",
            "command-v1",
            "--expect-fingerprint",
            fingerprint,
        ]
    )

    summary = await run_reconciliation(command_db, args)

    assert summary.status == "completed"
    assert summary.bundle_fingerprint == fingerprint
    assert [result.module for result in summary.results] == ["archive_integrity"]


@pytest.mark.asyncio
async def test_verify_only_writes_audit_rows_but_no_semantic_source_records(command_db):
    from scripts.reconcile_command_archive import parse_args, run_reconciliation

    command_db.add(
        archive_artifact_row(source_path="contacts/contact.json", content=b"contact")
    )
    await command_db.commit()
    args = parse_args(["--verify-only", "--parser-version", "command-v1"])

    summary = await run_reconciliation(command_db, args)

    assert summary.status == "completed"
    assert [result.module for result in summary.results] == ["archive_integrity"]
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMReconciliationRun)
        )
        == 1
    )
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMReconciliationResult)
        )
        == 1
    )
    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord))
        == 0
    )


def test_summary_json_is_one_deterministic_object_with_module_metrics():
    from scripts.reconcile_command_archive import summary_json

    summary = ReconciliationSummary(
        run_id=17,
        status="completed",
        bundle_fingerprint="a" * 64,
        results=(
            ModuleMetrics(
                source_system="all",
                module="archive_integrity",
                expected_count=2,
                observed_count=2,
                duplicate_content_count=1,
                details={"bytes": 12, "artifacts": 2},
            ),
        ),
    )

    rendered = summary_json(summary)

    assert "\n" not in rendered
    assert json.loads(rendered) == {
        "bundle_fingerprint": "a" * 64,
        "modules": [
            {
                "details": {"artifacts": 2, "bytes": 12},
                "duplicate_content_count": 1,
                "error_count": 0,
                "evidence_only_count": 0,
                "expected_count": 2,
                "module": "archive_integrity",
                "normalized_count": 0,
                "observed_count": 2,
                "rendered_count": 0,
                "source_system": "all",
                "unmatched_count": 0,
            }
        ],
        "run_id": 17,
        "status": "completed",
    }


def test_main_prints_exactly_one_json_summary(monkeypatch, capsys):
    import scripts.reconcile_command_archive as cli

    summary = ReconciliationSummary(
        run_id=3,
        status="completed",
        bundle_fingerprint=hashlib.sha256(b"bundle").hexdigest(),
        results=(),
    )

    async def fake_database_runner(args):
        assert args.verify_only is True
        assert args.parser_version == "command-v1"
        return summary

    monkeypatch.setattr(cli, "_run_with_database", fake_database_runner)

    cli.main(["--verify-only", "--parser-version", "command-v1"])

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "bundle_fingerprint": summary.bundle_fingerprint,
        "modules": [],
        "run_id": 3,
        "status": "completed",
    }
