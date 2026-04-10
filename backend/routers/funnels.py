from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
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
from services.notification_service import enqueue_notification, run_notification_retry_pass
from middleware.auth import require_admin

router = APIRouter()

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB


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


@router.post("/upload-image")
async def upload_funnel_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"Invalid image type. Allowed: {', '.join(ALLOWED_MIME_TYPES)}")
    data = await file.read()
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(400, "Image too large. Maximum 5MB.")
    # Store in a temporary funnel row or return a temp ID
    # For simplicity, we'll create a placeholder funnel entry or store separately
    # Actually, we return the image data encoded so the create endpoint can use it
    import base64
    encoded = base64.b64encode(data).decode('utf-8')
    return {
        "ok": True,
        "image_data": encoded,
        "mime_type": file.content_type,
        "size": len(data),
        "filename": file.filename,
    }


@router.post("/", response_model=FunnelOut)
async def create_funnel(data: FunnelCreate, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    slug = await _unique_slug(slugify(data.title), db)
    content = await generate_funnel_content(data.title, data.audience, data.description, data.cta_text)
    funnel = Funnel(
        title=data.title, slug=slug, audience=data.audience,
        description=data.description, cta_text=data.cta_text,
        video_url=data.video_url, hero_image_url=data.hero_image_url,
        lead_routing=data.lead_routing,
        generated_content=json.dumps(content), status="draft",
    )
    db.add(funnel)
    await db.flush()
    await db.refresh(funnel)
    return funnel


@router.post("/{funnel_id}/set-image")
async def set_funnel_image(
    funnel_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Upload and attach an image directly to an existing funnel."""
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"Invalid image type. Allowed: {', '.join(ALLOWED_MIME_TYPES)}")
    data = await file.read()
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(400, "Image too large. Maximum 5MB.")

    result = await db.execute(select(Funnel).where(Funnel.id == funnel_id))
    funnel = result.scalar_one_or_none()
    if not funnel:
        raise HTTPException(404, "Funnel not found")

    funnel.hero_image_data = data
    funnel.hero_image_mime = file.content_type
    funnel.hero_image_url = f"/api/v1/funnels/images/{funnel.id}"
    await db.flush()
    await db.refresh(funnel)
    return {"ok": True, "image_url": funnel.hero_image_url}


@router.get("/images/{funnel_id}")
async def get_funnel_image(funnel_id: int, db: AsyncSession = Depends(get_db)):
    """Serve a funnel's hero image from the database."""
    result = await db.execute(select(Funnel).where(Funnel.id == funnel_id))
    funnel = result.scalar_one_or_none()
    if not funnel or not funnel.hero_image_data:
        raise HTTPException(404, "Image not found")
    return Response(
        content=funnel.hero_image_data,
        media_type=funnel.hero_image_mime or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/", response_model=List[FunnelOut])
async def list_funnels(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    result = await db.execute(select(Funnel))
    return result.scalars().all()


@router.get("/{slug}")
async def get_funnel_by_slug(slug: str, preview: bool = False, db: AsyncSession = Depends(get_db)):
    if preview:
        # Allow fetching draft funnels for admin preview
        result = await db.execute(select(Funnel).where(Funnel.slug == slug))
    else:
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
        "hero_image_url": funnel.hero_image_url,
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
    await enqueue_notification(
        db,
        event_type="funnel_registration",
        payload={
            "funnel_id": funnel.id,
            "funnel_slug": funnel.slug,
            "funnel_title": funnel.title,
            "audience": funnel.audience,
            "name": req.name,
            "email": req.email,
            "phone": req.phone,
        },
    )
    await db.commit()
    await run_notification_retry_pass(limit=5)
    return {"ok": True, "message": "Registered successfully"}
