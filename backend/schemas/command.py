from datetime import date, datetime
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_RFC3339_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
POSTGRES_INTEGER_MAX = 2_147_483_647
DatabaseInteger = Annotated[
    int,
    Field(ge=1, le=POSTGRES_INTEGER_MAX, strict=True),
]


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
    model_config = ConfigDict(extra="forbid")

    expected_version: DatabaseInteger
    status: Literal["open", "in_progress", "completed", "cancelled"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=65_536)
    priority: Literal["low", "normal", "high"] | None = None
    due_at: datetime | None = None
    contact_id: DatabaseInteger | None = None

    @field_validator("title")
    @classmethod
    def require_nonblank_title(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title cannot be blank")
        return value

    @field_validator("due_at", mode="before")
    @classmethod
    def reject_non_datetime_due_input(cls, value: object) -> object:
        if value is None or isinstance(value, datetime):
            return value
        if type(value) is str and _RFC3339_DATETIME_PATTERN.fullmatch(value):
            return value
        raise ValueError("due_at must be an RFC 3339 datetime")

    @field_validator("due_at")
    @classmethod
    def require_due_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include a UTC offset")
        return value

    @model_validator(mode="after")
    def require_mutable_nonnull_change(self):
        mutable_fields = {
            "status",
            "title",
            "description",
            "priority",
            "due_at",
            "contact_id",
        }
        provided = self.model_fields_set & mutable_fields
        if not provided:
            raise ValueError("at least one mutable task field is required")
        nonnullable = {"status", "title", "description", "priority"}
        if any(getattr(self, field) is None for field in provided & nonnullable):
            raise ValueError("non-nullable task fields cannot be null")
        return self


class TaskLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_version: DatabaseInteger
    reason: str | None = Field(default=None, max_length=500)


class TaskLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1, max_length=50)
    entity_id: DatabaseInteger
    expected_version: DatabaseInteger


class TaskOut(TaskCreate):
    id: int
    status: str
    archived_at: datetime | None
    archive_reason: str | None
    version: int
    class Config: from_attributes = True


class TaskLinkOut(BaseModel):
    id: int
    task_id: int
    entity_type: str
    entity_id: int
    display_name: str
    task_version: int


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
    source_row_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    contact_email: str | None = None
    description: str = ""
    status: str = Field(default="open", pattern="^(open|in_progress|completed|cancelled)$")
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    due_at: datetime | None = None

    @field_validator("source_row_id")
    @classmethod
    def reject_blank_source_row_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_row_id must not be blank")
        return value


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
    source_id: str | None = Field(default=None, min_length=1, max_length=255)
    contacts: list[ContactImportRow] = Field(default_factory=list, max_length=10000)
    tasks: list[ArchiveTaskImportRow] = Field(default_factory=list, max_length=10000)
    notes: list[ArchiveNoteImportRow] = Field(default_factory=list, max_length=10000)
    opportunities: list[ArchiveOpportunityImportRow] = Field(default_factory=list, max_length=10000)
    referrals: list[ArchiveReferralImportRow] = Field(default_factory=list, max_length=10000)
    listings: list[ArchiveListingImportRow] = Field(default_factory=list, max_length=10000)
    templates: list[ArchiveTemplateImportRow] = Field(default_factory=list, max_length=10000)
    agreements: list[ArchiveAgreementImportRow] = Field(default_factory=list, max_length=10000)

    @field_validator("source_id")
    @classmethod
    def reject_blank_source_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("source_id must not be blank")
        return value

    @model_validator(mode="after")
    def require_task_source_identity(self):
        if self.tasks and self.source_id is None:
            raise ValueError("source_id is required when importing tasks")
        return self


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
