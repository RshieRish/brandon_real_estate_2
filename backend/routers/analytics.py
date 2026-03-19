from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from datetime import datetime, timedelta, timezone
import json
from database import get_db
from models.analytics_event import AnalyticsEvent
from schemas.analytics import EventCreate
from middleware.auth import require_admin

router = APIRouter()


def detect_device(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "mobile" in ua or "android" in ua:
        return "mobile"
    if "tablet" in ua or "ipad" in ua:
        return "tablet"
    return "desktop"


@router.post("/event")
async def track_event(data: EventCreate, db: AsyncSession = Depends(get_db)):
    event = AnalyticsEvent(
        event_type=data.event_type,
        page=data.page,
        referrer=data.referrer,
        user_agent=data.user_agent,
        device_type=detect_device(data.user_agent or ""),
        metadata_json=json.dumps(data.metadata or {}),
    )
    db.add(event)
    return {"ok": True}


@router.get("/dashboard")
async def dashboard_stats(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(func.count()).where(
            AnalyticsEvent.created_at >= since,
            AnalyticsEvent.event_type == "page_view",
        )
    )
    page_views = result.scalar() or 0
    result2 = await db.execute(
        select(AnalyticsEvent.page, func.count().label("count"))
        .where(
            AnalyticsEvent.created_at >= since,
            AnalyticsEvent.event_type == "page_view",
        )
        .group_by(AnalyticsEvent.page)
        .order_by(desc("count"))
        .limit(10)
    )
    top_pages = [{"page": row[0], "count": row[1]} for row in result2]
    return {"page_views": page_views, "top_pages": top_pages}
