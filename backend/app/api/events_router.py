from uuid import UUID
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.dto.events import EventCreate, EventUpdate, EventResponse
from backend.app.db import get_db
from backend.app.db.session import write_transaction
from backend.app.services import calendarService


events_router = APIRouter(prefix="/api/events", tags=["Events management"])


@events_router.post("", response_model=EventResponse, status_code=201)
async def create_event(data: EventCreate, session: AsyncSession = Depends(get_db)):
    async with write_transaction(session):
        event = await calendarService.create_event(**{**data.model_dump(), "recurrence_rule": data.recurrence_rule}, session=session)
        response = EventResponse.model_validate(event)

    return response


@events_router.get("", response_model=list[EventResponse])
async def list_events(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                      session: AsyncSession = Depends(get_db)):
    return await calendarService.list_events(session, limit, offset)


@events_router.get("/{event_series_id}", response_model=EventResponse)
async def get_event(event_series_id: UUID, session: AsyncSession = Depends(get_db)):
    return await calendarService.get_event_series(event_series_id, session)


@events_router.patch("/{event_series_id}", response_model=EventResponse)
async def update_event(event_series_id: UUID, data: EventUpdate, reset_exceptions: bool = False,
                       session: AsyncSession = Depends(get_db)):
    async with write_transaction(session):
        event = await calendarService.update_event(event_series_id, data.model_dump(exclude_unset=True),
                                                    session, reset_exceptions)
        response = EventResponse.model_validate(event)

    return response


@events_router.delete("/{event_series_id}", status_code=204)
async def delete_event(event_series_id: UUID, session: AsyncSession = Depends(get_db)):
    async with write_transaction(session):
        await calendarService.delete_event(event_series_id, session)

    return Response(status_code=204)