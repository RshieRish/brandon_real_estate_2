import asyncio
import random
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
# Arbitrary bigint identifier for the pg_advisory_lock used by the blog
# scheduler. Same value across all workers/replicas — only one process at a
# time can hold it, so only one worker actually runs the Gemini pipeline.
_BLOG_POST_LOCK_KEY = 842913571
# Connection that is currently holding the advisory lock. Held module-wide
# because pg advisory locks are released when the connection closes — we
# keep this open across the lock_try → release boundary.
_blog_post_lock_conn = None  # type: ignore[var-annotated]

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


def _try_claim_post_lock() -> bool:
    """Try to claim the blog-poster role via a non-blocking postgres advisory
    lock. Returns True if this worker got the lock; the caller MUST call
    `_release_post_lock()` once it's done to free the slot.

    Only one of N uvicorn workers (and N replicas) actually runs the Gemini
    pipeline per cycle — the rest see False and skip until next iteration.
    """
    global _blog_post_lock_conn
    _release_post_lock()  # be tidy in case a previous iteration leaked

    import psycopg2
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_BLOG_POST_LOCK_KEY,))
        got = bool(cur.fetchone()[0])
        if got:
            _blog_post_lock_conn = conn
        else:
            conn.close()
        return got
    except Exception as exc:
        logging.error("[blog-auto] Failed to acquire post lock: %s", exc)
        return False


def _release_post_lock() -> None:
    global _blog_post_lock_conn
    if _blog_post_lock_conn is None:
        return
    try:
        cur = _blog_post_lock_conn.cursor()
        cur.execute("SELECT pg_advisory_unlock(%s)", (_BLOG_POST_LOCK_KEY,))
    except Exception:
        pass  # connection close below also releases the lock
    try:
        _blog_post_lock_conn.close()
    except Exception:
        pass
    _blog_post_lock_conn = None


async def _blog_auto_post_loop() -> None:
    """Auto-post a fresh blog every BLOG_AUTO_POST_INTERVAL_HOURS hours.

    Restart-safe: each iteration looks at the most recent posted blog's
    created_at and only posts if the gap to now is >= the configured interval.

    Concurrency-safe: gated by a postgres advisory lock so multi-worker /
    multi-replica deploys don't fire simultaneous Gemini pipelines.
    """
    interval_seconds = max(3600, settings.BLOG_AUTO_POST_INTERVAL_HOURS * 3600)
    # Random startup jitter (0–30s) so N workers don't all hit the lock at the
    # same instant; reduces wasted DB connections.
    await asyncio.sleep(random.uniform(0, 30))

    while True:
        sleep_for = interval_seconds
        try:
            seconds_since_last = _seconds_since_last_posted_blog()
            if seconds_since_last is None or seconds_since_last >= interval_seconds:
                if _try_claim_post_lock():
                    try:
                        # Re-check inside the lock — another worker may have
                        # just posted while we were acquiring it.
                        recheck = _seconds_since_last_posted_blog()
                        if recheck is None or recheck >= interval_seconds:
                            logging.info("[blog-auto] Generating new auto-blog (lock held)…")
                            result = await BlogService.create_auto_blog()
                            logging.info("[blog-auto] Posted: id=%s slug=%s", result.get("id"), result.get("slug"))
                        else:
                            logging.info("[blog-auto] Recheck: another worker posted %ss ago; skipping.", int(recheck))
                    finally:
                        _release_post_lock()
                else:
                    logging.info("[blog-auto] Another worker holds the post lock; skipping this cycle.")
            else:
                sleep_for = interval_seconds - seconds_since_last
                logging.info("[blog-auto] Last post was %ss ago — sleeping %ss until next.", int(seconds_since_last), int(sleep_for))
        except Exception as exc:
            logging.error("[blog-auto] Generation pass failed: %s", exc)
            logging.error(traceback.format_exc())
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
