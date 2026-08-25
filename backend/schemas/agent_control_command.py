"""Strict Command-only contact contracts for the private agent bridge."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

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
    page: PositiveInt = 1
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
    page: PositiveInt
    page_size: Annotated[StrictInt, Field(ge=1, le=25)]
    page_count: Annotated[StrictInt, Field(ge=0)]


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


__all__ = [name for name in globals() if name.startswith("CommandContact")]
