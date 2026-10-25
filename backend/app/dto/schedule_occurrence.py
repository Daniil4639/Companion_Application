from datetime import datetime
from dataclasses import dataclass
from uuid import UUID
from backend.app.utils.event_category import EventCategory


@dataclass(slots=True)
class ScheduleOccurrence:

    event_series_id: UUID
    original_start_at: datetime
    start_at: datetime
    finish_at: datetime
    title: str
    description: str | None
    category: EventCategory = EventCategory.DEFAULT