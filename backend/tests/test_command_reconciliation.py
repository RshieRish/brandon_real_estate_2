"""Transactional orchestration tests for recovered Command source records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func, select

from command_db import archive_artifact_row, command_db as command_db_session
from models.command_provenance import (
    CRMReconciliationResult,
    CRMReconciliationRun,
    CRMSourceRecord,
    CRMSourceRecordArtifact,
    EvidenceLevel,
)
from services.command_parsers import (
    ModuleMetrics,
    ModuleParseResult,
    ParserRegistry,
    ParserRegistryError,
    UnknownParserModuleError,
)
from services.command_provenance import ArchiveArtifactInput, SourceRecordDraft


command_db = pytest.fixture(name="command_db")(command_db_session)


def artifact_for(
    content: bytes = b"private archive bytes",
    *,
    source_path: str = "kw_command_repaired/contacts/contact.json",
    artifact_id: int = 1,
) -> ArchiveArtifactInput:
    return ArchiveArtifactInput(
        id=artifact_id,
        source_path=source_path,
        domain="kw_command",
        artifact_type="json",
        filename=source_path.rsplit("/", 1)[-1],
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        content_bytes=content,
    )


def source_draft(
    *,
    module: str = "contacts",
    source_key: str = "contact-1",
    artifact_paths: tuple[str, ...] = ("kw_command_repaired/contacts/contact.json",),
    parser_version: str = "command-v1",
) -> SourceRecordDraft:
    return SourceRecordDraft(
        source_system="kw_command",
        module=module,
        record_kind=module.removesuffix("s"),
        source_key=source_key,
        evidence_level=EvidenceLevel.OBSERVED_RECORD,
        display_label=source_key,
        payload={"source_key": source_key},
        artifact_paths=artifact_paths,
        parser_version=parser_version,
    )


def parse_result(
    *,
    module: str,
    records: tuple[SourceRecordDraft, ...] = (),
    source_system: str = "kw_command",
    normalized_count: int = 0,
    details: dict[str, object] | None = None,
) -> ModuleParseResult:
    return ModuleParseResult(
        records=records,
        metrics=ModuleMetrics(
            source_system=source_system,
            module=module,
            expected_count=len(records),
            observed_count=len(records),
            rendered_count=2,
            normalized_count=normalized_count,
            evidence_only_count=3,
            unmatched_count=4,
            duplicate_content_count=5,
            error_count=6,
            details=details or {"zeta": 2, "alpha": {"beta": [1, 2]}},
        ),
    )


class FakeParser:
    def __init__(
        self,
        module: str,
        outcomes: list[ModuleParseResult | Exception],
        *,
        call_order: list[str] | None = None,
        before_return=None,
    ) -> None:
        self.module = module
        self.outcomes = outcomes
        self.parse_calls = 0
        self.call_order = call_order
        self.before_return = before_return

    def parse(self, artifacts, parser_version):
        if self.call_order is not None:
            self.call_order.append(self.module)
        self.parse_calls += 1
        if self.before_return is not None:
            self.before_return()
        outcome = self.outcomes[min(self.parse_calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def seed_artifacts(command_db, *artifacts: ArchiveArtifactInput) -> None:
    command_db.add_all(
        [
            archive_artifact_row(
                source_path=artifact.source_path,
                content=artifact.content_bytes or b"",
            )
            for artifact in artifacts
        ]
    )
    await command_db.commit()


def registry_for(*parsers: FakeParser) -> ParserRegistry:
    registry = ParserRegistry()
    for parser in parsers:
        registry.register(parser)
    return registry


def test_run_request_and_summary_are_validated_frozen_slotted_values():
    from services.command_reconciliation import (
        ReconciliationResumeError,
        ReconciliationSummary,
        RunRequest,
    )

    request = RunRequest(mode="apply", parser_version="command-v1")
    assert request.modules == frozenset()
    assert request.resume_run_id is None
    assert not hasattr(request, "__dict__")
    with pytest.raises(FrozenInstanceError):
        request.mode = "dry_run"

    summary = ReconciliationSummary(
        run_id=1,
        status="completed",
        bundle_fingerprint="a" * 64,
        results=(),
    )
    assert not hasattr(summary, "__dict__")
    with pytest.raises(FrozenInstanceError):
        summary.status = "failed"

    with pytest.raises(ValueError, match="mode"):
        RunRequest(mode="invalid", parser_version="command-v1")
    with pytest.raises(ValueError, match="parser_version"):
        RunRequest(mode="apply", parser_version=" \t")
    with pytest.raises(ValueError, match="archive_integrity"):
        RunRequest(
            mode="verify_only",
            parser_version="command-v1",
            modules=frozenset({"contacts"}),
        )
    for invalid_resume_id in (0, -1, True):
        with pytest.raises(ReconciliationResumeError, match="positive"):
            RunRequest(
                mode="apply",
                parser_version="command-v1",
                resume_run_id=invalid_resume_id,
            )


async def test_dry_run_audits_completed_result_without_source_mutation(command_db):
    from services.command_reconciliation import RunRequest, execute_reconciliation

    artifact = artifact_for()
    await seed_artifacts(command_db, artifact)
    draft = source_draft()
    parser = FakeParser(
        "contacts",
        [parse_result(module="contacts", records=(draft,), normalized_count=9)],
    )

    summary = await execute_reconciliation(
        command_db,
        registry_for(parser),
        (artifact,),
        RunRequest(
            mode="dry_run",
            parser_version="command-v1",
            modules=frozenset({"contacts"}),
        ),
    )

    assert summary.status == "completed"
    assert len(summary.results) == 1
    assert summary.results[0].normalized_count == 9
    assert summary.results[0].details == {
        "alpha": {"beta": (1, 2)},
        "zeta": 2,
    }
    run = await command_db.get(CRMReconciliationRun, summary.run_id)
    result = await command_db.scalar(select(CRMReconciliationResult))
    assert run is not None
    assert run.status == "completed"
    assert run.completed_at is not None
    assert run.requested_modules_json == '["contacts"]'
    assert result is not None
    assert result.details_json == '{"alpha":{"beta":[1,2]},"zeta":2}'
    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 0
    )
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMSourceRecordArtifact)
        )
        == 0
    )


async def test_apply_persists_idempotently_and_normalizes_every_matched_record(
    command_db,
):
    from services.command_reconciliation import RunRequest, execute_reconciliation

    artifact = artifact_for()
    await seed_artifacts(command_db, artifact)
    draft = source_draft()
    parser = FakeParser(
        "contacts",
        [parse_result(module="contacts", records=(draft,), normalized_count=0)],
    )
    request = RunRequest(
        mode="apply",
        parser_version="command-v1",
        modules=frozenset({"contacts"}),
    )

    first = await execute_reconciliation(
        command_db, registry_for(parser), (artifact,), request
    )
    second = await execute_reconciliation(
        command_db, registry_for(parser), (artifact,), request
    )

    assert first.run_id != second.run_id
    assert first.results[0].normalized_count == 1
    assert second.results[0].normalized_count == 1
    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 1
    )
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMSourceRecordArtifact)
        )
        == 1
    )
    assert (
        await command_db.scalar(select(func.count()).select_from(CRMReconciliationRun))
        == 2
    )
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMReconciliationResult)
        )
        == 2
    )


async def test_verify_only_selects_exactly_archive_integrity(command_db):
    from services.command_reconciliation import RunRequest, execute_reconciliation

    artifact = artifact_for()
    await seed_artifacts(command_db, artifact)
    integrity = FakeParser(
        "archive_integrity",
        [parse_result(module="archive_integrity", source_system="all")],
    )
    contacts = FakeParser("contacts", [parse_result(module="contacts")])

    summary = await execute_reconciliation(
        command_db,
        registry_for(contacts, integrity),
        (artifact,),
        RunRequest(mode="verify_only", parser_version="command-v1"),
    )

    assert integrity.parse_calls == 1
    assert contacts.parse_calls == 0
    assert tuple(result.module for result in summary.results) == ("archive_integrity",)


async def test_module_filter_runs_in_registry_order_and_serializes_modules(command_db):
    from services.command_reconciliation import RunRequest, execute_reconciliation

    artifact = artifact_for()
    await seed_artifacts(command_db, artifact)
    calls: list[str] = []
    tasks = FakeParser("tasks", [parse_result(module="tasks")], call_order=calls)
    contacts = FakeParser(
        "contacts", [parse_result(module="contacts")], call_order=calls
    )
    skipped = FakeParser(
        "opportunities",
        [parse_result(module="opportunities")],
        call_order=calls,
    )

    summary = await execute_reconciliation(
        command_db,
        registry_for(tasks, skipped, contacts),
        (artifact,),
        RunRequest(
            mode="dry_run",
            parser_version="command-v1",
            modules=frozenset({"tasks", "contacts"}),
        ),
    )

    assert calls == ["contacts", "tasks"]
    assert skipped.parse_calls == 0
    run = await command_db.get(CRMReconciliationRun, summary.run_id)
    assert run is not None
    assert run.requested_modules_json == '["contacts","tasks"]'


async def test_failed_parser_preserves_prior_module_boundary_and_marks_run_failed(
    command_db,
):
    from services.command_reconciliation import RunRequest, execute_reconciliation

    artifact = artifact_for()
    await seed_artifacts(command_db, artifact)
    contacts = FakeParser(
        "contacts",
        [
            parse_result(
                module="contacts",
                records=(source_draft(),),
            )
        ],
    )
    tasks = FakeParser("tasks", [RuntimeError("tasks parser exploded")])

    with pytest.raises(RuntimeError, match="exploded"):
        await execute_reconciliation(
            command_db,
            registry_for(tasks, contacts),
            (artifact,),
            RunRequest(
                mode="apply",
                parser_version="command-v1",
                modules=frozenset({"contacts", "tasks"}),
            ),
        )

    run = await command_db.scalar(select(CRMReconciliationRun))
    assert run is not None
    assert run.status == "failed"
    assert run.completed_at is not None
    assert "tasks parser exploded" in run.error_text
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMReconciliationResult)
        )
        == 1
    )
    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 1
    )
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMSourceRecordArtifact)
        )
        == 1
    )


async def test_resume_validates_compatibility_skips_success_and_completes(command_db):
    from services.command_reconciliation import (
        ReconciliationResumeError,
        RunRequest,
        execute_reconciliation,
    )

    artifact = artifact_for()
    await seed_artifacts(command_db, artifact)
    contacts = FakeParser(
        "contacts",
        [parse_result(module="contacts", records=(source_draft(),))],
    )
    tasks = FakeParser(
        "tasks",
        [
            RuntimeError("temporary task failure"),
            parse_result(
                module="tasks",
                records=(
                    source_draft(
                        module="tasks",
                        source_key="task-1",
                    ),
                ),
            ),
        ],
    )
    registry = registry_for(tasks, contacts)
    modules = frozenset({"contacts", "tasks"})
    base_request = RunRequest(
        mode="apply", parser_version="command-v1", modules=modules
    )
    with pytest.raises(RuntimeError, match="temporary"):
        await execute_reconciliation(command_db, registry, (artifact,), base_request)
    failed_run = await command_db.scalar(select(CRMReconciliationRun))
    assert failed_run is not None

    incompatible_requests = (
        RunRequest(
            mode="dry_run",
            parser_version="command-v1",
            modules=modules,
            resume_run_id=failed_run.id,
        ),
        RunRequest(
            mode="apply",
            parser_version="command-v2",
            modules=modules,
            resume_run_id=failed_run.id,
        ),
        RunRequest(
            mode="apply",
            parser_version="command-v1",
            modules=frozenset({"contacts"}),
            resume_run_id=failed_run.id,
        ),
    )
    for incompatible in incompatible_requests:
        with pytest.raises(ReconciliationResumeError):
            await execute_reconciliation(
                command_db, registry, (artifact,), incompatible
            )

    changed_bundle = artifact_for(b"changed")
    with pytest.raises(ReconciliationResumeError, match="fingerprint"):
        await execute_reconciliation(
            command_db,
            registry,
            (changed_bundle,),
            RunRequest(
                mode="apply",
                parser_version="command-v1",
                modules=modules,
                resume_run_id=failed_run.id,
            ),
        )

    summary = await execute_reconciliation(
        command_db,
        registry,
        (artifact,),
        RunRequest(
            mode="apply",
            parser_version="command-v1",
            modules=modules,
            resume_run_id=failed_run.id,
        ),
    )

    assert summary.run_id == failed_run.id
    assert summary.status == "completed"
    assert contacts.parse_calls == 1
    assert tasks.parse_calls == 2
    assert tuple(result.module for result in summary.results) == (
        "contacts",
        "tasks",
    )
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMReconciliationResult)
        )
        == 2
    )
    assert (
        await command_db.scalar(select(func.count()).select_from(CRMSourceRecord)) == 2
    )

    with pytest.raises(ReconciliationResumeError, match="completed"):
        await execute_reconciliation(
            command_db,
            registry,
            (artifact,),
            RunRequest(
                mode="apply",
                parser_version="command-v1",
                modules=modules,
                resume_run_id=failed_run.id,
            ),
        )


async def test_missing_resume_run_is_rejected(command_db):
    from services.command_reconciliation import (
        ReconciliationResumeError,
        RunRequest,
        execute_reconciliation,
    )

    with pytest.raises(ReconciliationResumeError, match="not found"):
        await execute_reconciliation(
            command_db,
            registry_for(FakeParser("contacts", [parse_result(module="contacts")])),
            (),
            RunRequest(
                mode="dry_run",
                parser_version="command-v1",
                modules=frozenset({"contacts"}),
                resume_run_id=999,
            ),
        )


async def test_fingerprint_and_parser_selection_failures_create_no_audit_run(
    command_db,
):
    from services.command_reconciliation import RunRequest, execute_reconciliation

    invalid = artifact_for()
    invalid = ArchiveArtifactInput(
        id=invalid.id,
        source_path=invalid.source_path,
        domain=invalid.domain,
        artifact_type=invalid.artifact_type,
        filename=invalid.filename,
        sha256="0" * 64,
        size_bytes=invalid.size_bytes,
        content_bytes=invalid.content_bytes,
    )
    request = RunRequest(
        mode="dry_run",
        parser_version="command-v1",
        modules=frozenset({"contacts"}),
    )
    with pytest.raises(ValueError, match="checksum"):
        await execute_reconciliation(command_db, ParserRegistry(), (invalid,), request)

    with pytest.raises(UnknownParserModuleError):
        await execute_reconciliation(command_db, ParserRegistry(), (), request)

    assert (
        await command_db.scalar(select(func.count()).select_from(CRMReconciliationRun))
        == 0
    )


async def test_parser_module_mutation_is_rejected_before_affected_parse(command_db):
    from services.command_reconciliation import RunRequest, execute_reconciliation

    artifact = artifact_for()
    await seed_artifacts(command_db, artifact)
    tasks = FakeParser("tasks", [parse_result(module="tasks")])
    contacts = FakeParser(
        "contacts",
        [parse_result(module="contacts")],
        before_return=lambda: setattr(tasks, "module", "changed"),
    )

    with pytest.raises(ParserRegistryError, match="now reports"):
        await execute_reconciliation(
            command_db,
            registry_for(tasks, contacts),
            (artifact,),
            RunRequest(
                mode="dry_run",
                parser_version="command-v1",
                modules=frozenset({"contacts", "tasks"}),
            ),
        )

    assert contacts.parse_calls == 1
    assert tasks.parse_calls == 0
    run = await command_db.scalar(select(CRMReconciliationRun))
    assert run is not None
    assert run.status == "failed"
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMReconciliationResult)
        )
        == 1
    )


async def test_result_module_mismatch_marks_run_failed(command_db):
    from services.command_reconciliation import (
        ReconciliationRunError,
        RunRequest,
        execute_reconciliation,
    )

    parser = FakeParser("contacts", [parse_result(module="tasks")])
    with pytest.raises(ReconciliationRunError, match="module"):
        await execute_reconciliation(
            command_db,
            registry_for(parser),
            (),
            RunRequest(
                mode="dry_run",
                parser_version="command-v1",
                modules=frozenset({"contacts"}),
            ),
        )

    run = await command_db.scalar(select(CRMReconciliationRun))
    assert run is not None
    assert run.status == "failed"
    assert "module" in run.error_text
    assert (
        await command_db.scalar(
            select(func.count()).select_from(CRMReconciliationResult)
        )
        == 0
    )


async def test_failure_error_text_is_bounded_to_database_safe_length(command_db):
    from services.command_reconciliation import RunRequest, execute_reconciliation

    parser = FakeParser("contacts", [RuntimeError("x" * 5000)])
    with pytest.raises(RuntimeError):
        await execute_reconciliation(
            command_db,
            registry_for(parser),
            (),
            RunRequest(
                mode="dry_run",
                parser_version="command-v1",
                modules=frozenset({"contacts"}),
            ),
        )

    run = await command_db.scalar(select(CRMReconciliationRun))
    assert run is not None
    assert len(run.error_text) == 4000


def test_backend_requirements_pin_async_sqlite_driver():
    requirements = Path(__file__).parents[1].joinpath("requirements.txt").read_text()

    assert "aiosqlite==0.21.0" in requirements.splitlines()
