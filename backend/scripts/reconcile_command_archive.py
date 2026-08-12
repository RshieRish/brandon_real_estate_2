"""Safely audit or reconcile the recovered Command and DocuSign archive.

Apply mode requires the caller to provide the exact fingerprint of the archive
currently stored in the database.  The comparison happens before a
reconciliation run is created, so a stale or mistyped fingerprint cannot cause
semantic source-record writes.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models.command import CRMArchiveArtifact
from services.command_parsers import ModuleMetrics, default_parser_registry
from services.command_provenance import ArchiveArtifactInput, bundle_fingerprint
from services.command_reconciliation import (
    ReconciliationSummary,
    RunRequest,
    execute_reconciliation,
)


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the reconciliation command without opening a database session."""
    parser = argparse.ArgumentParser(
        description="Audit or reconcile the recovered Command archive",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    parser.add_argument("--parser-version", required=True)
    parser.add_argument("--module", dest="modules", action="append", default=[])
    parser.add_argument("--resume", type=_positive_integer)
    parser.add_argument("--expect-fingerprint")
    return parser.parse_args(argv)


def validate_apply_args(args: argparse.Namespace) -> None:
    """Require an explicit archive identity before apply can access the DB."""
    if args.apply and not args.expect_fingerprint:
        raise ValueError("--apply requires --expect-fingerprint")


async def load_artifacts(db: AsyncSession) -> tuple[ArchiveArtifactInput, ...]:
    """Load private artifact bytes deterministically by canonical source path."""
    rows = (
        await db.scalars(
            select(CRMArchiveArtifact).order_by(CRMArchiveArtifact.source_path)
        )
    ).all()
    return tuple(
        ArchiveArtifactInput(
            id=row.id,
            source_path=row.source_path,
            domain=row.domain,
            artifact_type=row.artifact_type,
            filename=row.filename,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            content_bytes=(
                bytes(row.content_bytes) if row.content_bytes is not None else None
            ),
        )
        for row in rows
    )


def _mode(args: argparse.Namespace) -> str:
    if args.apply:
        return "apply"
    if args.verify_only:
        return "verify_only"
    return "dry_run"


async def run_reconciliation(
    db: AsyncSession,
    args: argparse.Namespace,
) -> ReconciliationSummary:
    """Run the selected safe mode against one database session."""
    validate_apply_args(args)
    artifacts = await load_artifacts(db)
    fingerprint = bundle_fingerprint(artifacts)
    if args.apply and args.expect_fingerprint != fingerprint:
        raise ValueError(
            "--expect-fingerprint does not match the computed archive fingerprint"
        )

    request = RunRequest(
        mode=_mode(args),
        parser_version=args.parser_version,
        modules=frozenset(args.modules),
        resume_run_id=args.resume,
    )
    return await execute_reconciliation(
        db,
        default_parser_registry(),
        artifacts,
        request,
    )


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(
            (_json_value(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    return value


def _metric_payload(metrics: ModuleMetrics) -> dict[str, object]:
    return {
        "source_system": metrics.source_system,
        "module": metrics.module,
        "expected_count": metrics.expected_count,
        "observed_count": metrics.observed_count,
        "rendered_count": metrics.rendered_count,
        "normalized_count": metrics.normalized_count,
        "evidence_only_count": metrics.evidence_only_count,
        "unmatched_count": metrics.unmatched_count,
        "duplicate_content_count": metrics.duplicate_content_count,
        "error_count": metrics.error_count,
        "details": _json_value(metrics.details),
    }


def summary_json(summary: ReconciliationSummary) -> str:
    """Serialize one reconciliation summary as compact deterministic JSON."""
    payload = {
        "run_id": summary.run_id,
        "status": summary.status,
        "bundle_fingerprint": summary.bundle_fingerprint,
        "modules": [_metric_payload(metrics) for metrics in summary.results],
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


async def _run_with_database(args: argparse.Namespace) -> ReconciliationSummary:
    async with AsyncSessionLocal() as db:
        return await run_reconciliation(db, args)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    validate_apply_args(args)
    summary = asyncio.run(_run_with_database(args))
    print(summary_json(summary))


if __name__ == "__main__":
    main()
