"""Idempotent seed for the singleton link pack.

Populates Brandon's profile, social links, theme, and 10 initial link items
from his current link-in-bio configuration. Downloads avatar, background image,
and property thumbnails from their public CDN URLs.

Usage:
    python -m scripts.seed_link_pack
"""
import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

# Ensure backend root is on path when run via `python -m`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import AsyncSessionLocal  # noqa: E402
from models.link_pack import LinkPack, LinkPackItem  # noqa: E402
from schemas.link_pack import DEFAULT_THEME  # noqa: E402
from services.link_pack_service import build_snapshot  # noqa: E402
from datetime import datetime, timezone  # noqa: E402


PROFILE_PHOTO_URL = "https://ugc.production.linktr.ee/b6d5aa61-e9c3-4728-8046-7080044ef6e5_Brandon-Sweeney-Headshot-Zoomed-In.png"
BACKGROUND_URL = "https://ugc.production.linktr.ee/c951a70a-c6df-48e5-a61f-5728d6f453f0_Gold-and-Black-Elegant-Abstract-Linktree-Background--5-.png"
LISTING_50_FRANK_THUMB = "https://ugc.production.linktr.ee/8e23039e-c430-4a4e-894a-4c79d07552a4_Resizer.jpeg"
LISTING_37_SAINT_PAUL_THUMB = "https://ugc.production.linktr.ee/b582bb0f-f324-459d-bf87-e7993e50c3ad_Resizer.jpeg"

PROFILE = {
    "name": "Brandon Sweeney | REALTOR®",
    "bio": "NOT your AVERAGE, award winning, philanthropic REALTOR®️ OF THE YEAR 25' at KW Realty Success!",
    "is_verified": True,
}
SOCIAL = {
    "social_phone": "+19789872806",
    "social_email": "Brandon@soldwithsweeney.com",
    "social_instagram": "https://instagram.com/soldwithsweeneyco",
    "social_facebook": "https://www.facebook.com/SoldWithSweeneyCo",
    "social_youtube": "https://www.youtube.com/@soldwithsweeneyco",
    "social_website": "https://soldwithsweeney.kw.com/?kwuid=878439",
}


async def _fetch(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(LinkPack).where(LinkPack.id == 1))
        if result.scalar_one_or_none():
            print("LinkPack already seeded; skipping.")
            return

        print("Fetching profile photo and background...")
        photo_bytes, photo_mime = await _fetch(PROFILE_PHOTO_URL)
        bg_bytes, bg_mime = await _fetch(BACKGROUND_URL)

        pack = LinkPack(
            id=1,
            profile_name=PROFILE["name"],
            profile_bio=PROFILE["bio"],
            is_verified=PROFILE["is_verified"],
            profile_photo_data=photo_bytes,
            profile_photo_mime=photo_mime,
            background_image_data=bg_bytes,
            background_image_mime=bg_mime,
            theme=DEFAULT_THEME,
            **SOCIAL,
        )
        db.add(pack)
        await db.flush()

        print("Fetching listing thumbnails...")
        thumb_50_frank, thumb_50_frank_mime = await _fetch(LISTING_50_FRANK_THUMB)
        thumb_37_saint_paul, thumb_37_saint_paul_mime = await _fetch(LISTING_37_SAINT_PAUL_THUMB)

        # Top-level items in display order
        items: list[tuple[dict, list[dict]]] = [
            ({
                "kind": "thumbnail",
                "title": "50 Frank St #50, Dracut, MA 01826 | Keller Williams",
                "url": "https://soldwithsweeney.kw.com/property/50-Frank-St-50-Dracut-MA-01826/2100015566681408",
                "thumbnail_data": thumb_50_frank,
                "thumbnail_mime": thumb_50_frank_mime,
            }, []),
            ({
                "kind": "email_gate",
                "title": "SELLERS SURVIVAL GUIDE",
                "gate_modal_headline": "Get the Sellers Survival Guide",
                "gate_modal_subtext": "Drop your details and we'll email it to you.",
            }, []),
            ({
                "kind": "classic",
                "title": "BUYERS SURVIVAL GUIDE",
                "url": "https://drive.google.com/file/d/13EVVYhKqdlEQkht1-CZXcrqFOF3acgmm/view?usp=sharing",
            }, []),
            ({
                "kind": "group",
                "title": "SWS AVAILABLE HOMES",
            }, [
                {
                    "kind": "thumbnail",
                    "title": "37 Saint Paul St, Lowell, MA 01851 | Keller Williams",
                    "url": "https://soldwithsweeney.kw.com/property/37-Saint-Paul-St-Lowell-MA-01851/2093151465671102?kwuid=878439",
                    "thumbnail_data": thumb_37_saint_paul,
                    "thumbnail_mime": thumb_37_saint_paul_mime,
                },
            ]),
            ({"kind": "group", "title": "SWS UNDER CONTRACT HOMES"}, []),
            ({"kind": "group", "title": "FREE RESOURCES"}, []),
            ({
                "kind": "classic",
                "title": "WHAT'S MY HOME WORTH? \U0001f4b8",
                "url": "https://soldwithsweeney.kw.com/YourHomeValuation",
            }, []),
            ({
                "kind": "classic",
                "title": "\U0001f4f2 SAVE MY CONTACT INFO",
                "url": "https://typecard.com/a9dc4d67/",
            }, []),
            ({
                "kind": "classic",
                "title": "DOWNLOAD MY APP \U0001f3e1",
                "url": "https://kw.com/download/KW4ABYJHJ",
            }, []),
            ({
                "kind": "classic",
                "title": "\U0001f511 CLIENT TESTIMONIALS",
                "url": "https://profile.realsatisfied.com/Brandon-Sweeney",
            }, []),
        ]

        for position, (parent_data, children_data) in enumerate(items):
            parent = LinkPackItem(
                link_pack_id=1,
                position=position,
                animation="none",
                is_active=True,
                **parent_data,
            )
            db.add(parent)
            await db.flush()
            for c_pos, c_data in enumerate(children_data):
                child = LinkPackItem(
                    link_pack_id=1,
                    parent_id=parent.id,
                    position=c_pos,
                    animation="none",
                    is_active=True,
                    **c_data,
                )
                db.add(child)

        await db.flush()

        # Initial publish so /links works immediately
        items_result = await db.execute(select(LinkPackItem).where(LinkPackItem.link_pack_id == pack.id))
        all_items = list(items_result.scalars().all())
        pack.published_snapshot = build_snapshot(pack, all_items)
        pack.published_at = datetime.now(timezone.utc)
        pack.has_unpublished_changes = False

        await db.commit()
        print(f"Seeded LinkPack with {len(items)} top-level items + nested children. Published.")


if __name__ == "__main__":
    asyncio.run(main())
