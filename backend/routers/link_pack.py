import base64

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
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
    items_result = await db.execute(select(LinkPackItem).where(LinkPackItem.link_pack_id == pack.id))
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


_TRANSPARENT_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _image_response(data: bytes | None, mime: str | None) -> Response:
    if not data:
        return Response(
            content=_TRANSPARENT_PNG,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        content=data,
        media_type=mime or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/images/profile")
async def get_profile_image(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LinkPack).where(LinkPack.id == 1))
    pack = result.scalar_one_or_none()
    return _image_response(
        pack.profile_photo_data if pack else None,
        pack.profile_photo_mime if pack else None,
    )


@router.get("/images/background")
async def get_background_image(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LinkPack).where(LinkPack.id == 1))
    pack = result.scalar_one_or_none()
    return _image_response(
        pack.background_image_data if pack else None,
        pack.background_image_mime if pack else None,
    )


@router.get("/images/items/{item_id}/thumbnail")
async def get_item_thumbnail(item_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LinkPackItem).where(LinkPackItem.id == item_id))
    item = result.scalar_one_or_none()
    return _image_response(
        item.thumbnail_data if item else None,
        item.thumbnail_mime if item else None,
    )
