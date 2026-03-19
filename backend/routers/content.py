from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from database import get_db
from models.content_block import ContentBlock
from schemas.content import ContentBlockUpdate, ContentBlockOut
from middleware.auth import require_admin

router = APIRouter()

@router.get("/", response_model=List[ContentBlockOut])
async def list_content(page: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(ContentBlock)
    if page: q = q.where(ContentBlock.page == page)
    result = await db.execute(q)
    return result.scalars().all()

@router.get("/{block_id}", response_model=ContentBlockOut)
async def get_block(block_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContentBlock).where(ContentBlock.block_id == block_id))
    block = result.scalar_one_or_none()
    if not block: raise HTTPException(404, "Block not found")
    return block

@router.put("/{block_id}", response_model=ContentBlockOut)
async def update_block(block_id: str, data: ContentBlockUpdate, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    result = await db.execute(select(ContentBlock).where(ContentBlock.block_id == block_id))
    block = result.scalar_one_or_none()
    if not block: raise HTTPException(404, "Block not found")
    block.content = data.content
    await db.flush()
    await db.refresh(block)
    return block
