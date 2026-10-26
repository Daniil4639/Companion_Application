"""Version-checked calendar editing, independent of MCP/HTTP.

The SQLite writer reservation covers both version checking and mutation. Versions
include exceptions and recurrence, so changes through REST are detected as well.
"""
import hashlib
import json
from backend.app.db.session import write_transaction
from backend.app.dto.calendar_editing import EventDetails, ScheduleDetails, ScheduleEditResult, EventEdit, \
    OccurrenceEdit
from backend.app.services.calendar import calendarService, timestamp, validate
from backend.app.services.errors import CalendarConflict, InvalidCalendarData
from backend.app.utils import EventExceptionStatus


class CalendarEditingService:
    @staticmethod
    def snapshot(series):
        event = EventDetails.model_validate(series)
        event.exceptions.sort(key=lambda e: (e.original_start_at, str(e.id)))
        encoded = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        version = hashlib.sha256(encoded.encode()).hexdigest()
        return ScheduleDetails(event=event, version=version)


    async def get(self, event_series_id, session):
        return self.snapshot(await calendarService.get_event_details(event_series_id, session))


    async def _checked(self, event_series_id, expected_version, session):
        snapshot = await self.get(event_series_id, session)
        if snapshot.version != expected_version:
            raise CalendarConflict(
                "VERSION_CONFLICT: event or exceptions changed; call schedule_get and review before retrying")
        return snapshot.event


    @staticmethod
    def _single(event):
        if event.recurrence_rule is not None:
            raise InvalidCalendarData("Series-wide editing is not supported; identify one original_start_at")
        if event.exceptions:
            raise CalendarConflict("Single event has exceptions; review them before editing")


    async def _result(self, event_series_id, before, session, *, original=None, outcome="updated", warnings=None):
        after = await self.get(event_series_id, session)
        if original is None:
            fields = [key for key in ("title", "description", "start_at", "finish_at", "timezone")
                      if getattr(before, key) != getattr(after.event, key)]
        else:
            previous = next((e for e in before.exceptions if e.original_start_at == original), None)
            current = next(e for e in after.event.exceptions if e.original_start_at == original)
            defaults = dict(title=None, description=None, status=EventExceptionStatus.MODIFIED,
                            start_at=original, finish_at=original + (before.finish_at - before.start_at))
            fields = [key for key in defaults if
                      (getattr(previous, key) if previous else defaults[key]) != getattr(current, key)]
        return ScheduleEditResult(event_series_id=event_series_id, original_start_at=original,
                                  outcome=outcome, changed_fields=fields, warnings=warnings or [],
                                  version=after.version, event=after.event)


    async def update(self, event_series_id, expected_version, data, session):
        data = validate(EventEdit, data)
        async with write_transaction(session):
            before = await self._checked(event_series_id, expected_version, session)
            self._single(before)
            await calendarService.update_event(event_series_id, data.model_dump(exclude_unset=True), session)
            return await self._result(event_series_id, before, session)


    async def reschedule(self, event_series_id, expected_version, start_at, finish_at, session):
        start_at = timestamp(start_at)
        async with write_transaction(session):
            before = await self._checked(event_series_id, expected_version, session)
            self._single(before)
            try:
                end = timestamp(finish_at) if finish_at is not None else start_at + (before.finish_at - before.start_at)
            except OverflowError as exc:
                raise InvalidCalendarData("Duration exceeds supported datetime range") from exc
            await calendarService.update_event(event_series_id, dict(start_at=start_at, finish_at=end), session)
            return await self._result(event_series_id, before, session,
                                      warnings=["Original elapsed duration preserved"] if finish_at is None else [])


    async def update_occurrence(self, event_series_id, original_start_at, expected_version, data, session):
        data = validate(OccurrenceEdit, data)
        original = timestamp(original_start_at)
        async with write_transaction(session):
            before = await self._checked(event_series_id, expected_version, session)
            await calendarService.update_occurrence(event_series_id, original, data.model_dump(exclude_unset=True),
                                                    session)
            return await self._result(event_series_id, before, session, original=original)


    async def delete(self, event_series_id, expected_version, original_start_at, session):
        async with write_transaction(session):
            before = await self._checked(event_series_id, expected_version, session)
            if before.recurrence_rule is None:
                self._single(before)
                if original_start_at is not None:
                    raise InvalidCalendarData("Omit original_start_at when deleting a single event")
                await calendarService.delete_event(event_series_id, session)
                return ScheduleEditResult(event_series_id=event_series_id, outcome="deleted", changed_fields=["event"])
            if original_start_at is None:
                raise InvalidCalendarData("Deleting a whole series is forbidden; supply original_start_at")
            original = timestamp(original_start_at)
            await calendarService.cancel_occurrence(event_series_id, original, session)
            return await self._result(event_series_id, before, session, original=original, outcome="cancelled")


calendarEditingService = CalendarEditingService()