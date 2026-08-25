from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Response,
    UploadFile,
    status,
)
from pydantic import BeforeValidator, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth import AdminSubject, require_admin
from models.analytics_event import AnalyticsEvent
from models.command import (
    AgreementStatus,
    CRMActivity,
    CRMAgreement,
    CRMAgreementEvent,
    CRMAgreementRecipient,
    CRMAgreementTemplate,
    CRMArchiveArtifact,
    CRMContact,
    CRMFileAsset,
    CRMGoal,
    CRMListingRecord,
    CRMNote,
    CRMOpportunity,
    CRMOpportunityContact,
    CRMOpportunityOffer,
    CRMOpportunityVendor,
    CRMReferral,
    CRMSmartPlan,
    CRMSmartPlanEnrollment,
    CRMSmartPlanStep,
    CRMTag,
    CRMTask,
    CRMTaskLink,
)
from models.content_block import ContentBlock
from models.funnel import Funnel
from models.lead import Lead
from schemas.command import (
    POSTGRES_INTEGER_MAX,
    AgreementCreate,
    AgreementOut,
    AgreementStatusUpdate,
    ArchiveBundleImportRequest,
    ArchiveBundleImportResult,
    FileAssetCreate,
    FileAssetOut,
    GoalCreate,
    GoalOut,
    GoalUpdate,
    ListingCreate,
    ListingOut,
    ListingStatusUpdate,
    NamedRecordCreate,
    NamedRecordOut,
    OpportunityCreate,
    OpportunityOut,
    OpportunityUpdate,
    OverviewOut,
    ReferralCreate,
    ReferralOut,
    ReferralUpdate,
    RelationshipCreate,
    RelationshipOut,
    SmartPlanEnrollmentCreate,
    SmartPlanEnrollmentUpdate,
    SmartPlanStatusUpdate,
    SmartPlanStepCreate,
    TagCreate,
    TaskCreate,
    TaskBulkArchiveRequest,
    TaskBulkArchiveResponse,
    TaskBulkArchiveResult,
    TaskLinkCreate,
    TaskLinkOut,
    TaskLifecycleRequest,
    TaskOut,
    TaskUpdate,
    TemplateCreate,
    TemplateOut,
    TemplateUpdate,
)
from schemas.command_contacts import (
    ContactDeletedOut,
    SavedSearchOut,
    canonical_saved_search_criteria,
)
from services import command_contacts as contact_service
from services.command_contact_contracts import (
    ContactImportRowCommand,
    ContactMutationResult,
    WorkspaceMutationResult,
)
from services.command_contact_identity import canonical_email
from services.command_contacts import (
    ContactDataIntegrityError,
    ContactLinkConflict,
    ContactNotFound,
    ContactNotInDirectory,
    ContactSectionUnsupported,
)
from services.command_file_storage import upload_command_file
from services.command_geocoding import geocode_listing_address
from services.command_lifecycle import ensure_agreement_transition
from services.command_relationships import is_same_opportunity_contact
from services.command_task_links import task_link_display_name, task_link_model
from services.command_tasks import archive_task_source_key
from services.crm_task_service import (
    CreateTaskCommand,
    TaskActor,
    TaskCommandValidationError,
    TaskContactNotFound,
    TaskCreationStateError,
    TaskIdempotencyConflict,
    TaskLinkedRecordNotFound,
    TaskNotFound,
    TaskSource,
    TaskSourceConflict,
    TaskStateConflict,
    crm_task_service,
)
from services.crm_task_projection import (
    TaskWorkflowStatus,
    active_task_clause,
    archived_task_clause,
    workflow_status_task_clause,
)
from services.gemini import generate_text_flash_lite

router = APIRouter(dependencies=[Depends(require_admin)])

_SAVED_SEARCHES_ADAPTER = TypeAdapter(list[SavedSearchOut])
_DELETED_SEARCH_ADAPTER = TypeAdapter(ContactDeletedOut)
_ARCHIVE_IMPORT_ADAPTER = TypeAdapter(ArchiveBundleImportResult)


def _canonical_http_integer(value: object) -> int:
    if type(value) is int:
        return value
    if (
        type(value) is str
        and value.isascii()
        and value.isdigit()
        and (value == "0" or not value.startswith("0"))
    ):
        return int(value)
    raise ValueError("integer input must be a canonical unsigned decimal")


SavedSearchId = Annotated[
    int,
    Path(gt=0),
    BeforeValidator(_canonical_http_integer),
]
TaskId = Annotated[
    int,
    Path(ge=1, le=POSTGRES_INTEGER_MAX),
    BeforeValidator(_canonical_http_integer),
]


async def _count(db: AsyncSession, model, *where) -> int:
    query = select(func.count()).select_from(model)
    if where: query = query.where(*where)
    return int((await db.execute(query)).scalar_one())


@router.get("/overview", response_model=OverviewOut)
async def overview(db: AsyncSession = Depends(get_db)):
    return OverviewOut(
        contacts=await _count(db, CRMContact), open_tasks=await _count(db, CRMTask, active_task_clause()),
        opportunities=await _count(db, CRMOpportunity), active_smart_plans=await _count(db, CRMSmartPlan, CRMSmartPlan.status == "active"),
    )

@router.get("/goals", response_model=list[GoalOut])
async def goals(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMGoal).order_by(CRMGoal.updated_at.desc()))).scalars().all()

@router.post("/goals", response_model=GoalOut)
async def create_goal(payload: GoalCreate, db: AsyncSession = Depends(get_db)):
    item = CRMGoal(**payload.model_dump()); db.add(item); await db.flush(); return item

@router.patch("/goals/{goal_id}", response_model=GoalOut)
async def update_goal_progress(goal_id: int, payload: GoalUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMGoal, goal_id)
    if not item: raise HTTPException(404, "Goal not found")
    item.current_value = payload.current_value; await db.flush(); return item

@router.get("/ai/briefing")
async def ai_briefing(db: AsyncSession = Depends(get_db)):
    """Deterministic, auditable pre-AI briefing; no contact data leaves the API."""
    open_tasks = await _count(db, CRMTask, active_task_clause())
    contacts = await _count(db, CRMContact)
    opportunities = await _count(db, CRMOpportunity)
    return {"summary": f"{open_tasks} open tasks across {contacts} contacts and {opportunities} opportunities.", "source": "internal-crm", "requires_review": True}

