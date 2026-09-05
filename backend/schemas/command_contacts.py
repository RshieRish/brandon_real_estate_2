"""Strict HTTP boundary models for the focused Command Contacts API."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)
from pydantic import (
    JsonValue as PydanticJsonValue,
)

from services.command_contact_contracts import (
    UNSET,
    CaptureQualityValue,
    ContactBulkCommand,
    ContactCreateCommand,
    ContactDirectoryFilters,
    ContactImportCommand,
    ContactImportRowCommand,
    ContactNoteCreateCommand,
    ContactOriginFilter,
    ContactSavedSearchCreateCommand,
    ContactSection,
    ContactSmartView,
    ContactSortKey,
    ContactSourceFilter,
    ContactUpdateCommand,
    JsonValue,
    SortDirection,
    UnsetType,
)
from services.command_contact_contracts import (
    ContactBulkAddTag as ContactBulkAddTagCommand,
)
from services.command_contact_contracts import (
    ContactBulkRemoveTag as ContactBulkRemoveTagCommand,
)
from services.command_contact_contracts import (
    ContactBulkSetStage as ContactBulkSetStageCommand,
)

PositiveInt = Annotated[StrictInt, Field(gt=0)]
DatabasePositiveInt = Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
BoundedPageSize = Annotated[StrictInt, Field(ge=1, le=100)]
_DATE_ONLY = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _date_only_input(value: object) -> object:
    if value is None or type(value) is date:
        return value
    if type(value) is str and _DATE_ONLY.fullmatch(value) is not None:
        return value
    raise ValueError("contact date must be an exact date")


def _canonical_query_integer(value: object) -> object:
    if type(value) is int:
        return value
    if (
        type(value) is str
        and value.isascii()
        and value.isdigit()
        and (value == "0" or not value.startswith("0"))
    ):
        return int(value)
    raise ValueError("query integer must be a canonical unsigned decimal")


class ContactBoundaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ContactDirectoryQueryIn(ContactBoundaryModel):
    query: str | None = Field(default=None, max_length=200)
    stage: str | None = Field(default=None, max_length=50)
    owner_actor_id: str | None = Field(default=None, max_length=255)
    assignee_actor_id: str | None = Field(default=None, max_length=255)
    tag: list[PositiveInt] = Field(default_factory=list)
    source: list[ContactSourceFilter] = Field(default_factory=list)
    origin: list[ContactOriginFilter] = Field(default_factory=list)
    health_min: StrictInt | None = Field(default=None, ge=0, le=100)
    health_max: StrictInt | None = Field(default=None, ge=0, le=100)
    birthday_month: StrictInt | None = Field(default=None, ge=1, le=12)
    anniversary_month: StrictInt | None = Field(default=None, ge=1, le=12)
    smart_view: ContactSmartView = ContactSmartView.ALL
    sort: ContactSortKey = ContactSortKey.NAME
    direction: SortDirection = SortDirection.ASC
    page: Annotated[StrictInt, Field(ge=1)] = 1
    page_size: BoundedPageSize = 50

    @field_validator(
        "health_min",
        "health_max",
        "birthday_month",
        "anniversary_month",
        "page",
        "page_size",
        mode="before",
    )
    @classmethod
    def _canonical_numeric_query_value(cls, value: object) -> object:
        if value is None:
            return None
        return _canonical_query_integer(value)

    @field_validator("tag", mode="before")
    @classmethod
    def _canonical_numeric_query_list(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            raise ValueError(  # noqa: TRY004 - Pydantic wraps ValueError only
                "tag must be a repeated query parameter"
            )
        return [_canonical_query_integer(item) for item in value]

    @model_validator(mode="after")
    def _valid_health_range(self) -> ContactDirectoryQueryIn:
        if (
            self.health_min is not None
            and self.health_max is not None
            and self.health_min > self.health_max
        ):
            raise ValueError("health_min must not exceed health_max")
        return self

    def to_filters(self) -> ContactDirectoryFilters:
        return ContactDirectoryFilters(
            query=self.query,
            stage=self.stage,
            owner_actor_id=self.owner_actor_id,
            assignee_actor_id=self.assignee_actor_id,
            tag_ids=tuple(self.tag),
            sources=tuple(self.source),
            origins=tuple(self.origin),
            health_min=self.health_min,
            health_max=self.health_max,
            birthday_month=self.birthday_month,
            anniversary_month=self.anniversary_month,
            smart_view=self.smart_view,
            sort=self.sort,
            direction=self.direction,
            page=self.page,
            page_size=self.page_size,
        )


class ContactTagOut(ContactBoundaryModel):
    id: PositiveInt
    name: str


class ContactActorOut(ContactBoundaryModel):
    role: Literal["owner", "assignee", "collaborator"]
    provider_actor_id: str | None
    display_name: str | None


class ContactCelebrationValueOut(ContactBoundaryModel):
    month: Annotated[StrictInt, Field(ge=1, le=12)]
    day: Annotated[StrictInt, Field(ge=1, le=31)]
    year: StrictInt | None
    year_quality: Literal["verified", "yearless", "sentinel", "unknown"]
    origin: Literal["internal_crm", "recovered"]


class ContactAddressOut(ContactBoundaryModel):
    id: PositiveInt
    address_type: str | None
    formatted: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    source_record_id: PositiveInt | None


class ContactDirectoryRowOut(ContactBoundaryModel):
    id: PositiveInt
    first_name: str
    last_name: str
    display_name: str
    primary_email: str | None
    primary_phone: str | None
    stage: str
    lead_backed: bool
    origins: list[ContactOriginFilter] = Field(default_factory=list)
    sources: list[ContactSourceFilter] = Field(default_factory=list)
    health_score: StrictInt | None = Field(default=None, ge=0, le=100)
    last_contacted_at: datetime | None
    last_interaction_at: datetime | None
    owner: ContactActorOut | None
    assignee: ContactActorOut | None
    tags: list[ContactTagOut] = Field(default_factory=list)
    birthday: ContactCelebrationValueOut | None
    anniversary: ContactCelebrationValueOut | None
    evidence_quality: Literal["complete", "partial", "limitation"] | None


class ContactDirectoryPageOut(ContactBoundaryModel):
    rows: list[ContactDirectoryRowOut] = Field(default_factory=list)
    total: NonnegativeInt
    page: Annotated[StrictInt, Field(ge=1)]
    page_size: BoundedPageSize
    page_count: NonnegativeInt
    sort: ContactSortKey
    direction: SortDirection


class ContactRecoveredProfileOut(ContactBoundaryModel):
    legal_name: str | None
    preferred_name: str | None
    description: str | None
    company: str | None
    title: str | None
    lead_source: str | None
    account_name: str | None
    birthday: ContactCelebrationValueOut | None
    anniversary: ContactCelebrationValueOut | None


class ContactDetailOut(ContactBoundaryModel):
    contact: ContactDirectoryRowOut
    lead_id: PositiveInt | None
    recovered_profile: ContactRecoveredProfileOut | None
    addresses: list[ContactAddressOut] = Field(default_factory=list)
    ownership: list[ContactActorOut] = Field(default_factory=list)
    tags: list[ContactTagOut] = Field(default_factory=list)


class ContactNeighborsOut(ContactBoundaryModel):
    previous_contact_id: PositiveInt | None
    next_contact_id: PositiveInt | None


class ContactWorkspaceCountsOut(ContactBoundaryModel):
    active_tasks: NonnegativeInt
    completed_tasks: NonnegativeInt
    cancelled_tasks: NonnegativeInt
    archived_tasks: NonnegativeInt
    active_smart_plans: NonnegativeInt
    opportunities: NonnegativeInt
    notes: NonnegativeInt
    saved_searches: NonnegativeInt
    bookings: NonnegativeInt


class ContactWorkspaceSummaryOut(ContactBoundaryModel):
    open_tasks: NonnegativeInt
    active_tasks: NonnegativeInt
    completed_tasks: NonnegativeInt
    cancelled_tasks: NonnegativeInt
    archived_tasks: NonnegativeInt
    archived_mutable_tasks: NonnegativeInt
    archived_recovered_evidence: NonnegativeInt
    active_smart_plans: NonnegativeInt
    opportunities: NonnegativeInt
    notes: NonnegativeInt
    saved_searches: NonnegativeInt
    bookings: NonnegativeInt
    internal_counts: ContactWorkspaceCountsOut | None = None
    recovered_counts: ContactWorkspaceCountsOut | None = None

    @model_validator(mode="after")
    def _consistent_task_totals(self) -> ContactWorkspaceSummaryOut:
        if self.open_tasks != self.active_tasks:
            raise ValueError("open task total must equal active task total")
        if self.archived_tasks != (
            self.archived_mutable_tasks + self.archived_recovered_evidence
        ):
            raise ValueError("archived task total must equal its subtotals")
        if (self.internal_counts is None) != (self.recovered_counts is None):
            raise ValueError("workspace count breakdown must include both origins")
        if self.internal_counts is not None and self.recovered_counts is not None:
            for key in ContactWorkspaceCountsOut.model_fields:
                if getattr(self, key) != (
                    getattr(self.internal_counts, key) + getattr(self.recovered_counts, key)
                ):
                    raise ValueError("workspace total must equal its origin subtotals")
        return self


class ContactOpportunityOccurrenceOut(ContactBoundaryModel):
    kind: Literal["opportunity"]
    title: str
    stage: str | None
    value_cents: NonnegativeInt | None
    budget: str | None = Field(default=None, max_length=120)


class ContactSmartPlanOccurrenceOut(ContactBoundaryModel):
    kind: Literal["smart_plan"]
    title: str
    status: str | None


class ContactTaskOccurrenceOut(ContactBoundaryModel):
    kind: Literal["task"]
    title: str
    description: str | None
    state: Literal["to_do", "completed", "archived"]
    due_at: datetime | None
    due_date: str | None = None
    due_date_text: str | None = Field(default=None, max_length=120)

    @field_validator("due_date")
    @classmethod
    def _exact_due_date(cls, value: str | None) -> str | None:
        if value is not None:
            if _DATE_ONLY.fullmatch(value) is None:
                raise ValueError("task due date must be a calendar date")
            date.fromisoformat(value)
        return value


class ContactNoteOccurrenceOut(ContactBoundaryModel):
    kind: Literal["note"]
    title: str
    body: str | None


class ContactSavedSearchOccurrenceOut(ContactBoundaryModel):
    kind: Literal["saved_search"]
    title: str
    criteria_summary: list[str] = Field(default_factory=list)


ContactOccurrenceOut = Annotated[
    ContactOpportunityOccurrenceOut
    | ContactSmartPlanOccurrenceOut
    | ContactTaskOccurrenceOut
    | ContactNoteOccurrenceOut
    | ContactSavedSearchOccurrenceOut,
    Field(discriminator="kind"),
]


class ContactSourceOnlyOut(ContactBoundaryModel):
    status: Literal["source_only"]
    source_record_id: PositiveInt
    source_key_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    section: ContactSection
    occurrence_ordinal: PositiveInt
    capture_quality: CaptureQualityValue
    captured_at: datetime | None
    value: ContactOccurrenceOut


class ContactMaterializedOut(ContactBoundaryModel):
    status: Literal["materialized"]
    source_record_id: PositiveInt
    source_key_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    section: ContactSection
    occurrence_ordinal: PositiveInt
    capture_quality: CaptureQualityValue
    captured_at: datetime | None
    value: ContactOccurrenceOut
    entity_type: Literal["note", "saved_search", "task", "smart_plan", "opportunity"]
    entity_id: PositiveInt


ContactSectionRowOut = Annotated[
    ContactSourceOnlyOut | ContactMaterializedOut,
    Field(discriminator="status"),
]


class ContactSectionPageOut(ContactBoundaryModel):
    rows: list[ContactSectionRowOut] = Field(default_factory=list)
    total: NonnegativeInt
    page: Annotated[StrictInt, Field(ge=1)]
    page_size: BoundedPageSize
    page_count: NonnegativeInt


class ContactTimelineEntryOut(ContactBoundaryModel):
    key: str
    origin: Literal["recovered", "internal_crm", "legacy_lead", "booking"]
    kind: str
    title: str
    body: str | None
    outcome: str | None
    occurred_at: datetime | None
    source_record_id: PositiveInt | None
    entity_type: str
    entity_id: PositiveInt
    captured_date: date | None = None
    captured_time: str | None = None


class ContactTimelinePageOut(ContactBoundaryModel):
    rows: list[ContactTimelineEntryOut] = Field(default_factory=list)
    next_cursor: str | None
    has_more: bool
    filtered_capture_count: NonnegativeInt = 0


class ContactArtifactMetadataOut(ContactBoundaryModel):
    artifact_id: PositiveInt
    artifact_type: str = Field(min_length=1, max_length=64)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: NonnegativeInt
    content_href: str

    @model_validator(mode="after")
    def _exact_content_href(self) -> ContactArtifactMetadataOut:
        expected = f"/api/v1/command/archive/artifacts/{self.artifact_id}/content"
        if self.content_href != expected:
            raise ValueError("artifact content href is invalid")
        return self


class ContactSourceMetadataOut(ContactBoundaryModel):
    source_record_id: PositiveInt
    record_kind: str = Field(min_length=1, max_length=64)
    evidence_level: Literal[
        "observed_record", "rendered_occurrence", "displayed_aggregate"
    ]
    capture_quality: CaptureQualityValue
    captured_at: datetime | None
    artifacts: list[ContactArtifactMetadataOut] = Field(default_factory=list)


class ContactSectionEvidenceOut(ContactBoundaryModel):
    capture_position_id: PositiveInt
    section: ContactSection
    source_record_id: PositiveInt
    capture_quality: CaptureQualityValue
    row_count: NonnegativeInt
    is_empty: bool
    limitation_codes: list[str] = Field(default_factory=list)


class ContactCapturePositionOut(ContactBoundaryModel):
    capture_position_id: PositiveInt
    capture_ordinal: PositiveInt
    source_record_id: PositiveInt
    capture_quality: CaptureQualityValue
    sections: list[ContactSectionEvidenceOut] = Field(default_factory=list)


class ContactEvidenceOut(ContactBoundaryModel):
    contact_id: PositiveInt
    provider_contact_rows: NonnegativeInt
    resolved_provider_identities: NonnegativeInt
    coalesced_aliases: Literal[0]
    lead_backed_contacts: NonnegativeInt
    reviewed_overlaps: NonnegativeInt
    legacy_only_contacts: NonnegativeInt
    capture_positions: list[ContactCapturePositionOut] = Field(default_factory=list)
    section_matrix: list[ContactSectionEvidenceOut] = Field(default_factory=list)
    sources: list[ContactSourceMetadataOut] = Field(default_factory=list)
    capture_quality: Literal["complete", "partial", "limitation"]

    @field_validator("coalesced_aliases", mode="before")
    @classmethod
    def _exact_zero_aliases(cls, value: object) -> object:
        if type(value) is not int or value != 0:
            raise ValueError("coalesced_aliases must be exact integer zero")
        return value


class ContactCelebrationRowOut(ContactBoundaryModel):
    contact_id: PositiveInt
    display_name: str
    kind: Literal["birthday", "anniversary"]
    month: Annotated[StrictInt, Field(ge=1, le=12)]
    day: Annotated[StrictInt, Field(ge=1, le=31)]
    year: StrictInt | None
    year_quality: Literal["verified", "yearless", "sentinel", "unknown"]
    origin: Literal["internal_crm", "recovered"]


class ContactCelebrationsOut(ContactBoundaryModel):
    birthdays: list[ContactCelebrationRowOut] = Field(default_factory=list)
    anniversaries: list[ContactCelebrationRowOut] = Field(default_factory=list)


class _ContactCreateFields(ContactBoundaryModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(default="", max_length=120)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    stage: str = Field(default="lead", min_length=1, max_length=50)
    birthday: date | None = None
    anniversary: date | None = None

    @field_validator("birthday", "anniversary", mode="before")
    @classmethod
    def _exact_date_or_null(cls, value: object) -> object:
        return _date_only_input(value)


class ContactCreateIn(_ContactCreateFields):
    def to_command(self) -> ContactCreateCommand:
        return ContactCreateCommand(**self.model_dump())


class ContactUpdateIn(ContactBoundaryModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    stage: str | None = Field(default=None, min_length=1, max_length=50)
    birthday: date | None = None
    anniversary: date | None = None

    @field_validator("birthday", "anniversary", mode="before")
    @classmethod
    def _exact_date_or_null(cls, value: object) -> object:
        return _date_only_input(value)

    @model_validator(mode="after")
    def _at_least_one_nonnullable_shape(self) -> ContactUpdateIn:
        if not self.model_fields_set:
            raise ValueError("contact update must contain at least one field")
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in ("first_name", "last_name", "stage")
        ):
            raise ValueError("required contact fields cannot be null")
        return self

    def to_command(self) -> ContactUpdateCommand:
        return ContactUpdateCommand(
            first_name=self._required_text_update("first_name", self.first_name),
            last_name=self._required_text_update("last_name", self.last_name),
            email=self.email if "email" in self.model_fields_set else UNSET,
            phone=self.phone if "phone" in self.model_fields_set else UNSET,
            stage=self._required_text_update("stage", self.stage),
            birthday=(self.birthday if "birthday" in self.model_fields_set else UNSET),
            anniversary=(
                self.anniversary if "anniversary" in self.model_fields_set else UNSET
            ),
        )

    def _required_text_update(
        self, field_name: str, value: str | None
    ) -> str | UnsetType:
        if field_name not in self.model_fields_set:
            return UNSET
        if value is None:
            raise ValueError("required contact fields cannot be null")
        return value


class ContactBulkSetStage(ContactBoundaryModel):
    action: Literal["set_stage"]
    stage: str = Field(min_length=1, max_length=50)


class ContactBulkAddTag(ContactBoundaryModel):
    action: Literal["add_tag"]
    tag_id: PositiveInt


class ContactBulkRemoveTag(ContactBoundaryModel):
    action: Literal["remove_tag"]
    tag_id: PositiveInt


ContactBulkActionIn = Annotated[
    ContactBulkSetStage | ContactBulkAddTag | ContactBulkRemoveTag,
    Field(discriminator="action"),
]


class ContactBulkRequest(ContactBoundaryModel):
    contact_ids: list[PositiveInt] = Field(min_length=1, max_length=200)
    action: ContactBulkActionIn

    @field_validator("contact_ids")
    @classmethod
    def _unique_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("contact_ids must be unique")
        return value

    def to_command(self) -> ContactBulkCommand:
        if isinstance(self.action, ContactBulkSetStage):
            return ContactBulkCommand(
                contact_ids=tuple(self.contact_ids),
                action=ContactBulkSetStageCommand(
                    action=self.action.action, stage=self.action.stage
                ),
            )
        if isinstance(self.action, ContactBulkAddTag):
            return ContactBulkCommand(
                contact_ids=tuple(self.contact_ids),
                action=ContactBulkAddTagCommand(
                    action=self.action.action, tag_id=self.action.tag_id
                ),
            )
        return ContactBulkCommand(
            contact_ids=tuple(self.contact_ids),
            action=ContactBulkRemoveTagCommand(
                action=self.action.action, tag_id=self.action.tag_id
            ),
        )


class ContactBulkResultOut(ContactBoundaryModel):
    requested_contact_ids: list[PositiveInt]
    actioned_contact_ids: list[PositiveInt]
    action: Literal["set_stage", "add_tag", "remove_tag"]


class ContactNoteCreateIn(ContactBoundaryModel):
    body: str = Field(min_length=1, max_length=20_000)

    def to_command(self) -> ContactNoteCreateCommand:
        return ContactNoteCreateCommand(body=self.body)


def _freeze_json(value: object) -> JsonValue:
    if value is None or type(value) in {bool, int, str}:
        return value  # type: ignore[return-value]
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON floats must be finite")
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("JSON object keys must be strings")
        return {key: _freeze_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise TypeError("value is not canonical JSON")


def _thaw_json(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def canonical_saved_search_criteria(value: Mapping[str, JsonValue]) -> str:
    return json.dumps(
        _thaw_json(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class ContactSavedSearchCreateIn(ContactBoundaryModel):
    name: str = Field(min_length=1, max_length=255)
    criteria: dict[str, PydanticJsonValue] = Field(default_factory=dict)

    @field_validator("criteria", mode="before")
    @classmethod
    def _canonical_criteria(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            raise ValueError(  # noqa: TRY004 - Pydantic wraps ValueError only
                "criteria must be an object"
            )
        return _freeze_json(value)

    @model_validator(mode="after")
    def _validate_service_command(self) -> ContactSavedSearchCreateIn:
        ContactSavedSearchCreateCommand(
            name=self.name, criteria=self._service_criteria()
        )
        return self

    def to_command(self) -> ContactSavedSearchCreateCommand:
        return ContactSavedSearchCreateCommand(
            name=self.name, criteria=self._service_criteria()
        )

    def _service_criteria(self) -> Mapping[str, JsonValue]:
        frozen = _freeze_json(self.criteria)
        if not isinstance(frozen, Mapping):
            raise TypeError("criteria must be an object")
        return frozen


class ContactImportRowIn(_ContactCreateFields):
    def to_command(self) -> ContactImportRowCommand:
        return ContactImportRowCommand(**self.model_dump())


class ContactImportIn(ContactBoundaryModel):
    contacts: list[ContactImportRowIn] = Field(min_length=1, max_length=1_000)

    def to_command(self) -> ContactImportCommand:
        return ContactImportCommand(
            contacts=tuple(row.to_command() for row in self.contacts)
        )


class LegacyContactOut(ContactBoundaryModel):
    id: PositiveInt
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    lead_id: PositiveInt | None
    birthday: date | None
    anniversary: date | None
    stage: str


class ContactTagAssignmentOut(ContactBoundaryModel):
    contact_id: PositiveInt
    tag_id: PositiveInt


class ContactTagRemovalOut(ContactTagAssignmentOut):
    removed: bool


class ContactNoteCreatedOut(ContactBoundaryModel):
    id: PositiveInt
    body: str


class ContactDeletedOut(ContactBoundaryModel):
    deleted: Literal[True]
    id: PositiveInt


class ContactSavedSearchCreatedOut(ContactBoundaryModel):
    id: PositiveInt
    name: str
    criteria: str


class ContactLegacySyncResultOut(ContactBoundaryModel):
    created: NonnegativeInt
    timeline_backfilled: NonnegativeInt
    total_legacy_leads: NonnegativeInt


class ContactImportResultOut(ContactBoundaryModel):
    created: NonnegativeInt
    skipped_duplicates: NonnegativeInt


class SavedSearchOut(ContactBoundaryModel):
    id: PositiveInt
    name: str
    criteria: str
    contact_id: PositiveInt | None
    contact_name: str | None
    updated_at: datetime


class LegacyTimelineOut(ContactBoundaryModel):
    id: PositiveInt
    kind: str
    summary: str
    created_at: datetime


class LegacyTaskOut(ContactBoundaryModel):
    id: PositiveInt
    title: str
    contact_id: PositiveInt | None
    description: str
    priority: str
    due_at: datetime | None
    status: Literal["open", "in_progress", "completed", "cancelled"]
    archived_at: datetime | None
    archive_reason: str | None = Field(max_length=500)
    version: DatabasePositiveInt


class LegacyNoteOut(ContactBoundaryModel):
    id: PositiveInt
    contact_id: PositiveInt
    body: str
    created_at: datetime
    updated_at: datetime


class LegacySmartPlanOut(ContactBoundaryModel):
    id: PositiveInt
    plan_id: PositiveInt
    plan_name: str | None = None
    status: str


class LegacyOpportunityOut(ContactBoundaryModel):
    id: PositiveInt
    name: str
    stage: str
    value_cents: int | None
    role: str


class LegacySavedSearchOut(ContactBoundaryModel):
    id: PositiveInt
    name: str
    criteria: str
    criteria_summary: list[str] = Field(default_factory=list)


class LegacyBookingOut(ContactBoundaryModel):
    id: PositiveInt
    meeting_type: str
    context: str
    scheduled_at: datetime
    location: str | None
    notes: str


class LegacyContactWorkspaceOut(ContactBoundaryModel):
    contact: LegacyContactOut
    timeline: list[LegacyTimelineOut] = Field(default_factory=list)
    tasks: list[LegacyTaskOut] = Field(default_factory=list)
    notes: list[LegacyNoteOut] = Field(default_factory=list)
    smart_plans: list[LegacySmartPlanOut] = Field(default_factory=list)
    opportunities: list[LegacyOpportunityOut] = Field(default_factory=list)
    saved_searches: list[LegacySavedSearchOut] = Field(default_factory=list)
    bookings: list[LegacyBookingOut] = Field(default_factory=list)
    tags: list[ContactTagOut] = Field(default_factory=list)


__all__ = [
    "ContactActorOut",
    "ContactAddressOut",
    "ContactArtifactMetadataOut",
    "ContactBoundaryModel",
    "ContactBulkActionIn",
    "ContactBulkAddTag",
    "ContactBulkRemoveTag",
    "ContactBulkRequest",
    "ContactBulkResultOut",
    "ContactBulkSetStage",
    "ContactCapturePositionOut",
    "ContactCelebrationRowOut",
    "ContactCelebrationValueOut",
    "ContactCelebrationsOut",
    "ContactCreateIn",
    "ContactDeletedOut",
    "ContactDetailOut",
    "ContactDirectoryPageOut",
    "ContactDirectoryQueryIn",
    "ContactDirectoryRowOut",
    "ContactEvidenceOut",
    "ContactImportIn",
    "ContactImportResultOut",
    "ContactImportRowIn",
    "ContactLegacySyncResultOut",
    "ContactMaterializedOut",
    "ContactNeighborsOut",
    "ContactNoteCreateIn",
    "ContactNoteCreatedOut",
    "ContactNoteOccurrenceOut",
    "ContactOccurrenceOut",
    "ContactOpportunityOccurrenceOut",
    "ContactRecoveredProfileOut",
    "ContactSavedSearchCreateIn",
    "ContactSavedSearchCreatedOut",
    "ContactSavedSearchOccurrenceOut",
    "ContactSectionEvidenceOut",
    "ContactSectionPageOut",
    "ContactSectionRowOut",
    "ContactSmartPlanOccurrenceOut",
    "ContactSourceMetadataOut",
    "ContactSourceOnlyOut",
    "ContactTagAssignmentOut",
    "ContactTagOut",
    "ContactTagRemovalOut",
    "ContactTaskOccurrenceOut",
    "ContactTimelineEntryOut",
    "ContactTimelinePageOut",
    "ContactWorkspaceCountsOut",
    "ContactUpdateIn",
    "ContactWorkspaceSummaryOut",
    "LegacyBookingOut",
    "LegacyContactOut",
    "LegacyContactWorkspaceOut",
    "LegacyNoteOut",
    "LegacyOpportunityOut",
    "LegacySavedSearchOut",
    "LegacySmartPlanOut",
    "LegacyTaskOut",
    "LegacyTimelineOut",
    "SavedSearchOut",
    "canonical_saved_search_criteria",
]
