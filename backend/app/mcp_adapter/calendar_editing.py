"""Typed calendar editing tools; domain policy lives in CalendarEditingService."""
from datetime import datetime
from uuid import UUID
from mcp.types import ToolAnnotations
from backend.app.dto.calendar_editing import EventEdit, OccurrenceEdit, Version, ScheduleDetails, ScheduleEditResult
from backend.app.mcp_adapter.mutations import mutation_session
from backend.app.services.calendar_editing import calendarEditingService


def register_calendar_editing(server):
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)


    @server.tool(annotations=read)
    async def schedule_get(event_series_id: UUID) -> ScheduleDetails:
        """Get full event, recurrence rule, timezone, exceptions and opaque version.
        Obtain a fresh version here before editing. Exception null metadata inherits from the series.
        """
        async with mutation_session() as session:
            return await calendarEditingService.get(event_series_id, session)


    @server.tool(annotations=write)
    async def schedule_update(event_series_id: UUID, expected_version: Version, data: EventEdit) -> ScheduleEditResult:
        """Patch an ordinary event only. Never edits a recurring series.
        Omitted fields stay unchanged; description null clears it. A stale/replayed version fails.
        """
        async with mutation_session() as session:
            return await calendarEditingService.update(event_series_id, expected_version, data, session)


    @server.tool(annotations=write)
    async def schedule_reschedule(event_series_id: UUID, expected_version: Version,
                                  start_at: datetime, finish_at: datetime | None = None) -> ScheduleEditResult:
        """Move an ordinary event. Omit finish_at to preserve elapsed duration in UTC.
        Datetimes require offsets. Retains the event's IANA timezone. No series-wide moves.
        """
        async with mutation_session() as session:
            return await calendarEditingService.reschedule(event_series_id, expected_version, start_at, finish_at, session)


    @server.tool(annotations=write)
    async def schedule_update_occurrence(event_series_id: UUID, original_start_at: datetime,
                                         expected_version: Version, data: OccurrenceEdit) -> ScheduleEditResult:
        """Patch one recurring occurrence, identified by its ORIGINAL start, even after a move.
        Other instances are unchanged. For a move supply start_at and finish_at.
        description null inherits the series; empty string clears the visible description.
        Cancelled instances cannot be implicitly restored. Re-read version after each edit.
        """
        async with mutation_session() as session:
            return await calendarEditingService.update_occurrence(event_series_id, original_start_at, expected_version, data, session)


    @server.tool(annotations=write)
    async def schedule_delete(event_series_id: UUID, expected_version: Version,
                               original_start_at: datetime | None = None) -> ScheduleEditResult:
        """Delete an ordinary event, or cancel ONE recurring occurrence with original_start_at.
        Whole-series deletion is forbidden. Repeat with a stale version fails; already deleted IDs are not found.
        """
        async with mutation_session() as session:
            return await calendarEditingService.delete(event_series_id, expected_version, original_start_at, session)