@router.post("/ai/briefing/generate")
async def generate_ai_briefing(db:AsyncSession=Depends(get_db)):
    if not settings.GEMINI_API_KEY:
        raise HTTPException(503,"AI briefing is not configured")
    metrics=await reports_summary(db)
    prompt=("Write a concise internal real-estate CRM morning briefing from these aggregate metrics: "
            f"{metrics}. Give only prioritized next actions. Do not claim actions were completed, do not give legal advice, and do not include private contact data.")
    try:
        summary=await generate_text_flash_lite(prompt)
    except Exception as exc:
        raise HTTPException(502, "AI briefing generation failed") from exc
    db.add(CRMActivity(kind="ai_briefing_generated",summary="Generated review-only AI briefing",metadata_json='{"scope":"aggregate_metrics"}'))
    await db.flush()
    return {"summary":summary,"source":"gemini-aggregate-internal-metrics","requires_review":True}

@router.get("/reports/summary")
async def reports_summary(db:AsyncSession=Depends(get_db)):
    return {"contacts":await _count(db,CRMContact),"leads":await _count(db,Lead),"open_tasks":await _count(db,CRMTask,active_task_clause()),"opportunities":await _count(db,CRMOpportunity),"agreements":await _count(db,CRMAgreement),"events":await _count(db,AnalyticsEvent)}


@router.get("/archive/artifacts")
async def archive_artifacts(domain: str | None = None, artifact_type: str | None = None, limit: int = 100, offset: int = 0, db: AsyncSession = Depends(get_db)):
    """Browse the complete private recovered-archive catalog."""
    statement = select(CRMArchiveArtifact).order_by(CRMArchiveArtifact.source_path)
    if domain:
        statement = statement.where(CRMArchiveArtifact.domain == domain)
    if artifact_type:
        statement = statement.where(CRMArchiveArtifact.artifact_type == artifact_type)
    count_statement = select(func.count()).select_from(CRMArchiveArtifact)
    if domain:
        count_statement = count_statement.where(CRMArchiveArtifact.domain == domain)
    if artifact_type:
        count_statement = count_statement.where(CRMArchiveArtifact.artifact_type == artifact_type)
    total = int((await db.execute(count_statement)).scalar_one())
    rows = (await db.execute(statement.offset(max(offset, 0)).limit(min(max(limit, 1), 200)))).scalars().all()
    return {"total": total, "rows": [{"id": row.id, "domain": row.domain, "artifact_type": row.artifact_type, "filename": row.filename, "source_path": row.source_path, "sha256": row.sha256, "size_bytes": row.size_bytes, "text_preview": row.text_preview} for row in rows]}


@router.get("/archive/artifacts/{artifact_id}/content")
async def archive_artifact_content(artifact_id: int, db: AsyncSession = Depends(get_db)):
    """Return an original recovered artifact only to an authenticated admin."""
    artifact = await db.get(CRMArchiveArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Recovered artifact not found")
    if artifact.content_bytes is None:
        raise HTTPException(409, "Recovered artifact bytes are not yet stored internally")
    media_type = {"html": "text/html", "json": "application/json", "txt": "text/plain", "csv": "text/csv", "zip": "application/zip", "png": "image/png", "pdf": "application/pdf"}.get(artifact.artifact_type, "application/octet-stream")
    safe_name = artifact.filename.replace('"', "")
    return Response(content=artifact.content_bytes, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{safe_name}"', "X-Content-Type-Options": "nosniff"})


@router.get("/reports/details/{metric}")
async def report_details(metric: str, db: AsyncSession = Depends(get_db)):
    """Bounded, read-only drilldown behind a Command report card."""
    if metric == "contacts":
        rows = (await db.execute(select(CRMContact).order_by(CRMContact.updated_at.desc()).limit(25))).scalars().all()
        data = [{"id": row.id, "title": f"{row.first_name} {row.last_name}".strip(), "detail": row.stage, "occurred_at": row.updated_at} for row in rows]
    elif metric == "leads":
        rows = (await db.execute(select(Lead).order_by(Lead.updated_at.desc()).limit(25))).scalars().all()
        data = [{"id": row.id, "title": row.name or "Unnamed lead", "detail": f"{row.routing_status} · {row.source or 'internal'}", "occurred_at": row.updated_at} for row in rows]
    elif metric == "open_tasks":
        rows = (await db.execute(select(CRMTask).where(active_task_clause()).order_by(CRMTask.due_at.asc().nulls_last()).limit(25))).scalars().all()
        data = [{"id": row.id, "title": row.title, "detail": f"{row.status} · {row.priority}", "occurred_at": row.due_at or row.updated_at} for row in rows]
    elif metric == "opportunities":
        rows = (await db.execute(select(CRMOpportunity).order_by(CRMOpportunity.updated_at.desc()).limit(25))).scalars().all()
        data = [{"id": row.id, "title": row.name, "detail": f"{row.stage}{f' · ${(row.value_cents or 0) / 100:,.0f}' if row.value_cents else ''}", "occurred_at": row.updated_at} for row in rows]
    elif metric == "agreements":
        rows = (await db.execute(select(CRMAgreement).order_by(CRMAgreement.updated_at.desc()).limit(25))).scalars().all()
        data = [{"id": row.id, "title": row.title, "detail": row.status, "occurred_at": row.updated_at} for row in rows]
    elif metric == "events":
        rows = (await db.execute(select(AnalyticsEvent).order_by(AnalyticsEvent.created_at.desc()).limit(25))).scalars().all()
        data = [{"id": row.id, "title": row.event_type, "detail": row.page or "No page recorded", "occurred_at": row.created_at} for row in rows]
    else:
        raise HTTPException(404, "Unknown report metric")
    return {"metric": metric, "rows": data}

@router.get("/growth/summary")
async def growth_summary(db:AsyncSession=Depends(get_db)):
    return {"content_blocks":await _count(db,ContentBlock),"funnels":await _count(db,Funnel),"leads":await _count(db,Lead),"analytics_events":await _count(db,AnalyticsEvent)}


@router.get("/marketing/records")
async def marketing_records(db: AsyncSession = Depends(get_db)):
    blocks = (await db.execute(select(ContentBlock).order_by(ContentBlock.updated_at.desc()).limit(100))).scalars().all()
    funnels = (await db.execute(select(Funnel).order_by(Funnel.updated_at.desc()).limit(100))).scalars().all()
    return {
        "content_blocks": [{"id": item.id, "block_id": item.block_id, "page": item.page, "content_type": item.content_type, "updated_at": item.updated_at} for item in blocks],
        "funnels": [{"id": item.id, "title": item.title, "slug": item.slug, "audience": item.audience, "status": item.status, "registrations": item.registrations, "updated_at": item.updated_at} for item in funnels],
    }


@router.get("/websites/records")
async def website_records(db: AsyncSession = Depends(get_db)):
    blocks = (await db.execute(select(ContentBlock).order_by(ContentBlock.page.asc().nulls_last(), ContentBlock.updated_at.desc()).limit(200))).scalars().all()
    return {"pages": [{"id": item.id, "block_id": item.block_id, "page": item.page or "unassigned", "content_type": item.content_type, "updated_at": item.updated_at} for item in blocks]}


@router.get("/reports/event-breakdown")
async def event_breakdown(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AnalyticsEvent.event_type, func.count(AnalyticsEvent.id)).group_by(AnalyticsEvent.event_type).order_by(func.count(AnalyticsEvent.id).desc()).limit(25))).all()
    return {"events": [{"event_type": event_type, "count": int(count)} for event_type, count in rows]}


