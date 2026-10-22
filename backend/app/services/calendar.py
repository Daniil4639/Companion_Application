from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.dto.schedule_occurrence import ScheduleOccurrence
from backend.app.models import EventSeries
from backend.app.models import RecurrenceRule
from backend.app.models import EventException
from .recurrence import generate_occurrences
from backend.app.utils import EventExceptionStatus


class CalendarService:

    @staticmethod
    async def create_event(
            title: str,
            start_at: datetime,
            finish_at: datetime,
            timezone: str,
            description: str | None,
            recurrence_rule: RecurrenceRule | None,
            session: AsyncSession
    ) -> EventSeries:

        event_series = EventSeries(
            title=title,
            description=description,
            start_at=start_at,
            finish_at=finish_at,
            timezone=timezone,
            recurrence_rule=recurrence_rule,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        session.add(event_series)
        await session.flush()

        return event_series


    @staticmethod
    async def get_event_series(
            event_series_id: UUID,
            session: AsyncSession
    ) -> EventSeries:

        stmt = (select(EventSeries)
            .where(EventSeries.id == event_series_id)
        )

        event_series = (await session.execute(stmt)).scalar_one_or_none()

        if event_series is None:
            raise ValueError("Event series not found")

        return event_series


    @staticmethod
    async def _get_exception(
            event_series_id: UUID,
            original_start_at: datetime,
            session: AsyncSession
    ) -> EventException | None:

        stmt = select(EventException).where(
            EventException.event_series_id == event_series_id,
            EventException.original_start_at == original_start_at,
        )

        return (await session.execute(stmt)).scalar_one_or_none()


    @staticmethod
    async def _generate_series_occurrences(
            *,
            series: EventSeries,
            range_start: datetime,
            range_end: datetime,
            session: AsyncSession
    ) -> list[ScheduleOccurrence]:

        starts = generate_occurrences(
            start_at=series.start_at,
            recurrence_rule=series.recurrence_rule,
            range_start=range_start,
            range_end=range_end,
        )

        duration = series.finish_at - series.start_at

        result = await session.execute(
            select(EventException)
            .where(
                EventException.event_series_id == series.id,
                EventException.original_start_at >= range_start,
                EventException.original_start_at <= range_end
            )
        )

        exceptions = {
            exception.original_start_at: exception
            for exception in result.scalars().all()
        }

        occurrences = []

        for original_start_at in starts:
            exception = exceptions.get(original_start_at)

            if exception is not None:
                if exception.status == EventExceptionStatus.CANCELLED:
                    continue

                start_at = exception.start_at
                finish_at = exception.finish_at

                if start_at is None or finish_at is None:
                    continue

                occurrences.append(
                    ScheduleOccurrence(
                        event_series_id=series.id,
                        original_start_at=original_start_at,
                        start_at=start_at,
                        finish_at=finish_at,
                        title=exception.title or series.title,
                        description=(
                            exception.description
                            if exception.description is not None
                            else series.description
                        ),
                    )
                )

                continue

            occurrences.append(
                ScheduleOccurrence(
                    event_series_id=series.id,
                    original_start_at=original_start_at,
                    start_at=original_start_at,
                    finish_at=original_start_at + duration,
                    title=series.title,
                    description=series.description,
                )
            )

        return occurrences


    async def move_occurrence(
            self,
            event_series_id: UUID,
            original_start_at: datetime,
            new_start_at: datetime,
            new_finish_at: datetime,
            session: AsyncSession
    ) -> EventException:

        exception = await self._get_exception(
            event_series_id=event_series_id,
            original_start_at=original_start_at,
            session=session
        )

        if exception is None:
            exception = EventException(
                event_series_id=event_series_id,
                original_start_at=original_start_at,
                status=EventExceptionStatus.MODIFIED,
                start_at=new_start_at,
                finish_at=new_finish_at
            )

            session.add(exception)

        else:
            exception.status = EventExceptionStatus.MODIFIED
            exception.start_at = new_start_at
            exception.finish_at = new_finish_at

        await session.flush()

        return exception


    async def cancel_occurrence(
            self,
            event_series_id: UUID,
            original_start_at: datetime,
            session: AsyncSession
    ) -> EventException:

        exception = await self._get_exception(
            event_series_id=event_series_id,
            original_start_at=original_start_at,
            session=session
        )

        if exception is None:
            exception = EventException(
                event_series_id=event_series_id,
                original_start_at=original_start_at,
                status=EventExceptionStatus.CANCELLED,
            )

            session.add(exception)

        else:
            exception.status = EventExceptionStatus.CANCELLED
            exception.start_at = None
            exception.finish_at = None

        await session.flush()

        return exception


    async def get_schedule(
        self,
        range_start: datetime,
        range_end: datetime,
        session: AsyncSession
    ) -> list[ScheduleOccurrence]:

        result = await session.execute(
            select(EventSeries)
            .options(selectinload(EventSeries.recurrence_rule))
            .where(
                (EventSeries.recurrence_rule_id.is_not(None)) |
                ((EventSeries.start_at < range_end) & (EventSeries.finish_at > range_start))
            )
        )

        series_list = result.scalars().all()

        occurrences: list[ScheduleOccurrence] = []

        for series in series_list:
            if series.recurrence_rule is None:
                occurrences.append(
                    ScheduleOccurrence(
                        event_series_id=series.id,
                        original_start_at=series.start_at,
                        start_at=series.start_at,
                        finish_at=series.finish_at,
                        title=series.title,
                        description=series.description
                    )
                )
                continue

            occurrences.extend(
                await self._generate_series_occurrences(
                    series=series,
                    range_start=range_start,
                    range_end=range_end,
                    session=session
                )
            )

        occurrences.sort(key=lambda occurrence: occurrence.start_at)

        return occurrences


calendarService = CalendarService()