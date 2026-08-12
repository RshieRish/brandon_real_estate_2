import asyncio
from datetime import datetime
import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import require_admin
from models.command import AgreementStatus, CRMActivity, CRMAgreement, CRMAgreementEvent, CRMAgreementRecipient, CRMAgreementTemplate, CRMContact, CRMContactTag, CRMFileAsset, CRMListingRecord, CRMNote, CRMOpportunity, CRMOpportunityContact, CRMOpportunityOffer, CRMOpportunityVendor, CRMSavedSearch, CRMSmartPlan, CRMSmartPlanEnrollment, CRMSmartPlanStep, CRMTag, CRMTask, CRMTaskLink
from models.lead import Lead
from models.analytics_event import AnalyticsEvent
from models.content_block import ContentBlock
from models.funnel import Funnel
from config import settings
from services.gemini import generate_text_flash_lite
from schemas.command import AgreementCreate, AgreementOut, AgreementStatusUpdate, ContactCreate, ContactImportRequest, ContactOut, ContactStageUpdate, ContactWorkspaceOpportunityOut, FileAssetCreate, FileAssetOut, ListingCreate, ListingOut, NamedRecordCreate, NamedRecordOut, NoteCreate, OpportunityCreate, OpportunityOut, OpportunityUpdate, OverviewOut, RelationshipCreate, RelationshipOut, SavedSearchCreate, SmartPlanEnrollmentCreate, SmartPlanEnrollmentUpdate, SmartPlanStepCreate, TagCreate, TaskCreate, TaskLinkCreate, TaskOut, TaskUpdate, TemplateCreate, TemplateOut, TemplateUpdate
from services.command_file_storage import upload_command_file
from services.command_geocoding import geocode_listing_address
from services.command_lifecycle import ensure_agreement_transition

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
    return {"contacts":await _count(db,CRMContact),"leads":await _count(db,Lead),"open_tasks":await _count(db,CRMTask,CRMTask.status!="completed"),"opportunities":await _count(db,CRMOpportunity),"agreements":await _count(db,CRMAgreement),"events":await _count(db,AnalyticsEvent)}

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

@router.post("/contacts/sync-leads")
async def sync_legacy_leads(db: AsyncSession = Depends(get_db)):
    """Idempotently project existing internal leads into CRM contacts."""
    leads = (await db.execute(select(Lead))).scalars().all()
    linked = {row[0] for row in (await db.execute(select(CRMContact.lead_id).where(CRMContact.lead_id.is_not(None)))).all()}
    created = 0
    for lead in leads:
        if lead.id in linked: continue
        parts = (lead.name or "Unnamed contact").strip().split(maxsplit=1)
        contact=CRMContact(lead_id=lead.id, first_name=parts[0], last_name=parts[1] if len(parts) > 1 else "", email=lead.email, phone=lead.phone, stage=lead.routing_status or "lead")
        db.add(contact); await db.flush()
        db.add(CRMActivity(contact_id=contact.id,kind="lead_imported",summary=f"Imported from internal lead source: {lead.source or 'website'}"))
        created += 1
    contacts = (await db.execute(select(CRMContact).where(CRMContact.lead_id.is_not(None)))).scalars().all()
    backfilled = 0
    for contact in contacts:
        has_activity = (await db.execute(select(CRMActivity.id).where(CRMActivity.contact_id == contact.id).limit(1))).scalar_one_or_none()
        if has_activity is None:
            db.add(CRMActivity(contact_id=contact.id, kind="lead_imported", summary="Imported from internal lead source"))
            backfilled += 1
    await db.flush()
    return {"created": created, "timeline_backfilled": backfilled, "total_legacy_leads": len(leads)}

@router.post("/contacts/import")
async def import_contacts(payload:ContactImportRequest,db:AsyncSession=Depends(get_db)):
    created=0;skipped=0
    for row in payload.contacts:
        existing=None
        if row.email: existing=(await db.execute(select(CRMContact).where(CRMContact.email==row.email))).scalar_one_or_none()
        if existing: skipped+=1; continue
        contact=CRMContact(**row.model_dump());db.add(contact);await db.flush()
        db.add(CRMActivity(contact_id=contact.id,kind="contact_imported",summary="Imported through internal CRM import"));created+=1
    await db.flush();return {"created":created,"skipped_duplicates":skipped}