async def _import_archive_bundle(
    payload: ArchiveBundleImportRequest,
    db: AsyncSession,
    contact_rows: tuple[ContactImportRowCommand, ...],
    referenced_emails: tuple[str | None, ...],
    *,
    actor_subject: str,
):
    created = {key: 0 for key in ("contacts", "tasks", "notes", "opportunities", "referrals", "listings", "templates", "agreements")}
    skipped = {key: 0 for key in created}
    unresolved = 0
    contact_result = await contact_service.ingest_archive_contacts(
        db,
        contact_rows,
        referenced_emails,
        actor_subject=actor_subject,
    )
    created["contacts"] = contact_result.created
    skipped["contacts"] = contact_result.skipped_duplicates
    owner_ids = contact_result.owner_contact_ids_by_normalized_email

    def resolve(email: str | None) -> int | None:
        normalized = canonical_email(email)
        if normalized is None:
            return None
        try:
            contact_id = owner_ids[normalized]
        except (KeyError, TypeError):
            raise ContactDataIntegrityError(
                "archive contact ownership is invalid"
            ) from None
        if contact_id is not None and (type(contact_id) is not int or contact_id <= 0):
            raise ContactDataIntegrityError(
                "archive contact ownership is invalid"
            )
        return contact_id

    templates_by_name = {item.name.strip().lower(): item for item in (await db.execute(select(CRMAgreementTemplate))).scalars().all()}
    for row in payload.templates:
        key = row.name.strip().lower()
        if key in templates_by_name:
            skipped["templates"] += 1
            continue
        item = CRMAgreementTemplate(name=row.name, body=row.body); db.add(item); await db.flush()
        templates_by_name[key] = item; created["templates"] += 1

    if payload.tasks and payload.source_id is None:
        raise TaskCommandValidationError("archive task source is invalid")
    task_rows_with_source_keys = sorted(
        (
            (
                archive_task_source_key(payload.source_id, row.source_row_id),
                row,
            )
            for row in payload.tasks
        ),
        key=lambda item: item[0],
    )
    for source_key, row in task_rows_with_source_keys:
        contact_id = resolve(row.contact_email)
        if row.contact_email and contact_id is None: unresolved += 1
        result = await crm_task_service.create(
            db,
            CreateTaskCommand(
                title=row.title,
                description=row.description,
                priority=row.priority,
                due_at=row.due_at,
                contact_id=contact_id,
                actor=TaskActor(type="admin", id=actor_subject),
                source=TaskSource(
                    type="archive_import",
                    id=payload.source_id,
                    key=source_key,
                ),
                idempotency_scope="archive_import",
                idempotency_key=source_key,
                client_timezone="UTC",
                status=row.status,
            ),
        )
        if result.replayed:
            skipped["tasks"] += 1
        else:
            created["tasks"] += 1

    for row in payload.notes:
        contact_id = resolve(row.contact_email)
        if contact_id is None:
            if row.contact_email: unresolved += 1
            continue
        existing = (await db.execute(select(CRMNote).where(CRMNote.contact_id == contact_id, CRMNote.body == row.body))).scalar_one_or_none()
        if existing: skipped["notes"] += 1; continue
        db.add(CRMNote(contact_id=contact_id, body=row.body)); db.add(CRMActivity(contact_id=contact_id, kind="archive_note_imported", summary="Imported contact note")); created["notes"] += 1

    for row in payload.opportunities:
        item = (await db.execute(select(CRMOpportunity).where(CRMOpportunity.name == row.name))).scalar_one_or_none()
        if item: skipped["opportunities"] += 1
        else:
            item = CRMOpportunity(name=row.name, stage=row.stage, value_cents=row.value_cents); db.add(item); await db.flush(); created["opportunities"] += 1
        for email in row.contact_emails:
            contact_id = resolve(email)
            if contact_id is None:
                if email: unresolved += 1
                continue
            link = (await db.execute(select(CRMOpportunityContact).where(CRMOpportunityContact.opportunity_id == item.id, CRMOpportunityContact.contact_id == contact_id, CRMOpportunityContact.role == "client"))).scalar_one_or_none()
            if not link:
                db.add(CRMOpportunityContact(opportunity_id=item.id, contact_id=contact_id, role="client")); db.add(CRMActivity(contact_id=contact_id, kind="archive_opportunity_linked", summary=f"Imported opportunity: {item.name}"))

    for row in payload.referrals:
        contact_id = resolve(row.contact_email)
        if row.contact_email and contact_id is None: unresolved += 1
        item = (await db.execute(select(CRMReferral).where(CRMReferral.name == row.name, CRMReferral.contact_id == contact_id))).scalar_one_or_none()
        if item: skipped["referrals"] += 1; continue
        db.add(CRMReferral(name=row.name, source=row.source, status=row.status, contact_id=contact_id)); created["referrals"] += 1

    for row in payload.listings:
        item = (await db.execute(select(CRMListingRecord).where(CRMListingRecord.address == row.address))).scalar_one_or_none()
        if item: skipped["listings"] += 1; continue
        db.add(CRMListingRecord(address=row.address, latitude=row.latitude, longitude=row.longitude, status=row.status)); created["listings"] += 1

    for row in payload.agreements:
        contact_id = resolve(row.contact_email)
        if row.contact_email and contact_id is None: unresolved += 1
        template = templates_by_name.get(row.template_name.strip().lower()) if row.template_name else None
        item = (await db.execute(select(CRMAgreement).where(CRMAgreement.title == row.title, CRMAgreement.contact_id == contact_id))).scalar_one_or_none()
        if item: skipped["agreements"] += 1; continue
        item = CRMAgreement(title=row.title, contact_id=contact_id, template_id=template.id if template else None, status=row.status)
        db.add(item); await db.flush(); db.add(CRMAgreementEvent(agreement_id=item.id, event_type=row.status)); created["agreements"] += 1
        if contact_id is not None: db.add(CRMActivity(contact_id=contact_id, kind="archive_agreement_imported", summary=f"Imported agreement: {item.title}"))
    await db.flush()
    return _ARCHIVE_IMPORT_ADAPTER.validate_python(
        {"created": created, "skipped_duplicates": skipped, "unresolved_contact_references": unresolved}
    )


