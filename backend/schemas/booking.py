from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class BookingCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    meeting_type: str = "phone"
    context: str = "general"
    scheduled_at: datetime
    notes: Optional[str] = ""

class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    meeting_type: str
    context: str
    scheduled_at: datetime
