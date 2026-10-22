from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status
from backend.app.db import get_db
from backend.app.dto.occurence import MoveOccurrenceRequest, CancelOccurrenceResponse
from backend.app.services import calendarService


occurrence_router = APIRouter(
    prefix="/api/events/{event_series_id}/occurrences",
    tags=["Occurrences management"]
)


@occurrence_router.post("/{original_start_at}/move", status_code=status.HTTP_200_OK)
async def move_occurrence(
    event_series_id: UUID,
    original_start_at: datetime,
    data: MoveOccurrenceRequest,
    session: AsyncSession = Depends(get_db)
):
    if data.finish_at <= data.start_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="finish_at must be greater than start_at"
        )

    try:
        exception = await calendarService.move_occurrence(
            event_series_id=event_series_id,
            original_start_at=original_start_at,
            new_start_at=data.start_at,
            new_finish_at=data.finish_at,
            session=session
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc

    await session.commit()

    return {
        "id": exception.id,
        "event_series_id": exception.event_series_id,
        "original_start_at": exception.original_start_at,
        "start_at": exception.start_at,
        "finish_at": exception.finish_at,
        "status": exception.status
    }


@occurrence_router.post("/{original_start_at}/cancel", response_model=CancelOccurrenceResponse)
async def cancel_occurrence(
    event_series_id: UUID,
    original_start_at: datetime,
    session: AsyncSession = Depends(get_db)
):
    try:
        exception = await calendarService.cancel_occurrence(
            event_series_id=event_series_id,
            original_start_at=original_start_at,
            session=session
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc

    await session.commit()

    return CancelOccurrenceResponse(
        status=exception.status.value
    )