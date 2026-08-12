from datetime import date, datetime
from pydantic import BaseModel, Field


class ContactCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(default="", max_length=120)
    email: str | None = None
    phone: str | None = None
    lead_id: int | None = None
    birthday: date | None = None
    anniversary: date | None = None


class ContactStageUpdate(BaseModel):
    stage: str = Field(min_length=1, max_length=50)


class ContactUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    stage: str | None = Field(default=None, min_length=1, max_length=50)
    birthday: date | None = None
    anniversary: date | None = None


class ContactOut(ContactCreate):
    id: int
    stage: str
    class Config: from_attributes = True


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    contact_id: int | None = None
    description: str = ""
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|in_progress|completed|cancelled)$")
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    priority: str | None = Field(default=None, pattern="^(low|normal|high)$")
    due_at: datetime | None = None
    contact_id: int | None = Field(default=None, ge=1)


class TaskLinkCreate(BaseModel):
    entity_type: str = Field(min_length=1, max_length=50)
    entity_id: int = Field(gt=0)


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

class SmartPlanStatusUpdate(BaseModel):
    status: str = Field(pattern="^(active|paused|archived)$")


class OpportunityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    stage: str = Field(default="cultivate", pattern="^(cultivate|appointment|active|offer|under_contract|closed|lost)$")
    value_cents: int | None = None


class OpportunityUpdate(BaseModel):
    stage: str = Field(pattern="^(cultivate|appointment|active|offer|under_contract|closed|lost)$")


class OpportunityOut(OpportunityCreate):
    id: int
    class Config: from_attributes = True

class AgreementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    contact_id: int | None = None
    template_id: int | None = None

class AgreementOut(AgreementCreate):
    id: int
    status: str
    class Config: from_attributes = True

class ListingCreate(BaseModel):
    address: str = Field(min_length=3, max_length=500)
    latitude: str | None = None
    longitude: str | None = None

class ListingStatusUpdate(BaseModel):
    status: str = Field(pattern="^(active|pending|sold|withdrawn)$")

class ReferralCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source: str = ""
    contact_id: int | None = None
class ReferralUpdate(BaseModel):
    status: str = Field(pattern="^(new|contacted|nurture|converted|closed|lost)$")
class ReferralOut(ReferralCreate):
    id: int
    status: str
    class Config: from_attributes = True

class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    target_value: int = Field(gt=0)
    current_value: int = Field(default=0, ge=0)
    period: str = Field(default="monthly", pattern="^(weekly|monthly|quarterly|annual)$")
class GoalUpdate(BaseModel):
    current_value: int = Field(ge=0)
class GoalOut(GoalCreate):
    id: int
    class Config: from_attributes = True

class ListingOut(ListingCreate):
    id: int
    status: str
    class Config: from_attributes = True

class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    body: str = ""
class TemplateUpdate(BaseModel):
    body: str = ""
class TemplateOut(TemplateCreate):
    id: int
    class Config: from_attributes = True
class FileAssetCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    storage_key: str = Field(min_length=1, max_length=500)
    content_type: str = "application/octet-stream"
    agreement_id: int | None = None
class FileAssetOut(FileAssetCreate):
    id: int
    class Config: from_attributes = True

class RelationshipCreate(BaseModel):
    name: str | None = None
    contact_id: int | None = None
    role: str = "client"
    amount_cents: int | None = None
    email: str | None = None
    status: str = "draft"
class RelationshipOut(RelationshipCreate):
    id: int
    class Config: from_attributes = True
class SmartPlanStepCreate(BaseModel):
    position: int = Field(ge=1)
    action_type: str = Field(min_length=1, max_length=50)
    payload: dict = {}
class SmartPlanEnrollmentCreate(BaseModel):
    contact_id: int
class SmartPlanEnrollmentUpdate(BaseModel):
    status: str = Field(pattern="^(active|paused|completed)$")
class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
class NoteCreate(BaseModel):
    body: str = Field(min_length=1)
class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    criteria: dict = {}
class ContactImportRow(BaseModel):
    first_name: str = Field(min_length=1,max_length=120)
    last_name: str = ""
    email: str | None = None
    phone: str | None = None
    stage: str = "lead"
    birthday: date | None = None
    anniversary: date | None = None
class ContactImportRequest(BaseModel):
    contacts: list[ContactImportRow] = Field(max_length=1000)


class ContactImportResult(BaseModel):
    created: int
    skipped_duplicates: int


class ArchiveTaskImportRow(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    contact_email: str | None = None
    description: str = ""
    status: str = Field(default="open", pattern="^(open|in_progress|completed|cancelled)$")
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    due_at: datetime | None = None


class ArchiveNoteImportRow(BaseModel):
    contact_email: str
    body: str = Field(min_length=1)


class ArchiveOpportunityImportRow(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    stage: str = Field(default="cultivate", pattern="^(cultivate|appointment|active|offer|under_contract|closed|lost)$")
    value_cents: int | None = None
    contact_emails: list[str] = Field(default_factory=list, max_length=100)


class ArchiveReferralImportRow(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source: str = ""
    status: str = Field(default="new", pattern="^(new|contacted|nurture|converted|closed|lost)$")
    contact_email: str | None = None


class ArchiveListingImportRow(BaseModel):
    address: str = Field(min_length=3, max_length=500)
    latitude: str | None = None
    longitude: str | None = None
    status: str = Field(default="active", pattern="^(active|pending|sold|withdrawn)$")


class ArchiveTemplateImportRow(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    body: str = ""


class ArchiveAgreementImportRow(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    contact_email: str | None = None
    template_name: str | None = None
    status: str = Field(default="draft", pattern="^(draft|in_review|ready|shared|viewed|completed|voided|expired)$")


class ArchiveBundleImportRequest(BaseModel):
    contacts: list[ContactImportRow] = Field(default_factory=list, max_length=10000)
    tasks: list[ArchiveTaskImportRow] = Field(default_factory=list, max_length=10000)
    notes: list[ArchiveNoteImportRow] = Field(default_factory=list, max_length=10000)
    opportunities: list[ArchiveOpportunityImportRow] = Field(default_factory=list, max_length=10000)
    referrals: list[ArchiveReferralImportRow] = Field(default_factory=list, max_length=10000)
    listings: list[ArchiveListingImportRow] = Field(default_factory=list, max_length=10000)
    templates: list[ArchiveTemplateImportRow] = Field(default_factory=list, max_length=10000)
    agreements: list[ArchiveAgreementImportRow] = Field(default_factory=list, max_length=10000)


class ArchiveBundleImportResult(BaseModel):
    created: dict[str, int]
    skipped_duplicates: dict[str, int]
    unresolved_contact_references: int


class ContactWorkspaceOpportunityOut(BaseModel):
    id: int
    name: str
    stage: str
    value_cents: int | None = None
    role: str
