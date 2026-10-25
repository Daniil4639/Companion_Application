from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from backend.app.utils.time import as_utc
from backend.app.utils import EventExceptionStatus


class MoveOccurrenceRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    start_at: datetime
    finish_at: datetime

    @field_validator("start_at", "finish_at")
    @classmethod
    def aware_time(cls, value):
        return as_utc(value)

    @model_validator(mode="after")
    def positive_duration(self):
        if self.finish_at <= self.start_at:
            raise ValueError("finish_at must be greater than start_at")
        return self


class CancelOccurrenceResponse(BaseModel):

    status: str


class MoveOccurrenceResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_series_id: UUID
    original_start_at: datetime
    start_at: datetime | None
    finish_at: datetime | None
    status: EventExceptionStatus