@router.post("/archive/import", response_model=ArchiveBundleImportResult)
async def import_archive_bundle(
    payload: ArchiveBundleImportRequest,
    db: AsyncSession = Depends(get_db),
    *,
    actor_subject: AdminSubject,
):
    try:
        contact_rows = tuple(
            ContactImportRowCommand(**row.model_dump()) for row in payload.contacts
        )
        referenced_emails = (
            *(row.contact_email for row in payload.tasks),
            *(row.contact_email for row in payload.notes),
            *(
                email
                for row in payload.opportunities
                for email in row.contact_emails
            ),
            *(row.contact_email for row in payload.referrals),
            *(row.contact_email for row in payload.agreements),
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Archive contact input is invalid",
        ) from None
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to import archive data",
        ) from None
    try:
        return await _import_archive_bundle(
            payload,
            db,
            contact_rows,
            referenced_emails,
            actor_subject=actor_subject,
        )
    except ContactNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found",
        ) from None
    except (
        ContactNotInDirectory,
        ContactDataIntegrityError,
        ContactLinkConflict,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Contact data is unavailable",
        ) from None
    except ContactSectionUnsupported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Contact section is unsupported",
        ) from None
    except TaskCommandValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Archive task input is invalid",
        ) from None
    except TaskIdempotencyConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "task_idempotency_mismatch",
                "message": "Archive task identity was already used with different task data or authority",
            },
        ) from None
    except TaskSourceConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "task_source_conflict",
                "message": "Archive task source identity is already linked",
            },
        ) from None
    except TaskCreationStateError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "task_creation_state_invalid",
                "message": "Archive task creation request is not replayable",
            },
        ) from None
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to import archive data",
        ) from None


@router.post("/tags")
async def create_tag(payload:TagCreate,db:AsyncSession=Depends(get_db)):
    existing=(await db.execute(select(CRMTag).where(CRMTag.name==payload.name))).scalar_one_or_none()
    if existing:return {"id":existing.id,"name":existing.name}
    tag=CRMTag(name=payload.name);db.add(tag);await db.flush();return {"id":tag.id,"name":tag.name}

@router.get("/saved-searches", response_model=list[SavedSearchOut])
async def saved_searches(db: AsyncSession = Depends(get_db)):
    try:
        values = await contact_service.list_saved_searches(db)
        return _SAVED_SEARCHES_ADAPTER.validate_python(
            [
                {
                    "id": value.id,
                    "name": value.name,
                    "criteria": canonical_saved_search_criteria(value.criteria),
                    "contact_id": value.contact_id,
                    "contact_name": value.contact_name,
                    "updated_at": value.updated_at,
                }
                for value in values
            ]
        )
    except ContactNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found",
        ) from None
    except (
        ContactNotInDirectory,
        ContactDataIntegrityError,
        ContactLinkConflict,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Contact data is unavailable",
        ) from None
    except ContactSectionUnsupported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Contact section is unsupported",
        ) from None
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load saved searches",
        ) from None

@router.delete("/saved-searches/{search_id}", response_model=ContactDeletedOut)
async def delete_saved_search(
    search_id: SavedSearchId,
    db: AsyncSession = Depends(get_db),
    *,
    actor_subject: AdminSubject,
):
    try:
        result = await contact_service.delete_saved_search(
            db,
            search_id,
            actor_subject=actor_subject,
        )
        if not isinstance(result, (ContactMutationResult, WorkspaceMutationResult)):
            raise ContactDataIntegrityError(
                "saved search result is invalid"
            )
        if result.changed is not True or result.record_id != search_id:
            raise ContactDataIntegrityError(
                "saved search result is invalid"
            )
        return _DELETED_SEARCH_ADAPTER.validate_python(
            {"deleted": True, "id": result.record_id}
        )
    except ContactNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved search not found",
        ) from None
    except (
        ContactNotInDirectory,
        ContactDataIntegrityError,
        ContactLinkConflict,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Contact data is unavailable",
        ) from None
    except ContactSectionUnsupported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Contact section is unsupported",
        ) from None
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete saved search",
        ) from None


TaskVisibility = Literal["active", "archived", "all"]


def _require_aware_task_filter(
    value: datetime | None,
    *,
    name: str,
) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise HTTPException(422, f"{name} must include a UTC offset")
    return value


def _task_state_conflict(exc: TaskStateConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": exc.code,
            "current_version": exc.current_version,
            "current_task": exc.current_task,
        },
    )


def _task_link_response(result) -> TaskLinkOut:
    return TaskLinkOut(
        id=result.link.id,
        task_id=result.link.task_id,
        entity_type=result.link.entity_type,
        entity_id=result.link.entity_id,
        display_name=result.display_name,
        task_version=result.task_version,
    )


