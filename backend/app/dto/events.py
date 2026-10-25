from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from backend.app.utils import RecurrenceFrequency
from backend.app.utils.time import as_utc, zone
from backend.app.utils.event_category import EventCategory


Weekday = Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
Month = Annotated[int, Field(ge=1, le=12)]


class RecurrenceRuleCreate(BaseModel):

    model_config = ConfigDict(from_attributes=True, extra="forbid")
    frequency: RecurrenceFrequency
    interval: int = Field(default=1, gt=0, le=1000)
    by_weekday: list[Weekday] | None = Field(default=None, min_length=1, max_length=7)
    by_monthday: list[int] | None = Field(default=None, min_length=1, max_length=62)
    by_month: list[Month] | None = Field(default=None, min_length=1, max_length=12)
    until: datetime | None = None
    count: int | None = Field(default=None, gt=0, le=100000)

    @field_validator("by_monthday")
    @classmethod
    def valid_monthdays(cls, value):
        if value is not None and any(day == 0 or not -31 <= day <= 31 for day in value):
            raise ValueError("Month days must be -31..-1 or 1..31")
        return value

    @field_validator("until")
    @classmethod
    def aware_until(cls, value):
        return None if value is None else as_utc(value)

    @model_validator(mode="after")
    def valid_end(self):
        if self.count is not None and self.until is not None:
            raise ValueError("count and until are mutually exclusive")
        return self


class EventCreate(BaseModel):

    category: EventCategory = EventCategory.DEFAULT
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    start_at: datetime
    finish_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    recurrence_rule: RecurrenceRuleCreate | None = None

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Title must not be blank")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        zone(value)
        return value

    @field_validator("start_at", "finish_at")
    @classmethod
    def aware_time(cls, value):
        return as_utc(value)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.finish_at <= self.start_at:
            raise ValueError("finish_at must be greater than start_at")
        if self.recurrence_rule and self.recurrence_rule.until is not None:
            if self.recurrence_rule.until < self.start_at:
                raise ValueError("until must not be before start_at")
        return self


class EventUpdate(BaseModel):

    category: EventCategory | None = None
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    description: str | None = None
    start_at: datetime | None = None
    finish_at: datetime | None = None
    timezone: str | None = None
    recurrence_rule: RecurrenceRuleCreate | None = None

    @model_validator(mode="after")
    def required_fields_cannot_be_null(self):
        for key in ("title", "start_at", "finish_at", "timezone", "category"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} must not be null")
        return self


class EventResponse(BaseModel):

    category: EventCategory
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    description: str | None
    start_at: datetime
    finish_at: datetime
    timezone: str
    recurrence_rule_id: UUID | None
    recurrence_rule: RecurrenceRuleCreate | None