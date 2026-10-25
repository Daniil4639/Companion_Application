from datetime import datetime
from uuid import UUID
from backend.app.utils.event_category import EventCategory
from pydantic import BaseModel


class ScheduleOccurrenceResponse(BaseModel):

    event_series_id: UUID
    original_start_at: datetime
    start_at: datetime
    finish_at: datetime
    title: str
    description: str | None
    category: EventCategory = EventCategory.DEFAULT


class ScheduleResponse(BaseModel):

    occurrences: list[ScheduleOccurrenceResponse]