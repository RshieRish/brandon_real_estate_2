from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import require_admin
from models.command import AgreementStatus, CRMActivity, CRMAgreement, CRMAgreementTemplate, CRMContact, CRMFileAsset, CRMListingRecord, CRMNote, CRMOpportunity, CRMSavedSearch, CRMSmartPlan, CRMSmartPlanEnrollment, CRMTask
from schemas.command import AgreementCreate, AgreementOut, AgreementStatusUpdate, ContactCreate, ContactOut, FileAssetCreate, FileAssetOut, ListingCreate, ListingOut, NamedRecordCreate, NamedRecordOut, OpportunityCreate, OpportunityOut, OverviewOut, TaskCreate, TaskOut, TaskUpdate, TemplateCreate, TemplateOut
from services.command_file_storage import upload_command_file

router = APIRouter(dependencies=[Depends(require_admin)])


async def _count(db: AsyncSession, model, *where) -> int:
    query = select(func.count()).select_from(model)
    if where: query = query.where(*where)
    return int((await db.execute(query)).scalar_one())


@router.get("/overview", response_model=OverviewOut)
async def overview(db: AsyncSession = Depends(get_db)):
    return OverviewOut(
        contacts=await _count(db, CRMContact), open_tasks=await _count(db, CRMTask, CRMTask.status != "completed"),
        opportunities=await _count(db, CRMOpportunity), active_smart_plans=await _count(db, CRMSmartPlan, CRMSmartPlan.status == "active"),
    )

@router.get("/ai/briefing")
async def ai_briefing(db: AsyncSession = Depends(get_db)):
    """Deterministic, auditable pre-AI briefing; no contact data leaves the API."""
    open_tasks = await _count(db, CRMTask, CRMTask.status != "completed")
    contacts = await _count(db, CRMContact)
    opportunities = await _count(db, CRMOpportunity)
    return {"summary": f"{open_tasks} open tasks across {contacts} contacts and {opportunities} opportunities.", "source": "internal-crm", "requires_review": True}


@router.get("/contacts", response_model=list[ContactOut])
async def contacts(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CRMContact).order_by(CRMContact.created_at.desc()).offset(offset).limit(min(limit, 100)))
    return result.scalars().all()


@router.post("/contacts", response_model=ContactOut)
async def create_contact(payload: ContactCreate, db: AsyncSession = Depends(get_db)):
    item = CRMContact(**payload.model_dump())
    db.add(item); await db.flush()
    db.add(CRMActivity(contact_id=item.id, kind="contact_created", summary="Contact created in Command workspace"))
    await db.flush(); return item


@router.get("/contacts/{contact_id}", response_model=ContactOut)
async def contact_detail(contact_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMContact, contact_id)
    if not item: raise HTTPException(404, "Contact not found")
    return item

@router.get("/contacts/{contact_id}/workspace")
async def contact_workspace(contact_id: int, db: AsyncSession = Depends(get_db)):
    contact = await db.get(CRMContact, contact_id)
    if not contact: raise HTTPException(404, "Contact not found")
    async def rows(model, field):
        return (await db.execute(select(model).where(field == contact_id).order_by(model.created_at.desc()))).scalars().all()
    tasks = await rows(CRMTask, CRMTask.contact_id)
    notes = await rows(CRMNote, CRMNote.contact_id)
    activity = await rows(CRMActivity, CRMActivity.contact_id)
    enrollments = (await db.execute(select(CRMSmartPlanEnrollment).where(CRMSmartPlanEnrollment.contact_id == contact_id))).scalars().all()
    searches=(await db.execute(select(CRMSavedSearch).where(CRMSavedSearch.contact_id == contact_id))).scalars().all()
    return {"contact": contact, "timeline": [{"id":a.id,"kind":a.kind,"summary":a.summary,"created_at":a.created_at} for a in activity], "tasks": tasks, "notes": notes, "smart_plans": [{"id":e.id,"plan_id":e.smart_plan_id,"status":e.status} for e in enrollments], "opportunities": [], "saved_searches": [{"id":s.id,"name":s.name,"criteria":s.criteria_json} for s in searches]}


