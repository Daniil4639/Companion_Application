from datetime import datetime
from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db import get_db
from backend.app.dto.schedule import ScheduleResponse, ScheduleOccurrenceResponse
from backend.app.services import calendarService


schedule_router = APIRouter(prefix="/api/schedule", tags=["Schedule management"])


@schedule_router.get("", response_model=ScheduleResponse)
async def get_schedule(range_start: datetime = Query(...), range_end: datetime = Query(...),
                       session: AsyncSession = Depends(get_db)):
    occurrences = await calendarService.get_schedule(range_start, range_end, session)

    return ScheduleResponse(occurrences=[
        ScheduleOccurrenceResponse(**{name: getattr(item, name) for name in item.__dataclass_fields__})
        for item in occurrences])