@router.get("/contacts/{contact_id}", response_model=ContactOut)
async def contact_detail(contact_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMContact, contact_id)
    if not item: raise HTTPException(404, "Contact not found")
    return item

@router.patch("/contacts/{contact_id}", response_model=ContactOut)
async def update_contact_stage(contact_id: int, payload: ContactStageUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMContact, contact_id)
    if not item: raise HTTPException(404, "Contact not found")
    item.stage = payload.stage
    db.add(CRMActivity(contact_id=item.id, kind="stage_changed", summary=f"Contact stage changed to {payload.stage}"))
    await db.flush(); return item

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
    opportunity_rows = (await db.execute(
        select(CRMOpportunity, CRMOpportunityContact.role)
        .join(CRMOpportunityContact, CRMOpportunity.id == CRMOpportunityContact.opportunity_id)
        .where(CRMOpportunityContact.contact_id == contact_id)
        .order_by(CRMOpportunity.created_at.desc())
    )).all()
    searches=(await db.execute(select(CRMSavedSearch).where(CRMSavedSearch.contact_id == contact_id))).scalars().all()
    tag_rows=(await db.execute(select(CRMTag).join(CRMContactTag,CRMTag.id==CRMContactTag.tag_id).where(CRMContactTag.contact_id==contact_id))).scalars().all()
    opportunities = [ContactWorkspaceOpportunityOut(id=item.id, name=item.name, stage=item.stage, value_cents=item.value_cents, role=role).model_dump() for item, role in opportunity_rows]
    return {"contact": contact, "timeline": [{"id":a.id,"kind":a.kind,"summary":a.summary,"created_at":a.created_at} for a in activity], "tasks": tasks, "notes": notes, "smart_plans": [{"id":e.id,"plan_id":e.smart_plan_id,"status":e.status} for e in enrollments], "opportunities": opportunities, "saved_searches": [{"id":s.id,"name":s.name,"criteria":s.criteria_json} for s in searches], "tags":[{"id":t.id,"name":t.name} for t in tag_rows]}

@router.post("/tags")
async def create_tag(payload:TagCreate,db:AsyncSession=Depends(get_db)):
    existing=(await db.execute(select(CRMTag).where(CRMTag.name==payload.name))).scalar_one_or_none()
    if existing:return {"id":existing.id,"name":existing.name}
    tag=CRMTag(name=payload.name);db.add(tag);await db.flush();return {"id":tag.id,"name":tag.name}
@router.post("/contacts/{contact_id}/tags/{tag_id}")
async def assign_tag(contact_id:int,tag_id:int,db:AsyncSession=Depends(get_db)):
    if not await db.get(CRMContact,contact_id) or not await db.get(CRMTag,tag_id):raise HTTPException(404,"Contact or tag not found")
    existing=(await db.execute(select(CRMContactTag).where(CRMContactTag.contact_id==contact_id,CRMContactTag.tag_id==tag_id))).scalar_one_or_none()
    if not existing:db.add(CRMContactTag(contact_id=contact_id,tag_id=tag_id));await db.flush()
    return {"contact_id":contact_id,"tag_id":tag_id}

@router.post("/contacts/{contact_id}/notes")
async def create_contact_note(contact_id:int,payload:NoteCreate,db:AsyncSession=Depends(get_db)):
    if not await db.get(CRMContact,contact_id):raise HTTPException(404,"Contact not found")
    note=CRMNote(contact_id=contact_id,body=payload.body);db.add(note);db.add(CRMActivity(contact_id=contact_id,kind="note",summary="Added a contact note"));await db.flush();return {"id":note.id,"body":note.body}
@router.post("/contacts/{contact_id}/saved-searches")
async def create_saved_search(contact_id:int,payload:SavedSearchCreate,db:AsyncSession=Depends(get_db)):
    if not await db.get(CRMContact,contact_id):raise HTTPException(404,"Contact not found")
    item=CRMSavedSearch(contact_id=contact_id,name=payload.name,criteria_json=__import__('json').dumps(payload.criteria));db.add(item);await db.flush();return {"id":item.id,"name":item.name,"criteria":item.criteria_json}


