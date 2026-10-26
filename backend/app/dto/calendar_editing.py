from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from backend.app.dto.events import EventResponse
from backend.app.utils import EventExceptionStatus
from backend.app.utils.time import as_utc, zone


Version = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
AwareTime = Annotated[datetime, Field(description="ISO 8601 datetime with explicit UTC offset")]


class OccurrenceEdit(BaseModel):

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    start_at: AwareTime | None = None
    finish_at: AwareTime | None = None

    @field_validator("start_at", "finish_at")
    @classmethod
    def aware(cls, value):
        return None if value is None else as_utc(value)

    @model_validator(mode="after")
    def supplied_fields(self):
        if not self.model_fields_set:
            raise ValueError("At least one changed field is required")
        for key in self.model_fields_set - {"description"}:
            if getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class EventEdit(OccurrenceEdit):

    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        if value is not None:
            zone(value)
        return value


class ExceptionDetails(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    original_start_at: datetime
    status: EventExceptionStatus
    start_at: datetime | None
    finish_at: datetime | None
    title: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class EventDetails(EventResponse):

    created_at: datetime
    updated_at: datetime
    exceptions: list[ExceptionDetails]


class ScheduleDetails(BaseModel):

    event: EventDetails
    version: Version


class ScheduleEditResult(BaseModel):

    event_series_id: UUID
    original_start_at: datetime | None = None
    outcome: Literal["updated", "deleted", "cancelled"]
    changed_fields: list[str]
    warnings: list[str] = Field(default_factory=list)
    version: Version | None = None
    event: EventDetails | None = None