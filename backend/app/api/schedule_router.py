from datetime import datetime
from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db import get_db
from backend.app.dto.schedule import ScheduleResponse, ScheduleOccurrenceResponse
from backend.app.services import calendarService


schedule_router = APIRouter(prefix="/api/schedule",tags=["Schedule management"])


@schedule_router.get("", response_model=ScheduleResponse)
async def get_schedule(
    range_start: datetime = Query(...),
    range_end: datetime = Query(...),
    session: AsyncSession = Depends(get_db)
):

    if range_end <= range_start:
        raise ValueError("range_end must be greater than range_start")

    occurrences = await calendarService.get_schedule(
        range_start=range_start,
        range_end=range_end,
        session=session
    )

    return ScheduleResponse(
        occurrences=[
            ScheduleOccurrenceResponse(
                event_series_id=occurrence.event_series_id,
                original_start_at=occurrence.original_start_at,
                start_at=occurrence.start_at,
                finish_at=occurrence.finish_at,
                title=occurrence.title,
                description=occurrence.description
            )
            for occurrence in occurrences
        ]
    )