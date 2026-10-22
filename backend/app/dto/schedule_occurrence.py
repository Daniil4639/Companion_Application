from datetime import datetime
from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class ScheduleOccurrence:
    event_series_id: UUID
    original_start_at: datetime

    start_at: datetime
    finish_at: datetime

    title: str
    description: str | None