from datetime import datetime
from uuid import UUID
from mcp.types import ToolAnnotations
from backend.app.dto.calendar_editing import Version
from backend.app.dto.recurrence_editing import RecurrenceChange, SeriesSplit, RecurrenceResult, RecurrencePreview, \
    UserTimeContext
from backend.app.mcp_adapter.mutations import mutation_session
from backend.app.services import recurrence_editing
from backend.app.services.user_service import get_time_context


def register_recurrence_editing(server):
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)

    @server.tool(annotations=write)
    async def schedule_update_recurrence(event_series_id: UUID, expected_version: Version,
                                         data: RecurrenceChange) -> RecurrenceResult:
        """Replace a recurring series rule, including its past. Rule is a full replacement.
        DTSTART must match: optionally supply start_at, preserving elapsed duration and timezone.
        Exception policy defaults to reject; preserve requires matching ORIGINAL starts; discard deletes explicitly.
        COUNT is the total number of originals, including cancelled ones. Preview before applying.
        """
        async with mutation_session() as session:
            return await recurrence_editing.change_recurrence(event_series_id, expected_version, data, session)

    @server.tool(annotations=write)
    async def schedule_split_series(event_series_id: UUID, expected_version: Version,
                                    data: SeriesSplit) -> RecurrenceResult:
        """Split BEFORE original_start_at; that occurrence starts a new series.
        Cannot split at the first original. Optional start_at moves the future part, never before the boundary.
        Omit recurrence_rule to inherit (COUNT becomes the remaining count); a supplied rule fully replaces it.
        Exception policy affects only originals at/after the boundary. Historical exceptions stay unchanged.
        """
        async with mutation_session() as session:
            return await recurrence_editing.change_recurrence(event_series_id, expected_version, data, session)

    @server.tool(annotations=write)
    async def schedule_restore_occurrence(event_series_id: UUID, original_start_at: datetime,
                                          expected_version: Version) -> RecurrenceResult:
        """Remove one cancellation/modification, restoring time/title/description from the current series.
        Identify by ORIGINAL start, not the moved time. Version check prevents stale/repeated writes.
        """
        async with mutation_session() as session:
            return await recurrence_editing.restore_occurrence(event_series_id, original_start_at, expected_version,
                                                               session)

    @server.tool(annotations=read)
    async def schedule_preview_change(event_series_id: UUID, expected_version: Version,
                                      data: SeriesSplit | RecurrenceChange,
                                      range_start: datetime, range_end: datetime) -> RecurrencePreview:
        """Preview rule replacement or split without DB writes. Include original_start_at to select split.
        Range requires offsets, maximum 366 days. Shows only this series and its proposed replacement(s).
        Exceptions are validated globally, not just inside the preview range. New IDs/versions are provisional.
        """
        async with mutation_session() as session:
            return await recurrence_editing.preview_change(event_series_id, expected_version, data, range_start,
                                                           range_end, session)

    @server.tool(annotations=read)
    async def get_user_context() -> UserTimeContext:
        """Get current local date/time, saved IANA timezone and time settings, without names or IDs.
        System mode uses the last browser-saved timezone; no profile yields explicit UTC fallback.
        """
        async with mutation_session() as session:
            return await get_time_context(session)