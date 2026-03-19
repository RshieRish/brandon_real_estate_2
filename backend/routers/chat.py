from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models.lead import Lead
from services.gemini import chat_response
import json

router = APIRouter()


class Message(BaseModel):
    role: str  # "user" or "model"
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    lead_context: dict = {}


class ChatResponse(BaseModel):
    reply: str


@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    msgs = [{"role": m.role, "content": m.content} for m in req.messages]
    reply = await chat_response(msgs)
    return ChatResponse(reply=reply)


@router.post("/lead")
async def capture_lead_from_chat(
    name: str, email: str, phone: str = None, lead_type: str = "general",
    db: AsyncSession = Depends(get_db)
):
    lead = Lead(name=name, email=email, phone=phone, source="chatbot", lead_type=lead_type, metadata_json="{}")
    db.add(lead)
    await db.flush()
    return {"id": lead.id, "message": "Lead captured"}
