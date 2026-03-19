from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class LeadCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    source: Optional[str] = "website"
    lead_type: Optional[str] = "general"
    metadata_: Optional[dict] = {}


class LeadUpdate(BaseModel):
    routing_status: Optional[str] = None
    notes: Optional[str] = None


class LeadOut(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    source: Optional[str]
    lead_type: Optional[str]
    routing_status: str
    notes: str
    created_at: datetime

    class Config:
        from_attributes = True
