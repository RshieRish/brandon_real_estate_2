from pydantic import BaseModel
from pydantic import ConfigDict
from typing import Optional
from datetime import datetime

class ContentBlockUpdate(BaseModel):
    content: str

class ContentBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    block_id: str
    content: str
    content_type: str
    page: Optional[str] = None
    updated_at: datetime
