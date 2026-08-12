"""Authenticated read-only access to recovered source evidence and audits."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import require_admin
from models.command import CRMArchiveArtifact
from models.command_provenance import (
    CRMEntitySource,
    CRMReconciliationResult,
    CRMReconciliationRun,
    CRMSourceRecord,
    CRMSourceRecordArtifact,
    CaptureQuality,
    EvidenceLevel,
)
from schemas.command_provenance import (
    ArchiveArtifactMetadataOut,
    EntitySourcesOut,
    ReconciliationResultOut,
    ReconciliationRunDetailOut,
    ReconciliationRunOut,
    ReconciliationRunPageOut,
    SourceRecordDetailOut,
    SourceRecordOut,
    SourceRecordPageOut,
)


_optional_admin_bearer = HTTPBearer(auto_error=False)


def _require_admin_bearer(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_optional_admin_bearer),
    ],
) -> None:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )


router = APIRouter(
    dependencies=[Depends(_require_admin_bearer), Depends(require_admin)]
)

ALLOWED_ENTITY_TYPES = frozenset(
    {
        "activity",
        "agreement",
        "agreement_event",
        "agreement_recipient",
        "agreement_template",
        "analytics_event",
        "booking",
        "contact",
        "content_block",
        "file_asset",
        "funnel",
        "goal",
        "lead",
        "listing",
        "marketing_campaign",
        "marketing_design",
        "note",
        "opportunity",
        "opportunity_contact",
        "opportunity_offer",
        "opportunity_vendor",
        "referral",
        "report",
        "saved_search",
        "smart_plan",
        "smart_plan_enrollment",
        "smart_plan_step",
        "tag",
        "task",
        "task_link",
        "website",
    }
)


def _json_object(value: str, field_name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Stored {field_name} is not valid JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=500,
            detail=f"Stored {field_name} is not a JSON object",
        )
    return parsed


def _json_string_list(value: str, field_name: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Stored {field_name} is not valid JSON",
        ) from exc
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) for item in parsed
    ):
        raise HTTPException(
            status_code=500,
            detail=f"Stored {field_name} is not a JSON string list",
        )
    return parsed


def _source_out(record: CRMSourceRecord) -> SourceRecordOut:
    return SourceRecordOut(
        id=record.id,
        source_system=record.source_system,
        module=record.module,
        record_kind=record.record_kind,
        source_key=record.source_key,
        evidence_level=record.evidence_level,
        display_label=record.display_label,
        payload=_json_object(record.payload_json, "source-record payload"),
        capture_quality=record.capture_quality,
        captured_at=record.captured_at,
        parser_version=record.parser_version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _artifact_out(
    link: CRMSourceRecordArtifact,
    artifact: CRMArchiveArtifact,
) -> ArchiveArtifactMetadataOut:
    return ArchiveArtifactMetadataOut(
        id=artifact.id,
        domain=artifact.domain,
        artifact_type=artifact.artifact_type,
        filename=artifact.filename,
        source_path=artifact.source_path,
        sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
        text_preview=artifact.text_preview,
        relation=link.relation,
    )


async def _artifact_map(
    db: AsyncSession,
    source_record_ids: Sequence[int],
) -> dict[int, list[ArchiveArtifactMetadataOut]]:
    grouped: dict[int, list[ArchiveArtifactMetadataOut]] = defaultdict(list)
    if not source_record_ids:
        return grouped
    statement = (
        select(CRMSourceRecordArtifact, CRMArchiveArtifact)
        .join(
            CRMArchiveArtifact,
            CRMArchiveArtifact.id == CRMSourceRecordArtifact.artifact_id,
        )
        .where(CRMSourceRecordArtifact.source_record_id.in_(source_record_ids))
        .order_by(
            CRMSourceRecordArtifact.source_record_id.asc(),
            CRMArchiveArtifact.source_path.asc(),
            CRMArchiveArtifact.id.asc(),
            CRMSourceRecordArtifact.id.asc(),
        )
    )
    for link, artifact in (await db.execute(statement)).all():
        grouped[link.source_record_id].append(_artifact_out(link, artifact))
    return grouped


def _source_detail_out(
    record: CRMSourceRecord,
    artifacts: list[ArchiveArtifactMetadataOut],
) -> SourceRecordDetailOut:
    return SourceRecordDetailOut(
        **_source_out(record).model_dump(),
        artifacts=artifacts,
    )


def _run_out(run: CRMReconciliationRun) -> ReconciliationRunOut:
    return ReconciliationRunOut(
        id=run.id,
        bundle_fingerprint=run.bundle_fingerprint,
        parser_version=run.parser_version,
        mode=run.mode,
        status=run.status,
        requested_modules=_json_string_list(
            run.requested_modules_json,
            "reconciliation requested modules",
        ),
        error_text=run.error_text,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _result_out(result: CRMReconciliationResult) -> ReconciliationResultOut:
    return ReconciliationResultOut(
        id=result.id,
        source_system=result.source_system,
        module=result.module,
        expected_count=result.expected_count,
        observed_count=result.observed_count,
        rendered_count=result.rendered_count,
        normalized_count=result.normalized_count,
        evidence_only_count=result.evidence_only_count,
        unmatched_count=result.unmatched_count,
        duplicate_content_count=result.duplicate_content_count,
        error_count=result.error_count,
        details=_json_object(result.details_json, "reconciliation result details"),
    )


async def _run_detail_out(
    db: AsyncSession,
    run: CRMReconciliationRun,
) -> ReconciliationRunDetailOut:
    statement = (
        select(CRMReconciliationResult)
        .where(CRMReconciliationResult.run_id == run.id)
        .order_by(
            CRMReconciliationResult.source_system.asc(),
            CRMReconciliationResult.module.asc(),
            CRMReconciliationResult.id.asc(),
        )
    )
    results = (await db.execute(statement)).scalars().all()
    return ReconciliationRunDetailOut(
        **_run_out(run).model_dump(),
        results=[_result_out(result) for result in results],
    )


def _literal_search_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/source-records", response_model=SourceRecordPageOut)
async def source_records(
    source_system: Annotated[str | None, Query(max_length=64)] = None,
    module: Annotated[str | None, Query(max_length=64)] = None,
    record_kind: Annotated[str | None, Query(max_length=64)] = None,
    evidence_level: EvidenceLevel | None = None,
    capture_quality: CaptureQuality | None = None,
    query: Annotated[str | None, Query(max_length=500)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    db: AsyncSession = Depends(get_db),
) -> SourceRecordPageOut:
    filters = []
    if source_system is not None:
        filters.append(CRMSourceRecord.source_system == source_system)
    if module is not None:
        filters.append(CRMSourceRecord.module == module)
    if record_kind is not None:
        filters.append(CRMSourceRecord.record_kind == record_kind)
    if evidence_level is not None:
        filters.append(CRMSourceRecord.evidence_level == evidence_level.value)
    if capture_quality is not None:
        filters.append(CRMSourceRecord.capture_quality == capture_quality.value)
    if query is not None:
        pattern = _literal_search_pattern(query)
        filters.append(
            or_(
                CRMSourceRecord.display_label.ilike(pattern, escape="\\"),
                CRMSourceRecord.source_key.ilike(pattern, escape="\\"),
                CRMSourceRecord.payload_json.ilike(pattern, escape="\\"),
            )
        )

    count_statement = select(func.count()).select_from(CRMSourceRecord)
    statement = select(CRMSourceRecord)
    if filters:
        count_statement = count_statement.where(*filters)
        statement = statement.where(*filters)
    total = int((await db.execute(count_statement)).scalar_one())
    statement = statement.order_by(
        CRMSourceRecord.source_system.asc(),
        CRMSourceRecord.module.asc(),
        CRMSourceRecord.source_key.asc(),
        CRMSourceRecord.id.asc(),
    )
    statement = statement.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(statement)).scalars().all()
    return SourceRecordPageOut(
        total=total,
        page=page,
        page_size=page_size,
        rows=[_source_out(record) for record in rows],
    )


@router.get("/source-records/{record_id}", response_model=SourceRecordDetailOut)
async def source_record_detail(
    record_id: Annotated[int, Path(gt=0)],
    db: AsyncSession = Depends(get_db),
) -> SourceRecordDetailOut:
    record = await db.get(CRMSourceRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Source record not found")
    artifacts = await _artifact_map(db, [record.id])
    return _source_detail_out(record, artifacts.get(record.id, []))


@router.get(
    "/entities/{entity_type}/{entity_id}/sources",
    response_model=EntitySourcesOut,
)
async def entity_sources(
    entity_type: Annotated[str, Path(min_length=1, max_length=64)],
    entity_id: Annotated[int, Path(gt=0)],
    db: AsyncSession = Depends(get_db),
) -> EntitySourcesOut:
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported entity type")
    statement = (
        select(CRMSourceRecord)
        .join(
            CRMEntitySource,
            CRMEntitySource.source_record_id == CRMSourceRecord.id,
        )
        .where(
            CRMEntitySource.entity_type == entity_type,
            CRMEntitySource.entity_id == entity_id,
        )
        .order_by(
            CRMSourceRecord.source_system.asc(),
            CRMSourceRecord.module.asc(),
            CRMSourceRecord.source_key.asc(),
            CRMSourceRecord.id.asc(),
        )
    )
    records = (await db.execute(statement)).scalars().all()
    artifacts = await _artifact_map(db, [record.id for record in records])
    return EntitySourcesOut(
        entity_type=entity_type,
        entity_id=entity_id,
        sources=[
            _source_detail_out(record, artifacts.get(record.id, []))
            for record in records
        ],
    )


@router.get("/reconciliation/runs", response_model=ReconciliationRunPageOut)
async def reconciliation_runs(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRunPageOut:
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(CRMReconciliationRun)
            )
        ).scalar_one()
    )
    statement = (
        select(CRMReconciliationRun)
        .order_by(
            CRMReconciliationRun.started_at.desc(),
            CRMReconciliationRun.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(statement)).scalars().all()
    return ReconciliationRunPageOut(
        total=total,
        page=page,
        page_size=page_size,
        rows=[_run_out(run) for run in rows],
    )


@router.get(
    "/reconciliation/runs/latest",
    response_model=ReconciliationRunDetailOut,
)
async def latest_reconciliation_run(
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRunDetailOut:
    statement = select(CRMReconciliationRun).order_by(
        CRMReconciliationRun.started_at.desc(),
        CRMReconciliationRun.id.desc(),
    )
    run = (await db.execute(statement.limit(1))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    return await _run_detail_out(db, run)


@router.get(
    "/reconciliation/runs/{run_id}",
    response_model=ReconciliationRunDetailOut,
)
async def reconciliation_run_detail(
    run_id: Annotated[int, Path(gt=0)],
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRunDetailOut:
    run = await db.get(CRMReconciliationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    return await _run_detail_out(db, run)
