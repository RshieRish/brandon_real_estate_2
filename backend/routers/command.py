from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import require_admin
from models.command import AgreementStatus, CRMActivity, CRMAgreement, CRMContact, CRMOpportunity, CRMSmartPlan, CRMTask
from schemas.command import AgreementStatusUpdate, ContactCreate, ContactOut, OverviewOut, TaskCreate, TaskOut, TaskUpdate

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