@router.get("/tasks", response_model=list[TaskOut])
async def tasks(status: str | None = None, due_before: datetime | None = None, due_after: datetime | None = None, db: AsyncSession = Depends(get_db)):
    query = select(CRMTask).order_by(CRMTask.due_at.asc().nulls_last())
    if status: query = query.where(CRMTask.status == status)
    if due_before: query = query.where(CRMTask.due_at <= due_before)
    if due_after: query = query.where(CRMTask.due_at >= due_after)
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

@router.post("/tasks/{task_id}/links")
async def add_task_link(task_id: int, payload: TaskLinkCreate, db: AsyncSession = Depends(get_db)):
    if not await db.get(CRMTask, task_id): raise HTTPException(404, "Task not found")
    link = CRMTaskLink(task_id=task_id, **payload.model_dump()); db.add(link); await db.flush()
    return {"id": link.id, "task_id": link.task_id, "entity_type": link.entity_type, "entity_id": link.entity_id}

@router.get("/tasks/{task_id}/links")
async def task_links(task_id: int, db: AsyncSession = Depends(get_db)):
    if not await db.get(CRMTask, task_id): raise HTTPException(404, "Task not found")
    rows = (await db.execute(select(CRMTaskLink).where(CRMTaskLink.task_id == task_id).order_by(CRMTaskLink.id.desc()))).scalars().all()
    return [{"id": row.id, "task_id": row.task_id, "entity_type": row.entity_type, "entity_id": row.entity_id} for row in rows]


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
    await db.flush()
    return {"id": item.id, "status": item.status}

@router.get("/agreements", response_model=list[AgreementOut])
async def agreements(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMAgreement).order_by(CRMAgreement.created_at.desc()))).scalars().all()

@router.post("/agreements", response_model=AgreementOut)
async def create_agreement(payload: AgreementCreate, db: AsyncSession = Depends(get_db)):
    item = CRMAgreement(**payload.model_dump()); db.add(item); await db.flush()
    db.add(CRMAgreementEvent(agreement_id=item.id, event_type="draft")); await db.flush(); return item

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
async def listings(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CRMListingRecord).order_by(CRMListingRecord.created_at.desc()))).scalars().all()

@router.post("/listings", response_model=ListingOut)
async def create_listing(payload: ListingCreate, db: AsyncSession = Depends(get_db)):
    item = CRMListingRecord(**payload.model_dump()); db.add(item); await db.flush(); return item


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

@router.get("/smart-plans/{plan_id}/workspace")
async def smart_plan_workspace(plan_id:int, db:AsyncSession=Depends(get_db)):
    plan=await db.get(CRMSmartPlan,plan_id)
    if not plan: raise HTTPException(404,"Smart Plan not found")
    steps=(await db.execute(select(CRMSmartPlanStep).where(CRMSmartPlanStep.smart_plan_id==plan_id).order_by(CRMSmartPlanStep.position))).scalars().all()
    enrollments=(await db.execute(select(CRMSmartPlanEnrollment).where(CRMSmartPlanEnrollment.smart_plan_id==plan_id))).scalars().all()
    return {"plan":plan,"steps":[{"id":x.id,"position":x.position,"action_type":x.action_type,"payload":x.payload_json} for x in steps],"enrollments":[{"id":x.id,"contact_id":x.contact_id,"status":x.status} for x in enrollments]}

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
    item=CRMSmartPlanEnrollment(smart_plan_id=plan_id,contact_id=payload.contact_id); db.add(item); await db.flush(); return {"id":item.id,"status":item.status}

@router.patch("/smart-plans/{plan_id}/enrollments/{enrollment_id}")
async def update_plan_enrollment(plan_id: int, enrollment_id: int, payload: SmartPlanEnrollmentUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(CRMSmartPlanEnrollment, enrollment_id)
    if not item or item.smart_plan_id != plan_id: raise HTTPException(404, "Smart Plan enrollment not found")
    item.status = payload.status; await db.flush(); return {"id": item.id, "status": item.status}


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
    item.stage = payload.stage; await db.flush(); return item

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
    item=CRMOpportunityContact(opportunity_id=opportunity_id,contact_id=payload.contact_id,role=payload.role);db.add(item);await db.flush();return {"id":item.id,"contact_id":item.contact_id,"role":item.role}
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
