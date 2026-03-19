from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class FunnelCreate(BaseModel):
    title: str
    audience: str = "general"
    event_date: Optional[datetime] = None
    description: str = ""
    cta_text: str = "Register Now"
    video_url: Optional[str] = None
    lead_routing: str = "dashboard"

class FunnelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    audience: str
    status: str
    registrations: int
    generated_content: str
    created_at: datetime