@router.get("/tasks", response_model=list[TaskOut])
async def tasks(
    visibility: TaskVisibility = "active",
    status: TaskWorkflowStatus | None = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    db: AsyncSession = Depends(get_db),
):
    due_before = _require_aware_task_filter(due_before, name="due_before")
    due_after = _require_aware_task_filter(due_after, name="due_after")
    query = select(CRMTask)
    if visibility == "active":
        query = query.where(
            workflow_status_task_clause(status)
            if status is not None
            else active_task_clause()
        )
    elif visibility == "archived":
        query = query.where(archived_task_clause())
        if status is not None:
            query = query.where(CRMTask.status == status)
    else:
        if status is not None:
            query = query.where(CRMTask.status == status)
    if due_before is not None:
        query = query.where(CRMTask.due_at <= due_before)
    if due_after is not None:
        query = query.where(CRMTask.due_at >= due_after)
    query = query.order_by(CRMTask.due_at.asc().nulls_last())
    return (await db.execute(query)).scalars().all()


@router.post("/tasks", response_model=TaskOut)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    *,
    actor_subject: AdminSubject,
    idempotency_key: Annotated[UUID, Header(alias="X-Idempotency-Key")],
    client_timezone: Annotated[str, Header(alias="X-Client-Timezone")] = "UTC",
):
    try:
        result = await crm_task_service.create(
            db,
            CreateTaskCommand(
                **payload.model_dump(),
                actor=TaskActor(type="admin", id=actor_subject),
                source=TaskSource(
                    type="command_ui",
                    id=str(idempotency_key),
                    key="primary",
                ),
                idempotency_scope="command_ui",
                idempotency_key=str(idempotency_key),
                client_timezone=client_timezone,
            ),
        )
        return result.task
    except TaskContactNotFound:
        raise HTTPException(404, "Task contact not found") from None
    except TaskCommandValidationError:
        raise HTTPException(422, "Task request is invalid") from None
    except TaskIdempotencyConflict:
        raise HTTPException(
            409,
            {
                "code": "task_idempotency_mismatch",
                "message": "Idempotency key was already used with a different task request",
            },
        ) from None
    except TaskCreationStateError:
        raise HTTPException(
            409,
            {
                "code": "task_creation_state_invalid",
                "message": "Task creation request is not in a replayable state",
            },
        ) from None
    except TaskSourceConflict:
        raise HTTPException(
            409,
            {
                "code": "task_source_conflict",
                "message": "Task source identity is already linked",
            },
        ) from None


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: TaskId,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    *,
    actor_subject: AdminSubject,
):
    try:
        result = await crm_task_service.update(
            db,
            task_id=task_id,
            expected_version=payload.expected_version,
            changes=payload.model_dump(
                exclude_unset=True,
                exclude={"expected_version"},
            ),
            actor=TaskActor(type="admin", id=actor_subject),
        )
        return result.task
    except TaskNotFound:
        raise HTTPException(404, "Task not found") from None
    except TaskContactNotFound:
        raise HTTPException(404, "Task contact not found") from None
    except TaskCommandValidationError:
        raise HTTPException(422, "Task request is invalid") from None
    except TaskStateConflict as exc:
        raise _task_state_conflict(exc) from None


@router.post("/tasks/{task_id}/links", response_model=TaskLinkOut)
async def add_task_link(
    task_id: TaskId,
    payload: TaskLinkCreate,
    db: AsyncSession = Depends(get_db),
    *,
    actor_subject: AdminSubject,
):
    try:
        result = await crm_task_service.add_link(
            db,
            task_id=task_id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            expected_version=payload.expected_version,
            actor=TaskActor(type="admin", id=actor_subject),
        )
        return _task_link_response(result)
    except TaskNotFound:
        raise HTTPException(404, "Task not found") from None
    except TaskLinkedRecordNotFound:
        raise HTTPException(404, "Linked internal record not found") from None
    except TaskCommandValidationError:
        raise HTTPException(422, "Unsupported task-link entity type") from None
    except TaskStateConflict as exc:
        raise _task_state_conflict(exc) from None


@router.get("/tasks/{task_id}/links", response_model=list[TaskLinkOut])
async def task_links(task_id: TaskId, db: AsyncSession = Depends(get_db)):
    task = await db.get(CRMTask, task_id, with_for_update=True)
    if not task:
        raise HTTPException(404, "Task not found")
    rows = (await db.execute(select(CRMTaskLink).where(CRMTaskLink.task_id == task_id).order_by(CRMTaskLink.id.desc()))).scalars().all()
    links = []
    for row in rows:
        entity_model = task_link_model(row.entity_type)
        record = await db.get(entity_model, row.entity_id) if entity_model else None
        links.append({"id": row.id, "task_id": row.task_id, "entity_type": row.entity_type, "entity_id": row.entity_id, "display_name": task_link_display_name(row.entity_type, record) if record else "Removed internal record", "task_version": task.version})
    return links


@router.post("/tasks/bulk-archive", response_model=TaskBulkArchiveResponse)
async def bulk_archive_tasks(
    payload: TaskBulkArchiveRequest,
    db: AsyncSession = Depends(get_db),
    *,
    actor_subject: AdminSubject,
):
    if not settings.CRM_TASK_ARCHIVE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task archive and restore are disabled",
        )

    results: list[TaskBulkArchiveResult] = []
    for item in sorted(payload.items, key=lambda candidate: candidate.task_id):
        try:
            result = await crm_task_service.archive(
                db,
                task_id=item.task_id,
                request_id=item.request_id,
                expected_version=item.expected_version,
                reason=payload.reason,
                actor=TaskActor(type="admin", id=actor_subject),
                source=TaskSource(
                    type="command_ui",
                    id=str(item.request_id),
                    key="bulk_archive",
                ),
            )
            results.append(
                TaskBulkArchiveResult(
                    task_id=item.task_id,
                    status="archived",
                    task=TaskOut.model_validate(result.task),
                )
            )
        except TaskStateConflict as exc:
            results.append(
                TaskBulkArchiveResult(
                    task_id=item.task_id,
                    status="conflict",
                    code=exc.code,
                    task=TaskOut.model_validate(exc.current_task),
                )
            )
        except TaskNotFound:
            results.append(
                TaskBulkArchiveResult(
                    task_id=item.task_id,
                    status="not_found",
                    code="task_not_found",
                )
            )
        except TaskCommandValidationError:
            results.append(
                TaskBulkArchiveResult(
                    task_id=item.task_id,
                    status="invalid",
                    code="task_request_invalid",
                )
            )
    return TaskBulkArchiveResponse(results=results)


