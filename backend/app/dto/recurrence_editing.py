from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.dto.events import RecurrenceRuleCreate
from backend.app.dto.calendar_editing import ScheduleDetails
from backend.app.dto.schedule import ScheduleOccurrenceResponse
from backend.app.utils.time import as_utc


class RecurrenceSpec(RecurrenceRuleCreate):
    """Existing recurrence vocabulary with strict numeric arguments for new tools."""

    interval: int = Field(default=1, gt=0, le=1000, strict=True)
    count: int | None = Field(default=None, gt=0, le=100000, strict=True)
    by_monthday: list[Annotated[int, Field(strict=True)]] | None = Field(default=None, min_length=1, max_length=62)
    by_month: list[Annotated[int, Field(ge=1, le=12, strict=True)]] | None = Field(default=None, min_length=1, max_length=12)


class RecurrenceChange(BaseModel):

    model_config = ConfigDict(extra="forbid")
    recurrence_rule: RecurrenceSpec
    start_at: datetime | None = None
    exception_policy: Literal["reject", "preserve", "discard"] = "reject"

    @field_validator("start_at")
    @classmethod
    def aware(cls, value):
        return None if value is None else as_utc(value)


class SeriesSplit(RecurrenceChange):

    original_start_at: datetime
    recurrence_rule: RecurrenceSpec | None = None

    @field_validator("original_start_at")
    @classmethod
    def original_aware(cls, value):
        return as_utc(value)


class RecurrenceResult(BaseModel):

    event_series_id: UUID
    outcome: Literal["recurrence_updated", "split", "restored"]
    series: list[ScheduleDetails]
    changed_fields: list[str]
    discarded_exception_ids: list[UUID] = Field(default_factory=list)
    transferred_exception_ids: list[UUID] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RecurrencePreview(BaseModel):

    event_series_id: UUID
    version: str
    range_start: datetime
    range_end: datetime
    before: list[ScheduleOccurrenceResponse]
    after: list[ScheduleOccurrenceResponse]
    proposed_events: list[ScheduleDetails]
    discarded_exception_ids: list[UUID]
    transferred_exception_ids: list[UUID]
    warnings: list[str]


class UserTimeContext(BaseModel):

    now_utc: datetime
    local_datetime: datetime
    local_date: date
    timezone: str
    timezone_mode: Literal["system", "manual"] | None
    timezone_source: Literal["saved_profile", "utc_fallback"]
    locale: str
    week_starts_on: Literal["MO"] = "MO"
    time_format: Literal["24h"] = "24h"
    warnings: list[str] = Field(default_factory=list)