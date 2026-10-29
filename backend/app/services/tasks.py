from sqlalchemy import select, or_, and_, case
from backend.app.db.session import write_transaction
from backend.app.models.task import Task
from backend.app.dto.tasks import TaskCreate, TaskPatch, TaskMove, TaskStatus, TaskPriority
from backend.app.utils.time import utc_now


class TaskNotFound(Exception):
    pass


class InvalidTaskData(Exception):
    pass


class TaskService:
    @staticmethod
    async def get(task_id, session):
        task = await session.get(Task, task_id)

        if task is None:
            raise TaskNotFound("Задача не найдена")

        return task

    @staticmethod
    async def list(session, *, status=None, priority=None, scheduled_date=None,
                   due_date=None, date_from=None, date_to=None, limit=100, offset=0):
        if not 1 <= limit <= 500 or offset < 0:
            raise InvalidTaskData("Некорректная пагинация")

        if date_from and date_to and date_from > date_to:
            raise InvalidTaskData("Начало диапазона позже окончания")

        query = select(Task)
        if status is not None:
            query = query.where(Task.status == TaskStatus(status).value)

        if priority is not None:
            query = query.where(Task.priority == TaskPriority(priority).value)

        for column, value in ((Task.scheduled_date, scheduled_date), (Task.due_date, due_date)):
            if value is not None:
                query = query.where(column == value)

        if date_from or date_to:
            clauses = []

            for column in (Task.scheduled_date, Task.due_date):
                conditions = [column.is_not(None)]

                if date_from:
                    conditions.append(column >= date_from)

                if date_to:
                    conditions.append(column <= date_to)

                clauses.append(and_(*conditions))

            query = query.where(or_(*clauses))

        order = case({s.value: i for i, s in enumerate(TaskStatus)}, value=Task.status)
        result = await session.scalars(query.order_by(order, Task.position, Task.id).limit(limit).offset(offset))

        return list(result)

    @staticmethod
    async def _column(status, session):
        return list(await session.scalars(select(Task).where(Task.status == status).order_by(Task.position, Task.id)))

    async def _reorder(self, task, status, position, session):
        source = await self._column(task.status, session)
        target = source if status == task.status else await self._column(status, session)

        source = [row for row in source if row.id != task.id]
        target = source if status == task.status else target

        target.insert(min(position, len(target)), task)
        columns = {status: target}

        if status != task.status:
            columns[task.status] = source

        rows = [row for column in columns.values() for row in column]
        original = {row.id: (row.status, row.position, row.updated_at) for row in rows}

        base = max((row.position for row in rows), default=0) + len(rows) + 1

        for index, row in enumerate(rows):
            row.position = base + index
        await session.flush()

        now = utc_now()
        for column_status, column in columns.items():
            for index, row in enumerate(column):
                previous_status, previous_position, previous_updated = original[row.id]
                row.status, row.position = column_status, index

                if column_status != previous_status:
                    row.completed_at = now if column_status == "DONE" else None

                row.updated_at = now if (column_status, index) != (previous_status,
                                                                   previous_position) else previous_updated

        await session.flush()

    async def create(self, data: TaskCreate, session):
        data = TaskCreate.model_validate(data)

        async with write_transaction(session, lock_model=Task):
            column = await self._column(data.status, session)
            values = data.model_dump(exclude={"position"})

            task = Task(**values, position=len(column),
                        completed_at=utc_now() if data.status == "DONE" else None)
            session.add(task)

            await session.flush()
            if data.position is not None:
                await self._reorder(task, data.status, data.position, session)

        return task

    async def update(self, task_id, data: TaskPatch, session):
        data = TaskPatch.model_validate(data)

        async with write_transaction(session, lock_model=Task):
            task = await self.get(task_id, session)
            values = data.model_dump(exclude_unset=True)

            status = values.pop("status", task.status)
            position = values.pop("position", None)

            if status != task.status or position is not None:
                target = await self._column(status, session)
                await self._reorder(task, status, len(target) if position is None else position, session)

            for key, value in values.items():
                setattr(task, key, value)

            task.updated_at = utc_now()
            await session.flush()

        return task

    async def move(self, task_id, data: TaskMove, session):
        data = TaskMove.model_validate(data)

        return await self.update(task_id, TaskPatch(status=data.status, position=data.position), session)

    async def delete(self, task_id, session):
        async with write_transaction(session, lock_model=Task):
            task = await self.get(task_id, session)
            status = task.status

            await session.delete(task)
            await session.flush()

            rows = await self._column(status, session)
            if rows:
                await self._reorder(rows[0], status, 0, session)


taskService = TaskService()