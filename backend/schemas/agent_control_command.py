"""Strict Command-only contact contracts for the private agent bridge."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from services.command_contact_contracts import (
    ContactOriginFilter,
    ContactSourceFilter,
)

PositiveInt = Annotated[StrictInt, Field(gt=0)]


class StrictCommandModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CommandContactFilters(StrictCommandModel):
    query: str | None = Field(default=None, min_length=1, max_length=200)
    stage: str | None = Field(default=None, min_length=1, max_length=50)
    tag_ids: list[PositiveInt] = Field(default_factory=list, max_length=50)
    sources: list[ContactSourceFilter] = Field(default_factory=list, max_length=3)
    origins: list[ContactOriginFilter] = Field(default_factory=list, max_length=4)

    @field_validator("tag_ids")
    @classmethod
    def normalize_tag_ids(cls, values: list[int]) -> list[int]:
        return sorted(set(values))

    @field_validator("sources", "origins")
    @classmethod
    def normalize_enums(cls, values: list) -> list:
        return sorted(set(values), key=lambda value: value.value)


class CommandContactsSearchRequest(CommandContactFilters):
    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: Annotated[StrictInt, Field(ge=1, le=25)] = 25


class CommandContactResult(StrictCommandModel):
    contact_id: PositiveInt
    display_name: str
    primary_email: str | None
    primary_phone: str | None
    stage: str
    sources: list[ContactSourceFilter]
    origins: list[ContactOriginFilter]
    tag_names: list[str]


class CommandContactsSearchResponse(StrictCommandModel):
    contacts: list[CommandContactResult]
    total: Annotated[StrictInt, Field(ge=0)]
    page_size: Annotated[StrictInt, Field(ge=1, le=25)]
    next_cursor: str | None = Field(default=None, max_length=512)
    has_more: bool


class CommandContactAudiencePreviewRequest(CommandContactFilters):
    pass


class CommandContactAudienceSample(StrictCommandModel):
    display_name: str
    primary_email: str | None
    primary_phone: str | None


class CommandContactAudiencePreviewResponse(StrictCommandModel):
    audience_ref: UUID
    audience_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_count: Annotated[StrictInt, Field(ge=0)]
    samples: list[CommandContactAudienceSample] = Field(max_length=5)


class CommandContactCelebrationsPreviewRequest(StrictCommandModel):
    month: Annotated[StrictInt, Field(ge=1, le=12)]
    include_birthdays: StrictBool = True
    include_home_anniversaries: StrictBool = True

    @model_validator(mode="after")
    def require_selected_kind(self) -> Self:
        if not self.include_birthdays and not self.include_home_anniversaries:
            raise ValueError("at least one celebration kind must be selected")
        return self


class CommandContactCelebrationOccurrence(StrictCommandModel):
    kind: Literal["birthday", "home_anniversary"]
    day: Annotated[StrictInt, Field(ge=1, le=31)]


class CommandContactCelebrationSample(StrictCommandModel):
    display_name: str
    celebrations: list[CommandContactCelebrationOccurrence] = Field(
        min_length=1,
        max_length=2,
    )
    address_ready: StrictBool


class CommandContactCelebrationsPreviewResponse(StrictCommandModel):
    month: Annotated[StrictInt, Field(ge=1, le=12)]
    include_birthdays: StrictBool
    include_home_anniversaries: StrictBool
    audience_ref: UUID
    audience_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    birthday_count: Annotated[StrictInt, Field(ge=0)]
    home_anniversary_count: Annotated[StrictInt, Field(ge=0)]
    union_count: Annotated[StrictInt, Field(ge=0)]
    address_ready_count: Annotated[StrictInt, Field(ge=0)]
    missing_address_count: Annotated[StrictInt, Field(ge=0)]
    reconciliation_status: Literal[
        "not_reconciled",
        "incomplete",
        "reconciled",
    ]
    samples: list[CommandContactCelebrationSample] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_exact_totals(self) -> Self:
        if not self.include_birthdays and self.birthday_count != 0:
            raise ValueError("excluded birthday count must be zero")
        if not self.include_home_anniversaries and self.home_anniversary_count != 0:
            raise ValueError("excluded home anniversary count must be zero")
        if not (
            max(self.birthday_count, self.home_anniversary_count)
            <= self.union_count
            <= self.birthday_count + self.home_anniversary_count
        ):
            raise ValueError("celebration union count is inconsistent")
        if self.address_ready_count + self.missing_address_count != self.union_count:
            raise ValueError("address readiness counts must equal the union count")
        if len(self.samples) > self.union_count:
            raise ValueError("samples must not exceed the union count")
        return self


__all__ = [name for name in globals() if name.startswith("CommandContact")]