async def _change_task_archive_state(
    *,
    action: Literal["archive", "restore"],
    task_id: int,
    payload: TaskLifecycleRequest,
    db: AsyncSession,
    actor_subject: str,
):
    if not settings.CRM_TASK_ARCHIVE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task archive and restore are disabled",
        )
    method = (
        crm_task_service.archive
        if action == "archive"
        else crm_task_service.restore
    )
    try:
        result = await method(
            db,
            task_id=task_id,
            request_id=payload.request_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
            actor=TaskActor(type="admin", id=actor_subject),
            source=TaskSource(
                type="command_ui",
                id=str(payload.request_id),
                key=action,
            ),
        )
        return result.task
    except TaskNotFound:
        raise HTTPException(404, "Task not found") from None
    except TaskCommandValidationError:
        raise HTTPException(422, "Task lifecycle request is invalid") from None
    except TaskStateConflict as exc:
        raise _task_state_conflict(exc) from None


@router.post("/tasks/{task_id}/archive", response_model=TaskOut)
async def archive_task(
    task_id: TaskId,
    payload: TaskLifecycleRequest,
    db: AsyncSession = Depends(get_db),
    *,
    actor_subject: AdminSubject,
):
    return await _change_task_archive_state(
        action="archive",
        task_id=task_id,
        payload=payload,
        db=db,
        actor_subject=actor_subject,
    )


@router.post("/tasks/{task_id}/restore", response_model=TaskOut)
async def restore_task(
    task_id: TaskId,
    payload: TaskLifecycleRequest,
    db: AsyncSession = Depends(get_db),
    *,
    actor_subject: AdminSubject,
):
    return await _change_task_archive_state(
        action="restore",
        task_id=task_id,
        payload=payload,
        db=db,
        actor_subject=actor_subject,
    )


@router.patch("/agreements/{agreement_id}/status")
async def update_agreement_status(agreement_id: int, payload: AgreementStatusUpdate, db: AsyncSession = Depends(get_db)):
    if payload.status not in {s.value for s in AgreementStatus}: raise HTTPException(422, "Invalid agreement status")
    item = await db.get(CRMAgreement, agreement_id)
    if not item: raise HTTPException(404, "Agreement not found")
    try:
        ensure_agreement_transition(item.status, payload.status)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    item.status = payload.status; await db.flush()
    db.add(CRMAgreementEvent(agreement_id=item.id, event_type=payload.status))
    if item.contact_id:
        db.add(CRMActivity(contact_id=item.contact_id, kind="agreement_status_changed", summary=f"Agreement {item.title} moved to {item.status}"))
    await db.flush()
    return {"id": item.id, "status": item.status}

@router.get("/agreements", response_model=list[AgreementOut])
async def agreements(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMAgreement).order_by(CRMAgreement.created_at.desc()))).scalars().all()

@router.post("/agreements", response_model=AgreementOut)
async def create_agreement(payload: AgreementCreate, db: AsyncSession = Depends(get_db)):
    if payload.contact_id is not None and not await db.get(CRMContact, payload.contact_id): raise HTTPException(404, "Contact not found")
    if payload.template_id is not None and not await db.get(CRMAgreementTemplate, payload.template_id): raise HTTPException(404, "Agreement template not found")
    item = CRMAgreement(**payload.model_dump()); db.add(item); await db.flush()
    db.add(CRMAgreementEvent(agreement_id=item.id, event_type="draft"))
    if item.contact_id:
        db.add(CRMActivity(contact_id=item.contact_id, kind="agreement_created", summary=f"Agreement created: {item.title}"))
    await db.flush(); return item

@router.get("/agreements/{agreement_id}/workspace")
async def agreement_workspace(agreement_id: int, db: AsyncSession = Depends(get_db)):
    agreement = await db.get(CRMAgreement, agreement_id)
    if not agreement: raise HTTPException(404, "Agreement not found")
    recipients = (await db.execute(select(CRMAgreementRecipient).where(CRMAgreementRecipient.agreement_id == agreement_id))).scalars().all()
    events = (await db.execute(select(CRMAgreementEvent).where(CRMAgreementEvent.agreement_id == agreement_id).order_by(CRMAgreementEvent.created_at.desc()))).scalars().all()
    files = (await db.execute(select(CRMFileAsset).where(CRMFileAsset.agreement_id == agreement_id).order_by(CRMFileAsset.created_at.desc()))).scalars().all()
    return {"agreement": agreement, "recipients": recipients, "events": events, "files": files}

@router.get("/agreement-templates", response_model=list[TemplateOut])
async def templates(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMAgreementTemplate))).scalars().all()
@router.post("/agreement-templates", response_model=TemplateOut)
async def create_template(payload: TemplateCreate, db: AsyncSession = Depends(get_db)):
    item=CRMAgreementTemplate(**payload.model_dump()); db.add(item); await db.flush(); return item
@router.patch("/agreement-templates/{template_id}", response_model=TemplateOut)
async def update_template(template_id: int, payload: TemplateUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMAgreementTemplate, template_id)
    if not item: raise HTTPException(404, "Agreement template not found")
    item.body = payload.body; await db.flush(); return item
@router.get("/files", response_model=list[FileAssetOut])
async def files(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMFileAsset))).scalars().all()
@router.post("/files", response_model=FileAssetOut)
async def create_file(payload: FileAssetCreate, db: AsyncSession = Depends(get_db)):
    item=CRMFileAsset(**payload.model_dump()); db.add(item); await db.flush(); return item

@router.post("/files/upload", response_model=FileAssetOut)
async def upload_file(file: UploadFile, agreement_id: int | None = None, db: AsyncSession = Depends(get_db)):
    if agreement_id is not None and not await db.get(CRMAgreement, agreement_id):
        raise HTTPException(404, "Agreement not found")
    filename, storage_key, content_type = await upload_command_file(file)
    item = CRMFileAsset(filename=filename, storage_key=storage_key, content_type=content_type, agreement_id=agreement_id)
    db.add(item); await db.flush(); return item

@router.get("/listings", response_model=list[ListingOut])
async def listings(query: str | None = None, status: str | None = None, db: AsyncSession = Depends(get_db)):
    statement = select(CRMListingRecord).order_by(CRMListingRecord.created_at.desc())
    if query and (term := query.strip()):
        statement = statement.where(CRMListingRecord.address.ilike(f"%{term}%"))
    if status:
        statement = statement.where(CRMListingRecord.status == status)
    return (await db.execute(statement)).scalars().all()

