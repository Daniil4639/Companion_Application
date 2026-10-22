from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from backend.app.utils import RecurrenceFrequency


class RecurrenceRuleCreate(BaseModel):
    frequency: RecurrenceFrequency
    interval: int = Field(default=1, gt=0)

    by_weekday: list[str] | None = None
    by_monthday: list[int] | None = None
    by_month: list[int] | None = None

    until: datetime | None = None
    count: int | None = Field(default=None, gt=0)


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None

    start_at: datetime
    finish_at: datetime

    timezone: str = Field(min_length=1, max_length=64)

    recurrence_rule: RecurrenceRuleCreate | None = None


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None

    start_at: datetime
    finish_at: datetime

    timezone: str
    recurrence_rule_id: UUID | None