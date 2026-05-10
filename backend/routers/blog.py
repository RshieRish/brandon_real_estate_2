"""
Blog Router for Sold With Sweeney & Co.

Endpoints:
  Public:
    GET  /api/v1/blog/              — list published blogs
    GET  /api/v1/blog/{slug}        — single published blog by slug

  Admin (Bearer JWT required):
    GET  /api/v1/blog/admin/all     — all blogs incl. drafts
    POST /api/v1/blog/              — manual create (form + optional image upload)
    POST /api/v1/blog/generate      — semi-auto: admin picks topic → Gemini drafts
    POST /api/v1/blog/cron          — auto-pilot: fully automated generation
    PUT  /api/v1/blog/{id}          — update title/content/is_posted
    DELETE /api/v1/blog/{id}        — delete blog
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from config import settings
from services.blog_service import BlogService

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Auth helpers — reuses Brandon's existing JWT pattern
# ---------------------------------------------------------------------------

async def _require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        sub: str | None = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return sub
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GenerateDraftRequest(BaseModel):
    topic: str
    category: str


class UpdateBlogRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    excerpt: Optional[str] = None
    is_posted: Optional[bool] = None
    featured: Optional[bool] = None
    category: Optional[str] = None


# ---------------------------------------------------------------------------
# DB helper — list blogs
# ---------------------------------------------------------------------------

def _list_blogs_from_db(published_only: bool = True, limit: int = 50, offset: int = 0) -> List[dict]:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if published_only:
            cur.execute(
                "SELECT * FROM blogs WHERE is_posted = TRUE ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
        else:
            cur.execute(
                "SELECT * FROM blogs ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
        rows = cur.fetchall()
        result = []
        for row in rows:
            r = dict(row)
            r["id"] = str(r["id"])
            r["created_at"] = str(r["created_at"])
            r["updated_at"] = str(r["updated_at"])
            result.append(r)
        return result
    finally:
        conn.close()


def _get_blog_by_slug(slug: str) -> dict | None:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM blogs WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if not row:
            return None
        r = dict(row)
        r["id"] = str(r["id"])
        r["created_at"] = str(r["created_at"])
        r["updated_at"] = str(r["updated_at"])
        return r
    finally:
        conn.close()


def _update_blog_in_db(blog_id: str, fields: dict) -> bool:
    import psycopg2
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(db_url)
    try:
        set_clauses = ", ".join([f"{k} = %s" for k in fields])
        values = list(fields.values()) + [blog_id]
        cur = conn.cursor()
        cur.execute(f"UPDATE blogs SET {set_clauses}, updated_at = NOW() WHERE id = %s", values)
        updated = cur.rowcount > 0
        conn.commit()
        return updated
    except Exception as exc:
        conn.rollback()
        raise exc
    finally:
        conn.close()


def _delete_blog_from_db(blog_id: str) -> bool:
    import psycopg2
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM blogs WHERE id = %s", (blog_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    except Exception as exc:
        conn.rollback()
        raise exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@router.get("/")
async def list_published_blogs(limit: int = 20, offset: int = 0):
    """Return all published blog posts (public)."""
    try:
        return _list_blogs_from_db(published_only=True, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/admin/all")
async def list_all_blogs(
    limit: int = 50,
    offset: int = 0,
    _admin: str = Depends(_require_admin),
):
    """Return ALL blogs including drafts (admin only)."""
    try:
        return _list_blogs_from_db(published_only=False, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{slug}")
async def get_blog(slug: str):
    """Return a single published blog by slug (public)."""
    blog = _get_blog_by_slug(slug)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    if not blog.get("is_posted"):
        raise HTTPException(status_code=404, detail="Blog not found")
    return blog


# ---------------------------------------------------------------------------
# Admin: manual create
# ---------------------------------------------------------------------------

@router.post("/")
async def create_manual_blog(
    title: str = Form(...),
    content: str = Form(...),
    category: str = Form(...),
    is_posted: bool = Form(False),
    image: Optional[UploadFile] = File(None),
    _admin: str = Depends(_require_admin),
):
    """Manual mode: admin provides all content and optional image upload."""
    try:
        result = BlogService.create_manual_blog(title, content, category, is_posted, image)
        return {"success": True, "blog": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Admin: semi-auto draft (admin picks topic → Gemini writes)
# ---------------------------------------------------------------------------

@router.post("/generate")
async def generate_draft(
    request: GenerateDraftRequest,
    _admin: str = Depends(_require_admin),
):
    """Semi-auto: admin provides topic/category → Gemini generates full draft."""
    try:
        result = await BlogService.create_draft_blog(request.topic, request.category)
        return {"success": True, "blog": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Auto-pilot cron trigger
# ---------------------------------------------------------------------------

@router.post("/cron")
async def cron_generate_blog(_admin: str = Depends(_require_admin)):
    """Auto-pilot: fully automated blog generation + publishing."""
    try:
        result = await BlogService.create_auto_blog()
        return {"success": True, "blog": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Admin: update
# ---------------------------------------------------------------------------

@router.put("/{blog_id}")
async def update_blog(
    blog_id: str,
    request: UpdateBlogRequest,
    _admin: str = Depends(_require_admin),
):
    fields = {k: v for k, v in request.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        updated = _update_blog_in_db(blog_id, fields)
        if not updated:
            raise HTTPException(status_code=404, detail="Blog not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Admin: delete
# ---------------------------------------------------------------------------

@router.delete("/{blog_id}")
async def delete_blog(
    blog_id: str,
    _admin: str = Depends(_require_admin),
):
    try:
        deleted = _delete_blog_from_db(blog_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Blog not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
