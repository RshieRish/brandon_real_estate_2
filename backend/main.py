import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import traceback
import logging

from config import settings
from routers import (
    analytics,
    auth,
    blog,
    booking,
    chat,
    content,
    crm,
    evaluator,
    funnels,
    geocode,
    investor,
    leads,
    link_pack,
)
from services.blog_service import BlogService
from services.notification_service import (
    NOTIFICATION_RETRY_INTERVAL_SECONDS,
    run_notification_retry_pass,
)

app = FastAPI(title="Brandon RE API", version="1.0.0", docs_url="/docs")
_notification_retry_task: asyncio.Task | None = None
_blog_auto_post_task: asyncio.Task | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(leads.router, prefix="/api/v1/leads", tags=["leads"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(funnels.router, prefix="/api/v1/funnels", tags=["funnels"])
app.include_router(link_pack.router, prefix="/api/v1/link-pack", tags=["link-pack"])
app.include_router(evaluator.router, prefix="/api/v1/evaluator", tags=["evaluator"])
app.include_router(investor.router, prefix="/api/v1/investor", tags=["investor"])
app.include_router(booking.router, prefix="/api/v1/booking", tags=["booking"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(content.router, prefix="/api/v1/content", tags=["content"])
app.include_router(crm.router, prefix="/api/v1/crm", tags=["crm"])
app.include_router(geocode.router, prefix="/api/v1/geocode", tags=["geocode"])
app.include_router(blog.router, prefix="/api/v1/blog", tags=["blog"])


async def _notification_retry_loop() -> None:
    while True:
        await run_notification_retry_pass(limit=20)
        await asyncio.sleep(NOTIFICATION_RETRY_INTERVAL_SECONDS)


async def _blog_auto_post_loop() -> None:
    """Auto-post a fresh blog every BLOG_AUTO_POST_INTERVAL_HOURS hours.

    Restart-safe: on boot we look at the most recent posted blog's created_at
    and only post if the gap to now is >= the configured interval. This way an
    app restart doesn't double-post within the window.
    """
    interval_seconds = max(3600, settings.BLOG_AUTO_POST_INTERVAL_HOURS * 3600)
    while True:
        try:
            seconds_since_last = _seconds_since_last_posted_blog()
            if seconds_since_last is None or seconds_since_last >= interval_seconds:
                logging.info("[blog-auto] Generating new auto-blog…")
                result = await BlogService.create_auto_blog()
                logging.info("[blog-auto] Posted: id=%s slug=%s", result.get("id"), result.get("slug"))
                sleep_for = interval_seconds
            else:
                sleep_for = interval_seconds - seconds_since_last
                logging.info("[blog-auto] Last post was %ss ago — sleeping %ss until next.", int(seconds_since_last), int(sleep_for))
        except Exception as exc:
            logging.error("[blog-auto] Generation pass failed: %s", exc)
            logging.error(traceback.format_exc())
            sleep_for = interval_seconds
        await asyncio.sleep(sleep_for)


def _seconds_since_last_posted_blog() -> float | None:
    """Return seconds since the most recent posted blog's created_at, or None if none exist."""
    import psycopg2
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = psycopg2.connect(db_url)
        try:
            cur = conn.cursor()
            cur.execute("SELECT created_at FROM blogs WHERE is_posted = TRUE ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            last = row[0]
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return (datetime.now(tz=timezone.utc) - last).total_seconds()
        finally:
            conn.close()
    except Exception as exc:
        logging.error("[blog-auto] Failed to read last-posted timestamp: %s", exc)
        return None


@app.on_event("startup")
async def start_background_loops() -> None:
    global _notification_retry_task, _blog_auto_post_task
    if _notification_retry_task is None or _notification_retry_task.done():
        _notification_retry_task = asyncio.create_task(_notification_retry_loop())
    if settings.BLOG_AUTO_POST_ENABLED and (_blog_auto_post_task is None or _blog_auto_post_task.done()):
        _blog_auto_post_task = asyncio.create_task(_blog_auto_post_loop())


@app.on_event("shutdown")
async def stop_background_loops() -> None:
    global _notification_retry_task, _blog_auto_post_task
    for task_attr in ("_notification_retry_task", "_blog_auto_post_task"):
        task = globals().get(task_attr)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            globals()[task_attr] = None


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Global exception caught: {exc}")
    logging.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc)},
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "brandon-re-api"}
