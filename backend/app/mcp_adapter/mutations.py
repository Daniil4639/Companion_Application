"""Write tools delegate validation and domain operations to existing DTOs/services."""
from contextlib import asynccontextmanager
from uuid import UUID
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from backend.app.db import get_db
from backend.app.db.session import write_transaction
from backend.app.dto.events import EventCreate, EventResponse
from backend.app.dto.tasks import TaskCreate, TaskPatch, TaskMove, TaskResponse, TaskStatus
from backend.app.services.calendar import calendarService
from backend.app.services.errors import CalendarError
from backend.app.services.tasks import taskService, InvalidTaskData, TaskNotFound


class SingleEventCreate(EventCreate):
    # Retain EventCreate validation but disallow recurrence through this tool.
    recurrence_rule: None = None


@asynccontextmanager
async def mutation_session():
    try:
        async with asynccontextmanager(get_db)() as session:
            yield session
    except (InvalidTaskData, TaskNotFound, CalendarError, ValidationError) as exc:
        raise ToolError(str(exc)) from None
    except SQLAlchemyError:
        # A client must inspect state before retrying a write with an uncertain outcome.
        raise ToolError("Database operation failed. Check current state before retrying.") from None


def register_mutations(server):
    create_annotations = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                         idempotentHint=False, openWorldHint=False)
    update_annotations = ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                         idempotentHint=False, openWorldHint=False)


    @server.tool(annotations=create_annotations)
    async def tasks_create(data: TaskCreate) -> TaskResponse:
        """Create a task. Dates are optional YYYY-MM-DD; default status BACKLOG.
        Omit position to append to the column. Repeating the call creates another task.
        """
        async with mutation_session() as session:
            task = await taskService.create(data, session)
            return TaskResponse.model_validate(task)


    @server.tool(annotations=update_annotations)
    async def tasks_update(task_id: UUID, data: TaskPatch) -> TaskResponse:
        """Patch only supplied task attributes. Omitted fields stay unchanged.
        Set description, scheduled_date or due_date to null to clear them.
        Prefer tasks_move for column/order changes and tasks_complete to finish a task.
        """
        async with mutation_session() as session:
            task = await taskService.update(task_id, data, session)
            return TaskResponse.model_validate(task)


    @server.tool(annotations=update_annotations)
    async def tasks_move(task_id: UUID, data: TaskMove) -> TaskResponse:
        """Move a task to a status and zero-based position, atomically reordering columns.
        Positions beyond the end append. Moving out of DONE clears completed_at.
        """
        async with mutation_session() as session:
            task = await taskService.move(task_id, data, session)
            return TaskResponse.model_validate(task)


    @server.tool(annotations=update_annotations)
    async def tasks_complete(task_id: UUID) -> TaskResponse:
        """Mark a task DONE and append to that column. Sets completed_at automatically.
        Already completed tasks retain their completed_at and position.
        """
        async with mutation_session() as session:
            task = await taskService.update(task_id, TaskPatch(status=TaskStatus.DONE), session)
            return TaskResponse.model_validate(task)


    @server.tool(annotations=create_annotations)
    async def schedule_create(data: SingleEventCreate) -> EventResponse:
        """Create one non-recurring calendar event, not a task.
        start_at/finish_at require UTC offsets; timezone is an IANA name.
        Recurrence is not supported. Repeating the call creates another event.
        """
        async with mutation_session() as session:
            # Calendar writes use a caller-owned transaction, exactly as in the REST route.
            async with write_transaction(session):
                event = await calendarService.create_event(**data.model_dump(), session=session)
                response = EventResponse.model_validate(event)
            return response