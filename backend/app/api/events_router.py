from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status
from backend.app.dto.events import EventResponse, EventCreate
from backend.app.db import get_db
from backend.app.models import RecurrenceRule
from backend.app.services import calendarService


events_router = APIRouter(prefix="/api/events", tags=["Events management"])


@events_router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    data: EventCreate,
    session: AsyncSession = Depends(get_db)
):
    recurrence_rule = None

    if data.recurrence_rule is not None:
        recurrence_rule = RecurrenceRule(
            frequency=data.recurrence_rule.frequency,
            interval=data.recurrence_rule.interval,
            by_weekday=data.recurrence_rule.by_weekday,
            by_monthday=data.recurrence_rule.by_monthday,
            by_month=data.recurrence_rule.by_month,
            until=data.recurrence_rule.until,
            count=data.recurrence_rule.count
        )

    event = await calendarService.create_event(
        title=data.title,
        description=data.description,
        start_at=data.start_at,
        finish_at=data.finish_at,
        timezone=data.timezone,
        recurrence_rule=recurrence_rule,
        session=session
    )

    await session.commit()
    await session.refresh(event)

    return event


@events_router.get("/{event_series_id}", response_model=EventResponse)
async def get_event(
    event_series_id: UUID,
    session: AsyncSession = Depends(get_db)
):

    try:
        event = await calendarService.get_event_series(
            event_series_id=event_series_id,
            session=session
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc

    return event