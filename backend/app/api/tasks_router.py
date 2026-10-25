from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db import get_db
from backend.app.dto.tasks import TaskCreate, TaskPatch, TaskMove, TaskResponse, TaskStatus, TaskPriority
from backend.app.services.tasks import taskService


tasks_router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


@tasks_router.get("", response_model=list[TaskResponse])
async def list_tasks(status: TaskStatus | None = None, priority: TaskPriority | None = None,
                     scheduled_date: date | None = None, due_date: date | None = None,
                     date_from: date | None = None, date_to: date | None = None,
                     limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                     session: AsyncSession = Depends(get_db)):

    return await taskService.list(session, status=status, priority=priority,
        scheduled_date=scheduled_date, due_date=due_date, date_from=date_from, date_to=date_to,
        limit=limit, offset=offset)


@tasks_router.post("", response_model=TaskResponse, status_code=201)
async def create_task(data: TaskCreate, session: AsyncSession = Depends(get_db)):
    return await taskService.create(data, session)


@tasks_router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, session: AsyncSession = Depends(get_db)):
    return await taskService.get(task_id, session)


@tasks_router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: UUID, data: TaskPatch, session: AsyncSession = Depends(get_db)):
    return await taskService.update(task_id, data, session)


@tasks_router.patch("/{task_id}/move", response_model=TaskResponse)
async def move_task(task_id: UUID, data: TaskMove, session: AsyncSession = Depends(get_db)):
    return await taskService.move(task_id, data, session)


@tasks_router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: UUID, session: AsyncSession = Depends(get_db)):
    await taskService.delete(task_id, session)

    return Response(status_code=204)
