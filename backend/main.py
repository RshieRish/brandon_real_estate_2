import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import traceback
import logging

from config import settings
from routers import (
    analytics,
    auth,
    booking,
    chat,
    content,
    crm,
    evaluator,
    funnels,
    investor,
    leads,
)
from services.notification_service import (
    NOTIFICATION_RETRY_INTERVAL_SECONDS,
    run_notification_retry_pass,
)

app = FastAPI(title="Brandon RE API", version="1.0.0", docs_url="/docs")
_notification_retry_task: asyncio.Task | None = None

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
app.include_router(evaluator.router, prefix="/api/v1/evaluator", tags=["evaluator"])
app.include_router(investor.router, prefix="/api/v1/investor", tags=["investor"])
app.include_router(booking.router, prefix="/api/v1/booking", tags=["booking"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(content.router, prefix="/api/v1/content", tags=["content"])
app.include_router(crm.router, prefix="/api/v1/crm", tags=["crm"])


async def _notification_retry_loop() -> None:
    while True:
        await run_notification_retry_pass(limit=20)
        await asyncio.sleep(NOTIFICATION_RETRY_INTERVAL_SECONDS)


@app.on_event("startup")
async def start_notification_retry_loop() -> None:
    global _notification_retry_task
    if _notification_retry_task is None or _notification_retry_task.done():
        _notification_retry_task = asyncio.create_task(_notification_retry_loop())


@app.on_event("shutdown")
async def stop_notification_retry_loop() -> None:
    global _notification_retry_task
    if _notification_retry_task:
        _notification_retry_task.cancel()
        try:
            await _notification_retry_task
        except asyncio.CancelledError:
            pass
        _notification_retry_task = None


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
