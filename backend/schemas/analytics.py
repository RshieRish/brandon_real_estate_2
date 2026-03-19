from pydantic import BaseModel
from typing import Optional


class EventCreate(BaseModel):
    event_type: str
    page: Optional[str] = None
    referrer: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: Optional[dict] = None
