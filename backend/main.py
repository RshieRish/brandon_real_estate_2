from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app = FastAPI(title="Brandon RE API", version="1.0.0", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "brandon-re-api"}
