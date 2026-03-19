from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
import re, json
from database import get_db
from models.funnel import Funnel
from models.lead import Lead
from schemas.funnel import FunnelCreate, FunnelOut
from services.funnel_service import generate_funnel_content
from middleware.auth import require_admin

router = APIRouter()


class RegisterRequest(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None


def slugify(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


async def _unique_slug(base_slug: str, db: AsyncSession) -> str:
    slug = base_slug
    suffix = 1
    while True:
        result = await db.execute(select(Funnel).where(Funnel.slug == slug))
        if not result.scalar_one_or_none():
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1


@router.post("/", response_model=FunnelOut)
async def create_funnel(data: FunnelCreate, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    slug = await _unique_slug(slugify(data.title), db)
    content = await generate_funnel_content(data.title, data.audience, data.description, data.cta_text)
    funnel = Funnel(
        title=data.title, slug=slug, audience=data.audience,
        description=data.description, cta_text=data.cta_text,
        video_url=data.video_url, lead_routing=data.lead_routing,
        generated_content=json.dumps(content), status="draft",
    )
    db.add(funnel)
    await db.flush()
    await db.refresh(funnel)
    return funnel

@router.get("/", response_model=List[FunnelOut])
async def list_funnels(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    result = await db.execute(select(Funnel))
    return result.scalars().all()

@router.get("/{slug}")
async def get_funnel_by_slug(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Funnel).where(Funnel.slug == slug, Funnel.status == "published"))
    funnel = result.scalar_one_or_none()
    if not funnel:
        raise HTTPException(404, "Funnel not found")
    content = json.loads(funnel.generated_content or "{}")
    return {
        "id": funnel.id,
        "title": funnel.title,
        "slug": funnel.slug,
        "audience": funnel.audience,
        "event_date": funnel.event_date,
        "cta_text": funnel.cta_text,
        "video_url": funnel.video_url,
        "content": content,
    }

@router.put("/{funnel_id}/publish", response_model=FunnelOut)
async def publish_funnel(funnel_id: int, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    result = await db.execute(select(Funnel).where(Funnel.id == funnel_id))
    funnel = result.scalar_one_or_none()
    if not funnel:
        raise HTTPException(404, "Funnel not found")
    funnel.status = "published"
    await db.flush()
    await db.refresh(funnel)
    return funnel

@router.post("/{slug}/register")
async def register_for_funnel(slug: str, req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Funnel).where(Funnel.slug == slug))
    funnel = result.scalar_one_or_none()
    if not funnel:
        raise HTTPException(404, "Funnel not found")
    lead = Lead(name=req.name, email=req.email, phone=req.phone, source=f"funnel:{slug}", lead_type=funnel.audience, metadata_json=json.dumps({"funnel_id": funnel.id}))
    db.add(lead)
    funnel.registrations = (funnel.registrations or 0) + 1
    await db.flush()
    return {"ok": True, "message": "Registered successfully"}