@router.post("/listings", response_model=ListingOut)
async def create_listing(payload: ListingCreate, db: AsyncSession = Depends(get_db)):
    item = CRMListingRecord(**payload.model_dump()); db.add(item); await db.flush(); return item

@router.patch("/listings/{listing_id}", response_model=ListingOut)
async def update_listing_status(listing_id: int, payload: ListingStatusUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMListingRecord, listing_id)
    if not item: raise HTTPException(404, "Listing not found")
    item.status = payload.status; await db.flush(); return item

@router.get("/referrals", response_model=list[ReferralOut])
async def referrals(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMReferral).order_by(CRMReferral.created_at.desc()))).scalars().all()
@router.post("/referrals", response_model=ReferralOut)
async def create_referral(payload: ReferralCreate, db: AsyncSession = Depends(get_db)):
    if payload.contact_id and not await db.get(CRMContact, payload.contact_id): raise HTTPException(404, "Contact not found")
    item = CRMReferral(**payload.model_dump()); db.add(item); await db.flush()
    if item.contact_id:
        db.add(CRMActivity(contact_id=item.contact_id, kind="referral_created", summary=f"Referral created: {item.name}"))
        await db.flush()
    return item
@router.patch("/referrals/{referral_id}", response_model=ReferralOut)
async def update_referral(referral_id: int, payload: ReferralUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMReferral, referral_id)
    if not item: raise HTTPException(404, "Referral not found")
    changed = item.status != payload.status
    item.status = payload.status
    if changed and item.contact_id:
        db.add(CRMActivity(contact_id=item.contact_id, kind="referral_status_changed", summary=f"Referral status changed to {item.status}"))
    await db.flush(); return item


@router.post("/listings/{listing_id}/geocode", response_model=ListingOut)
async def geocode_listing(listing_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMListingRecord, listing_id)
    if not item: raise HTTPException(404, "Listing not found")
    try:
        item.latitude, item.longitude = await geocode_listing_address(item.address)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(422, "Unable to geocode listing address") from exc
    await db.flush()
    return item


@router.get("/smart-plans", response_model=list[NamedRecordOut])
async def smart_plans(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMSmartPlan).order_by(CRMSmartPlan.created_at.desc()))).scalars().all()


@router.post("/smart-plans", response_model=NamedRecordOut)
async def create_smart_plan(payload: NamedRecordCreate, db: AsyncSession = Depends(get_db)):
    item = CRMSmartPlan(**payload.model_dump()); db.add(item); await db.flush(); return item

@router.patch("/smart-plans/{plan_id}", response_model=NamedRecordOut)
async def update_smart_plan_status(plan_id: int, payload: SmartPlanStatusUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMSmartPlan, plan_id)
    if not item: raise HTTPException(404, "Smart Plan not found")
    item.status = payload.status; await db.flush(); return item

@router.get("/smart-plans/{plan_id}/workspace")
async def smart_plan_workspace(plan_id:int, db:AsyncSession=Depends(get_db)):
    plan=await db.get(CRMSmartPlan,plan_id)
    if not plan: raise HTTPException(404,"Smart Plan not found")
    steps=(await db.execute(select(CRMSmartPlanStep).where(CRMSmartPlanStep.smart_plan_id==plan_id).order_by(CRMSmartPlanStep.position))).scalars().all()
    enrollment_rows=(await db.execute(
        select(CRMSmartPlanEnrollment, CRMContact)
        .join(CRMContact, CRMContact.id == CRMSmartPlanEnrollment.contact_id)
        .where(CRMSmartPlanEnrollment.smart_plan_id==plan_id)
        .order_by(CRMContact.last_name, CRMContact.first_name)
    )).all()
    return {"plan":plan,"steps":[{"id":x.id,"position":x.position,"action_type":x.action_type,"payload":x.payload_json} for x in steps],"enrollments":[{"id":enrollment.id,"contact_id":enrollment.contact_id,"contact_name":f"{contact.first_name} {contact.last_name}".strip(),"status":enrollment.status} for enrollment, contact in enrollment_rows]}

@router.post("/smart-plans/{plan_id}/steps")
async def create_plan_step(plan_id: int, payload: SmartPlanStepCreate, db: AsyncSession = Depends(get_db)):
    if not await db.get(CRMSmartPlan, plan_id): raise HTTPException(404, "Smart Plan not found")
    item=CRMSmartPlanStep(smart_plan_id=plan_id, position=payload.position, action_type=payload.action_type, payload_json=payload.payload.model_dump_json() if hasattr(payload.payload,'model_dump_json') else __import__('json').dumps(payload.payload)); db.add(item); await db.flush(); return {"id":item.id,"position":item.position,"action_type":item.action_type}

@router.patch("/smart-plans/{plan_id}/steps/{step_id}")
async def update_plan_step(plan_id: int, step_id: int, payload: SmartPlanStepCreate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMSmartPlanStep, step_id)
    if not item or item.smart_plan_id != plan_id: raise HTTPException(404, "Smart Plan step not found")
    item.position = payload.position; item.action_type = payload.action_type; item.payload_json = __import__('json').dumps(payload.payload)
    await db.flush(); return {"id": item.id, "position": item.position, "action_type": item.action_type}

@router.post("/smart-plans/{plan_id}/enrollments")
async def enroll_contact(plan_id: int, payload: SmartPlanEnrollmentCreate, db: AsyncSession = Depends(get_db)):
    if not await db.get(CRMSmartPlan, plan_id) or not await db.get(CRMContact, payload.contact_id): raise HTTPException(404, "Smart Plan or contact not found")
    existing = (await db.execute(select(CRMSmartPlanEnrollment).where(CRMSmartPlanEnrollment.smart_plan_id == plan_id, CRMSmartPlanEnrollment.contact_id == payload.contact_id))).scalar_one_or_none()
    if existing:
        return {"id": existing.id, "contact_id": existing.contact_id, "status": existing.status}
    plan = await db.get(CRMSmartPlan, plan_id)
    item=CRMSmartPlanEnrollment(smart_plan_id=plan_id,contact_id=payload.contact_id); db.add(item); await db.flush()
    db.add(CRMActivity(contact_id=item.contact_id, kind="smart_plan_enrolled", summary=f"Enrolled in Smart Plan: {plan.name if plan else plan_id}"))
    await db.flush(); return {"id":item.id,"status":item.status}

