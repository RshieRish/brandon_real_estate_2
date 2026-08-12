from datetime import datetime
from pydantic import BaseModel, Field


class ContactCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(default="", max_length=120)
    email: str | None = None
    phone: str | None = None
    lead_id: int | None = None


class ContactOut(ContactCreate):
    id: int
    stage: str
    class Config: from_attributes = True


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    contact_id: int | None = None
    description: str = ""
    priority: str = "normal"
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    status: str | None = None
    title: str | None = None
    due_at: datetime | None = None


class TaskOut(TaskCreate):
    id: int
    status: str
    class Config: from_attributes = True


class OverviewOut(BaseModel):
    contacts: int
    open_tasks: int
    opportunities: int
    active_smart_plans: int


class AgreementStatusUpdate(BaseModel):
    status: str


class NamedRecordCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""


class NamedRecordOut(NamedRecordCreate):
    id: int
    status: str
    class Config: from_attributes = True


class OpportunityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    stage: str = "cultivate"
    value_cents: int | None = None


class OpportunityOut(OpportunityCreate):
    id: int
    class Config: from_attributes = True

class AgreementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    contact_id: int | None = None

class AgreementOut(AgreementCreate):
    id: int
    status: str
    class Config: from_attributes = True

class ListingCreate(BaseModel):
    address: str = Field(min_length=3, max_length=500)
    latitude: str | None = None
    longitude: str | None = None

class ListingOut(ListingCreate):
    id: int
    status: str
    class Config: from_attributes = True

class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    body: str = ""
class TemplateOut(TemplateCreate):
    id: int
    class Config: from_attributes = True
class FileAssetCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    storage_key: str = Field(min_length=1, max_length=500)
    content_type: str = "application/octet-stream"
class FileAssetOut(FileAssetCreate):
    id: int
    class Config: from_attributes = True
