from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db import get_db
from backend.app.db.session import write_transaction
from backend.app.dto.occurence import MoveOccurrenceRequest, MoveOccurrenceResponse, CancelOccurrenceResponse
from backend.app.services import calendarService


occurrence_router = APIRouter(prefix="/api/events/{event_series_id}/occurrences", tags=["Occurrences management"])


@occurrence_router.post("/{original_start_at}/move", response_model=MoveOccurrenceResponse)
async def move_occurrence(event_series_id: UUID, original_start_at: datetime, data: MoveOccurrenceRequest,
                          session: AsyncSession = Depends(get_db)):
    async with write_transaction(session):
        exception = await calendarService.move_occurrence(event_series_id, original_start_at,
                                                           data.start_at, data.finish_at, session)
        response = MoveOccurrenceResponse.model_validate(exception)

    return response


@occurrence_router.post("/{original_start_at}/cancel", response_model=CancelOccurrenceResponse)
async def cancel_occurrence(event_series_id: UUID, original_start_at: datetime, session: AsyncSession = Depends(get_db)):
    async with write_transaction(session):
        exception = await calendarService.cancel_occurrence(event_series_id, original_start_at, session)
        response = CancelOccurrenceResponse(status=exception.status.value)

    return response


@occurrence_router.post("/{original_start_at}/restore", status_code=204)
async def restore_occurrence(event_series_id: UUID, original_start_at: datetime, session: AsyncSession = Depends(get_db)):
    async with write_transaction(session):
        await calendarService.restore_occurrence(event_series_id, original_start_at, session)

    return Response(status_code=204)
