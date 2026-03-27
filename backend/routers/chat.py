from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Literal
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
    lead_context: dict = Field(default_factory=dict)


class ChatAction(BaseModel):
    type: Literal["send_message", "navigate", "open_widget"]
    label: str
    message: str | None = None
    href: str | None = None
    widget: Literal["calendar_picker"] | None = None


class ChatResponse(BaseModel):
    text: str
    actions: List[ChatAction] = Field(default_factory=list)
    widget: Literal["calendar_picker"] | None = None
    response: str | None = None


@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    msgs = [{"role": m.role, "content": m.content} for m in req.messages]
    try:
        reply = await chat_response(msgs)
    except Exception as e:
        err = str(e)
        if "quota" in err.lower() or "429" in err or "ResourceExhausted" in err:
            raise HTTPException(status_code=503, detail="AI service temporarily unavailable. Please try again later.")
        raise HTTPException(status_code=502, detail="AI service error.")
    return ChatResponse(
        text=reply["text"],
        actions=reply["actions"],
        widget=reply["widget"],
        response=reply["text"],
    )


class CaptureLeadRequest(BaseModel):
    name: str
    email: str
    phone: str | None = None
    lead_type: str = "general"
    lead_context: dict = Field(default_factory=dict)


@router.post("/lead")
async def capture_lead_from_chat(req: CaptureLeadRequest, db: AsyncSession = Depends(get_db)):
    lead = Lead(
        name=req.name, email=req.email, phone=req.phone,
        source="chatbot", lead_type=req.lead_type,
        metadata_json=json.dumps(req.lead_context),
    )
    db.add(lead)
    await db.flush()
    return {"id": lead.id, "message": "Lead captured"}
