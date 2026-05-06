from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import require_admin
from models.link_pack import LinkPack, LinkPackItem
from services.link_pack_service import build_snapshot, get_or_create_pack

router = APIRouter()


@router.get("/")
async def get_public(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LinkPack).where(LinkPack.id == 1))
    pack = result.scalar_one_or_none()
    if not pack or not pack.published_snapshot:
        raise HTTPException(404, "Link pack not published yet")
    return pack.published_snapshot


@router.get("/draft")
async def get_draft(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    pack = await get_or_create_pack(db)
    items_result = await db.execute(select(LinkPackItem))
    items = list(items_result.scalars().all())
    snapshot = build_snapshot(pack, items)
    return {
        "live": snapshot,
        "status": {
            "has_unpublished_changes": pack.has_unpublished_changes,
            "published_at": pack.published_at.isoformat() if pack.published_at else None,
            "is_published": pack.published_snapshot is not None,
        },
    }
