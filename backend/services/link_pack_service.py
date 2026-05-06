from datetime import datetime, timedelta, timezone
from typing import Iterable

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.link_pack import LinkPack, LinkPackItem


GATE_TOKEN_TTL_SECONDS = 5 * 60


def _profile_photo_url(pack: LinkPack) -> str | None:
    return "/api/v1/link-pack/images/profile" if pack.profile_photo_mime else None


def _background_image_url(pack: LinkPack) -> str | None:
    return "/api/v1/link-pack/images/background" if pack.background_image_mime else None


def _thumbnail_url(item: LinkPackItem) -> str | None:
    return f"/api/v1/link-pack/images/items/{item.id}/thumbnail" if item.thumbnail_mime else None


def _serialize_item(item: LinkPackItem, children: list[dict]) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        "url": item.url,
        "thumbnail_url": _thumbnail_url(item),
        "gated_filename": item.gated_filename,
        "gate_modal_headline": item.gate_modal_headline,
        "gate_modal_subtext": item.gate_modal_subtext,
        "animation": item.animation,
        "is_active": item.is_active,
        "children": children,
    }


def build_snapshot(pack: LinkPack, items: Iterable[LinkPackItem]) -> dict:
    items = [it for it in items if it.is_active]
    by_parent: dict[int | None, list[LinkPackItem]] = {}
    for it in items:
        by_parent.setdefault(it.parent_id, []).append(it)
    for siblings in by_parent.values():
        siblings.sort(key=lambda x: x.position)

    def _children(parent_id: int) -> list[dict]:
        return [_serialize_item(c, []) for c in by_parent.get(parent_id, [])]

    top_level = by_parent.get(None, [])
    items_payload = []
    for it in top_level:
        kids = _children(it.id) if it.kind == "group" else []
        items_payload.append(_serialize_item(it, kids))

    return {
        "profile": {
            "name": pack.profile_name,
            "bio": pack.profile_bio,
            "photo_url": _profile_photo_url(pack),
            "is_verified": pack.is_verified,
        },
        "social": {
            "phone": pack.social_phone,
            "email": pack.social_email,
            "instagram": pack.social_instagram,
            "facebook": pack.social_facebook,
            "youtube": pack.social_youtube,
            "website": pack.social_website,
            "tiktok": pack.social_tiktok,
            "x": pack.social_x,
        },
        "theme": pack.theme,
        "background_image_url": _background_image_url(pack),
        "items": items_payload,
    }


async def get_or_create_pack(db: AsyncSession) -> LinkPack:
    result = await db.execute(select(LinkPack).where(LinkPack.id == 1))
    pack = result.scalar_one_or_none()
    if pack is None:
        from schemas.link_pack import DEFAULT_THEME
        pack = LinkPack(id=1, theme=DEFAULT_THEME)
        db.add(pack)
        await db.flush()
        await db.refresh(pack)
    return pack


async def mark_dirty(db: AsyncSession) -> None:
    pack = await get_or_create_pack(db)
    pack.has_unpublished_changes = True


def mint_gate_token(item_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(seconds=GATE_TOKEN_TTL_SECONDS)
    payload = {"item_id": item_id, "exp": exp, "scope": "link_pack_gate"}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_gate_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise ValueError(str(e))
    if payload.get("scope") != "link_pack_gate":
        raise ValueError("wrong token scope")
    return int(payload["item_id"])
