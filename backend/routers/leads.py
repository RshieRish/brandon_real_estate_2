from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
import json
from database import get_db
from models.lead import Lead
from schemas.lead import LeadCreate, LeadUpdate, LeadOut
from middleware.auth import require_admin

router = APIRouter()


@router.post("/", response_model=LeadOut)
async def create_lead(data: LeadCreate, db: AsyncSession = Depends(get_db)):
    lead = Lead(
        name=data.name, email=data.email, phone=data.phone,
        source=data.source, lead_type=data.lead_type,
        metadata_json=json.dumps(data.metadata_ or {})
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


@router.get("/", response_model=List[LeadOut])
async def list_leads(
    lead_type: Optional[str] = None,
    routing_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    q = select(Lead).order_by(desc(Lead.created_at))
    if lead_type:
        q = q.where(Lead.lead_type == lead_type)
    if routing_status:
        q = q.where(Lead.routing_status == routing_status)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: int,
    data: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    if data.routing_status is not None:
        lead.routing_status = data.routing_status
    if data.notes is not None:
        lead.notes = data.notes
    await db.flush()
    await db.refresh(lead)
    return lead
