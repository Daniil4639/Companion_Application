from datetime import timedelta
from sqlalchemy import select, delete, func
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import selectinload
from pydantic import ValidationError
from backend.app.dto.events import EventCreate, EventUpdate, RecurrenceRuleCreate
from backend.app.dto.occurence import MoveOccurrenceRequest
from backend.app.dto.schedule_occurrence import ScheduleOccurrence
from backend.app.models import EventSeries, RecurrenceRule, EventException
from backend.app.utils import EventExceptionStatus
from backend.app.utils.time import as_utc, utc_now
from .errors import InvalidCalendarData, CalendarNotFound, CalendarConflict
from .recurrence import generate_occurrences

MAX_RANGE_DAYS = 366
MAX_SCHEDULE_ITEMS = 10000


def validate(model, data):
    try:
        return model.model_validate(data)

    except (ValidationError, ValueError) as exc:
        raise InvalidCalendarData(str(exc)) from exc


def timestamp(value):
    try:
        return as_utc(value)

    except (ValueError, AttributeError) as exc:
        raise InvalidCalendarData("Datetime must include a UTC offset") from exc


class CalendarService:
    """Transport-independent operations. Caller owns commit/rollback."""

    @staticmethod
    async def create_event(title, start_at, finish_at, timezone, description, recurrence_rule, session,
                           category="default"):
        rule_data = None

        if recurrence_rule is not None:
            rule_data = validate(RecurrenceRuleCreate, recurrence_rule).model_dump()

        data = validate(EventCreate, dict(title=title, start_at=start_at, finish_at=finish_at,
                                          timezone=timezone, description=description, recurrence_rule=rule_data,
                                          category=category))

        rule = RecurrenceRule(**data.recurrence_rule.model_dump()) if data.recurrence_rule else None
        series = EventSeries(**data.model_dump(exclude={"recurrence_rule"}), recurrence_rule=rule)
        session.add(series)

        await session.flush()
        return series

    @staticmethod
    async def get_event_series(event_series_id, session):
        series = (await session.execute(
            select(EventSeries).options(selectinload(EventSeries.recurrence_rule))
            .where(EventSeries.id == event_series_id)
        )).scalar_one_or_none()

        if series is None:
            raise CalendarNotFound("Event series not found")

        return series

    @staticmethod
    async def get_event_details(event_series_id, session):
        series = (await session.execute(
            select(EventSeries).options(selectinload(EventSeries.recurrence_rule),
                                        selectinload(EventSeries.exceptions))
            .where(EventSeries.id == event_series_id)
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()

        if series is None:
            raise CalendarNotFound("Event series not found")

        return series

    @staticmethod
    async def list_events(session, limit=100, offset=0):
        if not 1 <= limit <= 500 or offset < 0:
            raise InvalidCalendarData("Invalid pagination")

        return (await session.execute(
            select(EventSeries).options(selectinload(EventSeries.recurrence_rule))
            .order_by(EventSeries.start_at, EventSeries.id).limit(limit).offset(offset)
        )).scalars().all()

    async def update_event(self, event_series_id, changes, session, reset_exceptions=False):
        patch = validate(EventUpdate, changes).model_dump(exclude_unset=True)
        series = await self.get_event_series(event_series_id, session)

        current = dict(title=series.title, category=series.category, description=series.description,
                       start_at=series.start_at,
                       finish_at=series.finish_at, timezone=series.timezone,
                       recurrence_rule=RecurrenceRuleCreate.model_validate(series.recurrence_rule).model_dump()
                       if series.recurrence_rule else None)

        data = validate(EventCreate, {**current, **patch})
        replacement = data.model_dump()
        timing_changed = any(current[key] != replacement[key]
                             for key in ("start_at", "finish_at", "timezone", "recurrence_rule"))

        if timing_changed:
            count = await session.scalar(select(func.count()).select_from(EventException)
                                         .where(EventException.event_series_id == series.id))

            if count and not reset_exceptions:
                raise CalendarConflict("Changing series timing requires reset_exceptions=true")

            if count:
                await session.execute(delete(EventException).where(EventException.event_series_id == series.id))

        old_rule = series.recurrence_rule
        for key, value in data.model_dump(exclude={"recurrence_rule"}).items():
            setattr(series, key, value)

        if data.recurrence_rule:
            if old_rule is None:
                series.recurrence_rule = RecurrenceRule(**data.recurrence_rule.model_dump())

            else:
                for key, value in data.recurrence_rule.model_dump().items():
                    setattr(old_rule, key, value)

        else:
            series.recurrence_rule = None

        series.updated_at = utc_now()
        await session.flush()

        if old_rule is not None and data.recurrence_rule is None:
            await session.delete(old_rule)
            await session.flush()

        return series

    async def delete_event(self, event_series_id, session):
        series = await self.get_event_series(event_series_id, session)
        rule = series.recurrence_rule

        await session.execute(delete(EventException).where(EventException.event_series_id == series.id))
        await session.delete(series)
        await session.flush()

        if rule is not None:
            await session.delete(rule)
            await session.flush()

    async def _require_occurrence(self, event_series_id, original_start_at, session):
        original = timestamp(original_start_at)
        series = await self.get_event_series(event_series_id, session)

        if series.recurrence_rule is None:
            exists = original == series.start_at

        else:
            try:
                end = original + timedelta(microseconds=1)

            except OverflowError as exc:
                raise InvalidCalendarData("Invalid occurrence date") from exc

            exists = bool(generate_occurrences(series.start_at, series.recurrence_rule,
                                               original, end, series.timezone))

        if not exists:
            raise CalendarNotFound("Occurrence does not exist in this series")

        return original

    async def _save_exception(self, event_series_id, original, status, start_at, finish_at, session):
        now = utc_now()

        statement = insert(EventException).values(
            event_series_id=event_series_id, original_start_at=original,
            status=status, start_at=start_at, finish_at=finish_at, created_at=now, updated_at=now)

        statement = statement.on_conflict_do_update(
            index_elements=["event_series_id", "original_start_at"],
            set_=dict(status=status, start_at=start_at, finish_at=finish_at, updated_at=now))

        await session.execute(statement)

        return (await session.execute(
            select(EventException).where(EventException.event_series_id == event_series_id,
                                         EventException.original_start_at == original)
            .execution_options(populate_existing=True)
        )).scalar_one()

    async def move_occurrence(self, event_series_id, original_start_at, new_start_at, new_finish_at, session):
        data = validate(MoveOccurrenceRequest, dict(start_at=new_start_at, finish_at=new_finish_at))
        original = await self._require_occurrence(event_series_id, original_start_at, session)

        # Moving a cancelled occurrence explicitly restores it.
        return await self._save_exception(event_series_id, original, EventExceptionStatus.MODIFIED,
                                          data.start_at, data.finish_at, session)

    async def update_occurrence(self, event_series_id, original_start_at, changes, session):
        """Patch one instance using the existing exception representation. Caller owns transaction."""
        if not changes or set(changes) - {"title", "description", "start_at", "finish_at"}:
            raise InvalidCalendarData("Supply title, description, start_at or finish_at")

        original = await self._require_occurrence(event_series_id, original_start_at, session)
        series = await self.get_event_details(event_series_id, session)

        if series.recurrence_rule is None:
            raise InvalidCalendarData("Occurrence editing requires a recurring series")
        existing = next((e for e in series.exceptions if e.original_start_at == original), None)

        if existing and existing.status == EventExceptionStatus.CANCELLED:
            raise CalendarConflict("Occurrence is cancelled; implicit restoration is not allowed")

        current = dict(
            title=existing.title if existing and existing.title is not None else series.title,
            description=existing.description if existing and existing.description is not None else series.description,
            start_at=existing.start_at if existing else original,
            finish_at=existing.finish_at if existing else original + (series.finish_at - series.start_at),
            timezone=series.timezone, recurrence_rule=None, category=series.category)

        data = validate(EventCreate, {**current, **changes})
        exception = await self.move_occurrence(event_series_id, original, data.start_at, data.finish_at, session)

        if "title" in changes:
            exception.title = data.title
        if "description" in changes:
            exception.description = data.description

        await session.flush()
        return exception

    async def cancel_occurrence(self, event_series_id, original_start_at, session):
        original = await self._require_occurrence(event_series_id, original_start_at, session)

        return await self._save_exception(event_series_id, original, EventExceptionStatus.CANCELLED,
                                          None, None, session)

    async def restore_occurrence(self, event_series_id, original_start_at, session):
        original = await self._require_occurrence(event_series_id, original_start_at, session)

        await session.execute(delete(EventException).where(
            EventException.event_series_id == event_series_id, EventException.original_start_at == original))

        # Removing an exception must not resurrect a previously issued snapshot version.
        series = await self.get_event_series(event_series_id, session)
        series.updated_at = utc_now()

        await session.flush()

    @staticmethod
    async def get_schedule(range_start, range_end, session):
        start, end = timestamp(range_start), timestamp(range_end)

        if end <= start or end - start > timedelta(days=MAX_RANGE_DAYS):
            raise InvalidCalendarData("Range must be positive and no longer than 366 days")

        moved = select(EventException.event_series_id).where(
            EventException.status == EventExceptionStatus.MODIFIED,
            EventException.start_at < end, EventException.finish_at > start)

        rows = (await session.execute(
            select(EventSeries).options(selectinload(EventSeries.recurrence_rule))
            .where(
                ((EventSeries.recurrence_rule_id.is_not(None)) & (EventSeries.start_at < end)) |
                ((EventSeries.start_at < end) & (EventSeries.finish_at > start)) |
                EventSeries.id.in_(moved)
            ).limit(1001)
        )).scalars().all()

        if len(rows) > 1000:
            raise InvalidCalendarData("Schedule exceeds the 1000 series limit")

        if not rows:
            return []

        exceptions = (await session.execute(
            select(EventException).where(EventException.event_series_id.in_([s.id for s in rows]))
            .limit(MAX_SCHEDULE_ITEMS + 1)
        )).scalars().all()

        if len(exceptions) > MAX_SCHEDULE_ITEMS:
            raise InvalidCalendarData("Schedule exceeds the exception limit")

        grouped = {}
        for exception in exceptions:
            grouped.setdefault(exception.event_series_id, {})[exception.original_start_at] = exception
        return render_schedule(rows, grouped, start, end)


def render_schedule(rows, grouped, start, end):
    """Pure occurrence rendering shared by stored schedules and previews."""
    result = {}

    for series in rows:
        overrides = grouped.get(series.id, {})
        duration = series.finish_at - series.start_at

        try:
            lower = start - duration

        except OverflowError as exc:
            raise InvalidCalendarData("Date range is too close to datetime limits") from exc

        originals = (generate_occurrences(series.start_at, series.recurrence_rule, lower, end, series.timezone)
                     if series.recurrence_rule else [series.start_at])

        for original in set(originals) | set(overrides):
            exception = overrides.get(original)

            if exception and exception.status == EventExceptionStatus.CANCELLED:
                continue

            actual_start = exception.start_at if exception else original

            actual_end = exception.finish_at if exception else original + duration

            if actual_start < end and actual_end > start:
                result[(series.id, original)] = ScheduleOccurrence(
                    event_series_id=series.id, original_start_at=original,
                    start_at=actual_start, finish_at=actual_end,
                    title=exception.title if exception and exception.title is not None else series.title,
                    description=exception.description if exception and exception.description is not None else series.description,
                    category=series.category)

                if len(result) > MAX_SCHEDULE_ITEMS:
                    raise InvalidCalendarData("Schedule exceeds the 10000 occurrence limit")

    return sorted(result.values(), key=lambda item: (item.start_at, str(item.event_series_id), item.original_start_at))


calendarService = CalendarService()