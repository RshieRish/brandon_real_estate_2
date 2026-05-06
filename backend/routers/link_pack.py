import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import require_admin
from models.link_pack import LinkPack, LinkPackItem
from schemas.link_pack import ProfileIn, SocialIn, ThemeIn
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


@router.put("/profile")
async def update_profile(
    data: ProfileIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    pack = await get_or_create_pack(db)
    pack.profile_name = data.profile_name
    pack.profile_bio = data.profile_bio
    pack.is_verified = data.is_verified
    pack.has_unpublished_changes = True
    await db.flush()
    return {"ok": True}


@router.put("/social")
async def update_social(
    data: SocialIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    pack = await get_or_create_pack(db)
    for field in (
        "social_phone", "social_email", "social_instagram", "social_facebook",
        "social_youtube", "social_website", "social_tiktok", "social_x",
    ):
        setattr(pack, field, getattr(data, field))
    pack.has_unpublished_changes = True
    await db.flush()
    return {"ok": True}


@router.put("/theme")
async def update_theme(
    data: ThemeIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    pack = await get_or_create_pack(db)
    pack.theme = data.model_dump()
    pack.has_unpublished_changes = True
    await db.flush()
    return {"ok": True}


ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024


async def _read_image(file: UploadFile) -> tuple[bytes, str]:
    if file.content_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(400, f"Invalid image type. Allowed: {', '.join(sorted(ALLOWED_IMAGE_MIMES))}")
    data = await file.read()
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(400, "Image too large. Maximum 5MB.")
    return data, file.content_type


@router.post("/profile-photo")
async def upload_profile_photo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    data, mime = await _read_image(file)
    pack = await get_or_create_pack(db)
    pack.profile_photo_data = data
    pack.profile_photo_mime = mime
    pack.has_unpublished_changes = True
    await db.flush()
    return {"ok": True, "url": "/api/v1/link-pack/images/profile"}


@router.post("/background-image")
async def upload_background_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    data, mime = await _read_image(file)
    pack = await get_or_create_pack(db)
    pack.background_image_data = data
    pack.background_image_mime = mime
    pack.has_unpublished_changes = True
    await db.flush()
    return {"ok": True, "url": "/api/v1/link-pack/images/background"}


from schemas.link_pack import ItemIn, ItemPatch


def _validate_item_invariants(data: ItemIn, parent: LinkPackItem | None = None) -> None:
    if data.kind == "group" and data.parent_id is not None:
        raise HTTPException(400, "Groups cannot be nested (max 1 level deep).")
    if data.parent_id is not None:
        if parent is None:
            raise HTTPException(400, "Parent item not found.")
        if parent.kind != "group":
            raise HTTPException(400, "Parent must be a group.")


async def _next_position(db: AsyncSession, parent_id: int | None) -> int:
    from sqlalchemy import func as sqlfunc
    stmt = select(sqlfunc.coalesce(sqlfunc.max(LinkPackItem.position), -1)).where(
        LinkPackItem.parent_id.is_(parent_id) if parent_id is None else LinkPackItem.parent_id == parent_id
    )
    result = await db.execute(stmt)
    return int(result.scalar_one()) + 1


@router.post("/items")
async def create_item(
    data: ItemIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    parent = None
    if data.parent_id is not None:
        result = await db.execute(select(LinkPackItem).where(LinkPackItem.id == data.parent_id))
        parent = result.scalar_one_or_none()
    _validate_item_invariants(data, parent=parent)

    pack = await get_or_create_pack(db)
    position = await _next_position(db, data.parent_id)
    item = LinkPackItem(
        link_pack_id=pack.id,
        parent_id=data.parent_id,
        position=position,
        kind=data.kind,
        title=data.title,
        url=data.url,
        animation=data.animation,
        is_active=data.is_active,
        gate_modal_headline=data.gate_modal_headline,
        gate_modal_subtext=data.gate_modal_subtext,
    )
    db.add(item)
    pack.has_unpublished_changes = True
    await db.flush()
    await db.refresh(item)
    return {
        "id": item.id,
        "parent_id": item.parent_id,
        "position": item.position,
        "kind": item.kind,
        "title": item.title,
        "url": item.url,
        "animation": item.animation,
        "is_active": item.is_active,
    }


@router.patch("/items/{item_id}")
async def patch_item(
    item_id: int,
    data: ItemPatch,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(LinkPackItem).where(LinkPackItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    payload = data.model_dump(exclude_unset=True)
    for k, v in payload.items():
        setattr(item, k, v)
    pack = await get_or_create_pack(db)
    pack.has_unpublished_changes = True
    await db.flush()
    return {"ok": True}


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(LinkPackItem).where(LinkPackItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    await db.delete(item)
    pack = await get_or_create_pack(db)
    pack.has_unpublished_changes = True
    await db.flush()
    return {"ok": True}


ALLOWED_PDF_MIMES = {"application/pdf"}
MAX_PDF_SIZE = 10 * 1024 * 1024


@router.post("/items/{item_id}/thumbnail")
async def upload_item_thumbnail(
    item_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(LinkPackItem).where(LinkPackItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    data, mime = await _read_image(file)
    item.thumbnail_data = data
    item.thumbnail_mime = mime
    pack = await get_or_create_pack(db)
    pack.has_unpublished_changes = True
    await db.flush()
    return {"ok": True, "url": f"/api/v1/link-pack/images/items/{item_id}/thumbnail"}


@router.post("/items/{item_id}/gated-file")
async def upload_gated_file(
    item_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(LinkPackItem).where(LinkPackItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    if file.content_type not in ALLOWED_PDF_MIMES:
        raise HTTPException(400, "Only PDF files are allowed.")
    data = await file.read()
    if len(data) > MAX_PDF_SIZE:
        raise HTTPException(400, "PDF too large. Maximum 10MB.")
    item.gated_file_data = data
    item.gated_file_mime = file.content_type
    item.gated_filename = file.filename or "download.pdf"
    pack = await get_or_create_pack(db)
    pack.has_unpublished_changes = True
    await db.flush()
    return {"ok": True, "filename": item.gated_filename}