@router.get("/tasks", response_model=list[TaskOut])
async def tasks(status: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(CRMTask).order_by(CRMTask.due_at.asc().nulls_last())
    if status: query = query.where(CRMTask.status == status)
    return (await db.execute(query)).scalars().all()


@router.post("/tasks", response_model=TaskOut)
async def create_task(payload: TaskCreate, db: AsyncSession = Depends(get_db)):
    item = CRMTask(**payload.model_dump()); db.add(item); await db.flush()
    db.add(CRMActivity(contact_id=item.contact_id, kind="task_created", summary=item.title)); await db.flush()
    return item


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: int, payload: TaskUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMTask, task_id)
    if not item: raise HTTPException(404, "Task not found")
    for field, value in payload.model_dump(exclude_none=True).items(): setattr(item, field, value)
    await db.flush(); return item


@router.patch("/agreements/{agreement_id}/status")
async def update_agreement_status(agreement_id: int, payload: AgreementStatusUpdate, db: AsyncSession = Depends(get_db)):
    if payload.status not in {s.value for s in AgreementStatus}: raise HTTPException(422, "Invalid agreement status")
    item = await db.get(CRMAgreement, agreement_id)
    if not item: raise HTTPException(404, "Agreement not found")
    item.status = payload.status; await db.flush()
    return {"id": item.id, "status": item.status}

@router.get("/agreements", response_model=list[AgreementOut])
async def agreements(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMAgreement).order_by(CRMAgreement.created_at.desc()))).scalars().all()

@router.post("/agreements", response_model=AgreementOut)
async def create_agreement(payload: AgreementCreate, db: AsyncSession = Depends(get_db)):
    item = CRMAgreement(**payload.model_dump()); db.add(item); await db.flush(); return item

@router.get("/agreement-templates", response_model=list[TemplateOut])
async def templates(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMAgreementTemplate))).scalars().all()
@router.post("/agreement-templates", response_model=TemplateOut)
async def create_template(payload: TemplateCreate, db: AsyncSession = Depends(get_db)):
    item=CRMAgreementTemplate(**payload.model_dump()); db.add(item); await db.flush(); return item
@router.get("/files", response_model=list[FileAssetOut])
async def files(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMFileAsset))).scalars().all()
@router.post("/files", response_model=FileAssetOut)
async def create_file(payload: FileAssetCreate, db: AsyncSession = Depends(get_db)):
    item=CRMFileAsset(**payload.model_dump()); db.add(item); await db.flush(); return item

@router.post("/files/upload", response_model=FileAssetOut)
async def upload_file(file: UploadFile, db: AsyncSession = Depends(get_db)):
    filename, storage_key, content_type = await upload_command_file(file)
    item = CRMFileAsset(filename=filename, storage_key=storage_key, content_type=content_type)
    db.add(item); await db.flush(); return item

@router.get("/listings", response_model=list[ListingOut])
async def listings(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMListingRecord).order_by(CRMListingRecord.created_at.desc()))).scalars().all()

@router.post("/listings", response_model=ListingOut)
async def create_listing(payload: ListingCreate, db: AsyncSession = Depends(get_db)):
    item = CRMListingRecord(**payload.model_dump()); db.add(item); await db.flush(); return item


@router.get("/smart-plans", response_model=list[NamedRecordOut])
async def smart_plans(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMSmartPlan).order_by(CRMSmartPlan.created_at.desc()))).scalars().all()


@router.post("/smart-plans", response_model=NamedRecordOut)
async def create_smart_plan(payload: NamedRecordCreate, db: AsyncSession = Depends(get_db)):
    item = CRMSmartPlan(**payload.model_dump()); db.add(item); await db.flush(); return item


@router.get("/opportunities", response_model=list[OpportunityOut])
async def opportunities(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMOpportunity).order_by(CRMOpportunity.created_at.desc()))).scalars().all()


@router.post("/opportunities", response_model=OpportunityOut)
async def create_opportunity(payload: OpportunityCreate, db: AsyncSession = Depends(get_db)):
    item = CRMOpportunity(**payload.model_dump()); db.add(item); await db.flush(); return item