@router.patch("/smart-plans/{plan_id}/enrollments/{enrollment_id}")
async def update_plan_enrollment(plan_id: int, enrollment_id: int, payload: SmartPlanEnrollmentUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMSmartPlanEnrollment, enrollment_id)
    if not item or item.smart_plan_id != plan_id: raise HTTPException(404, "Smart Plan enrollment not found")
    changed = item.status != payload.status
    item.status = payload.status
    if changed:
        plan = await db.get(CRMSmartPlan, plan_id)
        db.add(CRMActivity(contact_id=item.contact_id, kind="smart_plan_enrollment_changed", summary=f"Smart Plan {plan.name if plan else plan_id} enrollment {item.status}"))
    await db.flush(); return {"id": item.id, "status": item.status}


@router.get("/opportunities", response_model=list[OpportunityOut])
async def opportunities(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMOpportunity).order_by(CRMOpportunity.created_at.desc()))).scalars().all()


@router.post("/opportunities", response_model=OpportunityOut)
async def create_opportunity(payload: OpportunityCreate, db: AsyncSession = Depends(get_db)):
    item = CRMOpportunity(**payload.model_dump()); db.add(item); await db.flush(); return item

@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityOut)
async def update_opportunity(opportunity_id: int, payload: OpportunityUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMOpportunity, opportunity_id)
    if not item: raise HTTPException(404, "Opportunity not found")
    if item.stage != payload.stage:
        item.stage = payload.stage
        db.add(CRMActivity(kind="opportunity_stage_changed", summary=f"Opportunity {item.name} moved to {payload.stage}", metadata_json=f'{{"opportunity_id":{item.id}}}'))
        contact_ids = (await db.execute(select(CRMOpportunityContact.contact_id).where(CRMOpportunityContact.opportunity_id == item.id))).scalars().all()
        for contact_id in contact_ids:
            db.add(CRMActivity(contact_id=contact_id, kind="opportunity_stage_changed", summary=f"Opportunity {item.name} moved to {payload.stage}", metadata_json=f'{{"opportunity_id":{item.id}}}'))
    await db.flush(); return item

@router.get("/opportunities/{opportunity_id}/workspace")
async def opportunity_workspace(opportunity_id:int,db:AsyncSession=Depends(get_db)):
    item=await db.get(CRMOpportunity,opportunity_id)
    if not item: raise HTTPException(404,"Opportunity not found")
    contacts=(await db.execute(select(CRMOpportunityContact).where(CRMOpportunityContact.opportunity_id==opportunity_id))).scalars().all()
    vendors=(await db.execute(select(CRMOpportunityVendor).where(CRMOpportunityVendor.opportunity_id==opportunity_id))).scalars().all()
    offers=(await db.execute(select(CRMOpportunityOffer).where(CRMOpportunityOffer.opportunity_id==opportunity_id))).scalars().all()
    return {"opportunity":item,"contacts":[{"id":x.id,"contact_id":x.contact_id,"role":x.role} for x in contacts],"vendors":[{"id":x.id,"name":x.name,"role":x.role} for x in vendors],"offers":[{"id":x.id,"amount_cents":x.amount_cents,"status":x.status} for x in offers]}

@router.post("/opportunities/{opportunity_id}/contacts", response_model=RelationshipOut)
async def add_opportunity_contact(opportunity_id:int,payload:RelationshipCreate,db:AsyncSession=Depends(get_db)):
    if not await db.get(CRMOpportunity, opportunity_id) or not payload.contact_id or not await db.get(CRMContact,payload.contact_id): raise HTTPException(404,"Opportunity or contact not found")
    candidates = (await db.execute(select(CRMOpportunityContact).where(CRMOpportunityContact.opportunity_id == opportunity_id, CRMOpportunityContact.contact_id == payload.contact_id))).scalars().all()
    existing = next((row for row in candidates if is_same_opportunity_contact(row.contact_id, row.role, payload.contact_id, payload.role)), None)
    if existing:
        return {"id":existing.id,"contact_id":existing.contact_id,"role":existing.role}
    item=CRMOpportunityContact(opportunity_id=opportunity_id,contact_id=payload.contact_id,role=payload.role);db.add(item);await db.flush()
    opportunity = await db.get(CRMOpportunity, opportunity_id)
    db.add(CRMActivity(contact_id=item.contact_id, kind="opportunity_linked", summary=f"Linked to opportunity: {opportunity.name if opportunity else opportunity_id}"))
    await db.flush();return {"id":item.id,"contact_id":item.contact_id,"role":item.role}
@router.post("/opportunities/{opportunity_id}/vendors", response_model=RelationshipOut)
async def add_opportunity_vendor(opportunity_id:int,payload:RelationshipCreate,db:AsyncSession=Depends(get_db)):
    if not await db.get(CRMOpportunity,opportunity_id) or not payload.name: raise HTTPException(404,"Opportunity or vendor name not found")
    item=CRMOpportunityVendor(opportunity_id=opportunity_id,name=payload.name,role=payload.role);db.add(item);await db.flush();return {"id":item.id,"name":item.name,"role":item.role}
@router.post("/opportunities/{opportunity_id}/offers", response_model=RelationshipOut)
async def add_opportunity_offer(opportunity_id:int,payload:RelationshipCreate,db:AsyncSession=Depends(get_db)):
    if not await db.get(CRMOpportunity,opportunity_id): raise HTTPException(404,"Opportunity not found")
    item=CRMOpportunityOffer(opportunity_id=opportunity_id,amount_cents=payload.amount_cents,status=payload.status);db.add(item);await db.flush();return {"id":item.id,"amount_cents":item.amount_cents,"status":item.status}

@router.post("/agreements/{agreement_id}/recipients", response_model=RelationshipOut)
async def add_agreement_recipient(agreement_id:int,payload:RelationshipCreate,db:AsyncSession=Depends(get_db)):
    if not await db.get(CRMAgreement,agreement_id) or not payload.name or not payload.email: raise HTTPException(404,"Agreement or recipient details not found")
    item=CRMAgreementRecipient(agreement_id=agreement_id,name=payload.name,email=payload.email,role=payload.role);db.add(item);db.add(CRMAgreementEvent(agreement_id=agreement_id,event_type="recipient_added"));await db.flush();return {"id":item.id,"name":item.name,"email":item.email,"role":item.role}
