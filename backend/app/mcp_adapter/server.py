"""Thin MCP tools: validation/serialization only; domain rules stay in services."""
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated
from uuid import UUID
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from backend.app.db import get_db
from backend.app.config import settings
from backend.app.mcp_adapter.mutations import register_mutations
from backend.app.mcp_adapter.calendar_editing import register_calendar_editing
from backend.app.mcp_adapter.recurrence_editing import register_recurrence_editing
from backend.app.dto.tasks import TaskStatus, TaskPriority
from backend.app.dto.schedule import ScheduleOccurrenceResponse
from backend.app.services.tasks import taskService, InvalidTaskData
from backend.app.services.calendar import calendarService
from backend.app.services.errors import InvalidCalendarData


class TaskItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    status: TaskStatus
    priority: TaskPriority
    scheduled_date: date | None
    due_date: date | None


class TasksResult(BaseModel):
    tasks: list[TaskItem]
    next_offset: int | None


class ScheduleResult(BaseModel):
    occurrences: list[ScheduleOccurrenceResponse]


def create_mcp():
    server = MCPServer(
        "Folliant",
        instructions="Manage local tasks and calendar. Use schedule_get for expected_version and schedule_preview_change before recurrence edits. Rule replacement/splitting require explicit exception policy if exceptions exist. Whole-series deletion is forbidden. Dates require UTC offsets. Writes persist immediately.",
    )

    # Reuse get_db's factory and guaranteed async-with cleanup for each tool call.
    session_context = asynccontextmanager(get_db)
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                  idempotentHint=True, openWorldHint=False)

    @server.tool(annotations=annotations)
    async def tasks_list(
            status: TaskStatus | None = None,
            limit: Annotated[int, Field(ge=1, le=500, strict=True)] = 100,
            offset: Annotated[int, Field(ge=0, strict=True)] = 0,
    ) -> TasksResult:
        """List existing tasks, optionally by BACKLOG/TODO/IN_PROGRESS/DONE.
        Follow next_offset until null to read all tasks. Dates are YYYY-MM-DD, without a timezone.
        """
        try:
            async with session_context() as session:
                rows = await taskService.list(session, status=status, limit=limit, offset=offset)
                # Probe using the same service and snapshot, without issuing SQL in the adapter.
                more = await taskService.list(session, status=status, limit=1, offset=offset + len(rows)) if len(
                    rows) == limit else []
                return TasksResult(tasks=[TaskItem.model_validate(row) for row in rows],
                                   next_offset=offset + len(rows) if more else None)
        except InvalidTaskData as exc:
            raise ToolError(str(exc)) from None
        except SQLAlchemyError:
            raise ToolError("Database unavailable; retry the request.") from None

    @server.tool(annotations=annotations)
    async def schedule_list(range_start: datetime, range_end: datetime) -> ScheduleResult:
        """Read overlapping calendar occurrences in [range_start, range_end).
        Use ISO 8601 datetimes with an explicit offset (e.g. +03:00 or Z).
        Maximum range: 366 days. Recurrences, moved/cancelled instances and DST
        use the calendar service; output instants are UTC.
        """
        try:
            async with session_context() as session:
                rows = await calendarService.get_schedule(range_start, range_end, session)
                return ScheduleResult(occurrences=[
                    ScheduleOccurrenceResponse.model_validate({
                        name: getattr(row, name) for name in row.__dataclass_fields__
                    }) for row in rows
                ])
        except InvalidCalendarData as exc:
            raise ToolError(str(exc)) from None
        except SQLAlchemyError:
            raise ToolError("Database unavailable; retry the request.") from None

    register_mutations(server)
    register_calendar_editing(server)
    register_recurrence_editing(server)

    http_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        max_request_body_size=64 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                f"127.0.0.1:{settings.port}",
                f"localhost:{settings.port}",
            ],
            allowed_origins=[
                f"http://127.0.0.1:{settings.port}",
                f"http://localhost:{settings.port}",
            ],
        ),
    )

    return server, http_app