"""Durable, resumable orchestration for Command archive reconciliation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import secrets
from typing import Literal

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.command import CRMArchiveArtifact
from models.command_provenance import (
    CRMReconciliationResult,
    CRMReconciliationRun,
)
from services.command_parsers import (
    ModuleMetrics,
    ParserRegistry,
    validate_parser_module,
)
from services.command_provenance import (
    ArchiveArtifactInput,
    SourceRecordDraft,
    bundle_fingerprint,
    persist_source_records,
)


_CLAIM_LEASE = timedelta(minutes=30)


class ReconciliationRunError(RuntimeError):
    """Raised when a selected parser produces an unsafe run result."""


class ReconciliationResumeError(ReconciliationRunError):
    """Raised when an audit run cannot be resumed safely."""


@dataclass(frozen=True, slots=True)
class RunRequest:
    mode: Literal["dry_run", "apply", "verify_only"]
    parser_version: str
    modules: frozenset[str] = field(default_factory=frozenset)
    resume_run_id: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"dry_run", "apply", "verify_only"}:
            raise ValueError("mode must be dry_run, apply, or verify_only")
        if not isinstance(self.parser_version, str) or not self.parser_version.strip():
            raise ValueError("parser_version must be nonblank")
        if not isinstance(self.modules, set | frozenset):
            raise ValueError("modules must be a set or frozenset")
        modules = frozenset(self.modules)
        if any(not isinstance(module, str) or not module.strip() for module in modules):
            raise ValueError("modules must contain nonblank strings")
        object.__setattr__(self, "modules", modules)
        if self.mode == "verify_only" and modules not in {
            frozenset(),
            frozenset({"archive_integrity"}),
        }:
            raise ValueError(
                "verify_only modules must be empty or {'archive_integrity'}"
            )
        if self.resume_run_id is not None and (
            type(self.resume_run_id) is not int or self.resume_run_id <= 0
        ):
            raise ReconciliationResumeError("resume_run_id must be a positive integer")


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    run_id: int
    status: str
    bundle_fingerprint: str
    results: tuple[ModuleMetrics, ...]


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, set | frozenset):
        converted = [_json_value(item) for item in value]
        return sorted(
            converted,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            _json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReconciliationRunError(
            "reconciliation data must be canonical JSON-serializable"
        ) from exc


def _requested_modules_json(modules: frozenset[str]) -> str:
    return _canonical_json(sorted(modules))


def _selected_modules(
    registry: ParserRegistry,
    request: RunRequest,
) -> frozenset[str]:
    if request.mode == "verify_only":
        return frozenset({"archive_integrity"})
    if request.modules:
        return request.modules
    return registry.registered_modules()


def _stored_module_set(run: CRMReconciliationRun) -> frozenset[str]:
    try:
        value = json.loads(run.requested_modules_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReconciliationResumeError("stored requested modules are invalid") from exc
    if not isinstance(value, list) or any(
        not isinstance(module, str) for module in value
    ):
        raise ReconciliationResumeError("stored requested modules are invalid")
    return frozenset(value)


def _validate_resume(
    run: CRMReconciliationRun,
    *,
    fingerprint: str,
    parser_version: str,
    mode: str,
    modules: frozenset[str],
) -> None:
    if run.status not in {"failed", "running"}:
        raise ReconciliationResumeError(
            f"reconciliation run {run.id} is {run.status} and cannot be resumed"
        )
    if run.bundle_fingerprint != fingerprint:
        raise ReconciliationResumeError("resume bundle fingerprint does not match")
    if run.parser_version != parser_version:
        raise ReconciliationResumeError("resume parser version does not match")
    if run.mode != mode:
        raise ReconciliationResumeError("resume mode does not match")
    if _stored_module_set(run) != modules:
        raise ReconciliationResumeError("resume requested module set does not match")


def _result_row(
    run_id: int,
    metrics: ModuleMetrics,
    *,
    normalized_count: int,
) -> CRMReconciliationResult:
    return CRMReconciliationResult(
        run_id=run_id,
        source_system=metrics.source_system,
        module=metrics.module,
        expected_count=metrics.expected_count,
        observed_count=metrics.observed_count,
        rendered_count=metrics.rendered_count,
        normalized_count=normalized_count,
        evidence_only_count=metrics.evidence_only_count,
        unmatched_count=metrics.unmatched_count,
        duplicate_content_count=metrics.duplicate_content_count,
        error_count=metrics.error_count,
        details_json=_canonical_json(metrics.details),
    )


def _owned_run_update(run_id: int, claim_token: str):
    """Build the conditional UPDATE that holds a PostgreSQL row lock to commit."""
    return (
        update(CRMReconciliationRun)
        .where(
            CRMReconciliationRun.id == run_id,
            CRMReconciliationRun.status == "running",
            CRMReconciliationRun.claim_token == claim_token,
        )
        .execution_options(synchronize_session=False)
    )


def _validate_result_records(
    records: Sequence[SourceRecordDraft],
    *,
    parser_version: str,
    artifacts_by_path: Mapping[str, ArchiveArtifactInput],
) -> None:
    for draft in records:
        if draft.parser_version != parser_version:
            raise ReconciliationRunError(
                "source draft parser_version does not match reconciliation request: "
                f"expected {parser_version!r}, got {draft.parser_version!r}"
            )
        for path in draft.artifact_paths:
            if path not in artifacts_by_path:
                raise ReconciliationRunError(
                    f"source draft artifact is outside the fingerprinted bundle: {path}"
                )


async def _validate_bundle_catalog(
    db: AsyncSession,
    artifacts_by_path: Mapping[str, ArchiveArtifactInput],
) -> None:
    """Require every fingerprinted artifact to match its catalog row exactly."""
    if not artifacts_by_path:
        return
    catalog_rows = await db.scalars(
        select(CRMArchiveArtifact).where(
            CRMArchiveArtifact.source_path.in_(artifacts_by_path)
        )
    )
    catalog_by_path = {row.source_path: row for row in catalog_rows}
    missing_paths = set(artifacts_by_path).difference(catalog_by_path)
    if missing_paths:
        raise ReconciliationRunError(
            "fingerprinted bundle artifacts are missing from the archive catalog: "
            + ", ".join(sorted(missing_paths))
        )

    for path in sorted(artifacts_by_path):
        artifact = artifacts_by_path[path]
        catalog = catalog_by_path[path]
        if catalog.id != artifact.id:
            raise ReconciliationRunError(
                f"archive artifact id mismatch for {path}: "
                f"bundle={artifact.id}, catalog={catalog.id}"
            )
        if catalog.sha256 != artifact.sha256:
            raise ReconciliationRunError(f"archive artifact hash mismatch for {path}")
        if catalog.size_bytes != artifact.size_bytes:
            raise ReconciliationRunError(
                f"archive artifact size mismatch for {path}: "
                f"bundle={artifact.size_bytes}, catalog={catalog.size_bytes}"
            )


async def _summary(db: AsyncSession, run_id: int) -> ReconciliationSummary:
    run = await db.get(CRMReconciliationRun, run_id)
    if run is None:
        raise ReconciliationRunError(f"reconciliation run {run_id} not found")
    rows = (
        await db.scalars(
            select(CRMReconciliationResult)
            .where(CRMReconciliationResult.run_id == run_id)
            .order_by(
                CRMReconciliationResult.source_system,
                CRMReconciliationResult.module,
            )
        )
    ).all()
    results = tuple(
        ModuleMetrics(
            source_system=row.source_system,
            module=row.module,
            expected_count=row.expected_count,
            observed_count=row.observed_count,
            rendered_count=row.rendered_count,
            normalized_count=row.normalized_count,
            evidence_only_count=row.evidence_only_count,
            unmatched_count=row.unmatched_count,
            duplicate_content_count=row.duplicate_content_count,
            error_count=row.error_count,
            details=json.loads(row.details_json),
        )
        for row in rows
    )
    return ReconciliationSummary(
        run_id=run.id,
        status=run.status,
        bundle_fingerprint=run.bundle_fingerprint,
        results=results,
    )


async def _mark_failed(
    db: AsyncSession,
    run_id: int,
    claim_token: str,
    error: Exception,
) -> None:
    await db.rollback()
    result = await db.execute(
        _owned_run_update(run_id, claim_token).values(
            status="failed",
            error_text=str(error)[:4000],
            completed_at=datetime.now(UTC),
            claim_token="",
            claimed_at=None,
        )
    )
    if result.rowcount == 1:
        await db.commit()
        db.expire_all()
    else:
        await db.rollback()


async def _claim_resume_run(
    db: AsyncSession,
    run_id: int,
    claim_token: str,
) -> None:
    now = datetime.now(UTC)
    stale_before = now - _CLAIM_LEASE
    result = await db.execute(
        update(CRMReconciliationRun)
        .where(
            CRMReconciliationRun.id == run_id,
            or_(
                CRMReconciliationRun.status == "failed",
                and_(
                    CRMReconciliationRun.status == "running",
                    or_(
                        CRMReconciliationRun.claim_token == "",
                        CRMReconciliationRun.claimed_at.is_(None),
                        CRMReconciliationRun.claimed_at < stale_before,
                    ),
                ),
            ),
        )
        .values(
            status="running",
            error_text="",
            completed_at=None,
            claim_token=claim_token,
            claimed_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise ReconciliationResumeError(
            f"reconciliation run {run_id} is already claimed by another worker"
        )
    await db.commit()
    db.expire_all()


async def _lock_module_claim(
    db: AsyncSession,
    run_id: int,
    claim_token: str,
) -> None:
    """Lock ownership through the module commit on PostgreSQL and SQLite."""
    result = await db.execute(
        _owned_run_update(run_id, claim_token).values(claimed_at=datetime.now(UTC))
    )
    if result.rowcount != 1:
        await db.rollback()
        raise ReconciliationResumeError(f"reconciliation run {run_id} claim was lost")


async def _complete_claimed_run(
    db: AsyncSession,
    run_id: int,
    claim_token: str,
) -> None:
    result = await db.execute(
        _owned_run_update(run_id, claim_token).values(
            status="completed",
            error_text="",
            completed_at=datetime.now(UTC),
            claim_token="",
            claimed_at=None,
        )
    )
    if result.rowcount != 1:
        await db.rollback()
        raise ReconciliationResumeError(
            f"reconciliation run {run_id} claim was lost before completion"
        )
    await db.commit()
    db.expire_all()


async def execute_reconciliation(
    db: AsyncSession,
    registry: ParserRegistry,
    artifacts: Iterable[ArchiveArtifactInput],
    request: RunRequest,
) -> ReconciliationSummary:
    """Execute selected parsers with durable, resumable module boundaries."""
    if not isinstance(request, RunRequest):
        raise ReconciliationRunError("request must be a RunRequest")
    materialized_artifacts = tuple(artifacts)
    fingerprint = bundle_fingerprint(materialized_artifacts)
    artifacts_by_path = {
        artifact.source_path: artifact for artifact in materialized_artifacts
    }
    selected_modules = _selected_modules(registry, request)
    requested_modules_json = _requested_modules_json(selected_modules)
    claim_token = secrets.token_hex(32)

    if request.resume_run_id is None:
        run = CRMReconciliationRun(
            bundle_fingerprint=fingerprint,
            parser_version=request.parser_version,
            mode=request.mode,
            status="running",
            requested_modules_json=requested_modules_json,
            error_text="",
            claim_token=claim_token,
            claimed_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()
        run_id = run.id
        await db.commit()
    else:
        run = await db.get(CRMReconciliationRun, request.resume_run_id)
        if run is None:
            raise ReconciliationResumeError(
                f"reconciliation run {request.resume_run_id} not found"
            )
        _validate_resume(
            run,
            fingerprint=fingerprint,
            parser_version=request.parser_version,
            mode=request.mode,
            modules=selected_modules,
        )
        run_id = run.id
        await _claim_resume_run(db, run_id, claim_token)

    try:
        await _validate_bundle_catalog(db, artifacts_by_path)
        parsers = registry.select(selected_modules)
        selected = tuple((parser.module, parser) for parser in parsers)
        completed_modules = set(
            await db.scalars(
                select(CRMReconciliationResult.module).where(
                    CRMReconciliationResult.run_id == run_id
                )
            )
        )
        for expected_module, parser in selected:
            if expected_module in completed_modules:
                continue
            validate_parser_module(parser, expected_module)
            result = parser.parse(
                materialized_artifacts,
                request.parser_version,
            )
            if result.metrics.module != expected_module:
                raise ReconciliationRunError(
                    "parser result module does not match selected module: "
                    f"expected {expected_module!r}, got {result.metrics.module!r}"
                )
            _validate_result_records(
                result.records,
                parser_version=request.parser_version,
                artifacts_by_path=artifacts_by_path,
            )
            await _lock_module_claim(db, run_id, claim_token)
            normalized_count = result.metrics.normalized_count
            if request.mode == "apply":
                await persist_source_records(db, result.records)
                normalized_count = len(result.records)
            db.add(
                _result_row(
                    run_id,
                    result.metrics,
                    normalized_count=normalized_count,
                )
            )
            await db.commit()

        await _complete_claimed_run(db, run_id, claim_token)
    except Exception as exc:
        await _mark_failed(db, run_id, claim_token, exc)
        raise

    return await _summary(db, run_id)


__all__ = (
    "ReconciliationResumeError",
    "ReconciliationRunError",
    "ReconciliationSummary",
    "RunRequest",
    "execute_reconciliation",
)
