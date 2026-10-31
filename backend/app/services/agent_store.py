"""Durable tool approvals and audit; arguments are immutable after insertion."""
from uuid import uuid4
from sqlalchemy import select
from backend.app.models.chat import ToolExecution, GenerationRun, ChatMessage
from backend.app.db.session import write_transaction
from backend.app.utils.time import utc_now
from backend.app.llm.schemas import ProviderError
from .chat import view, ACTIVE


class AgentStore:
    def __init__(self, sessions):
        self.sessions = sessions

    async def create(self, run_id, call_id, tool, arguments, approval):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=GenerationRun):
                row = ToolExecution(id=uuid4().hex, run_id=run_id, call_id=call_id,
                                    server_id=tool.server_id, tool_name=tool.name, arguments=arguments,
                                    status="waiting_approval" if approval else "approved")
                s.add(row)
                await s.flush()
                return view(row)

    async def get(self, id):
        async with self.sessions() as s:
            row = await s.get(ToolExecution, id)
            if row is None:
                raise ProviderError("not_found", "Вызов не найден")
            return view(row)

    async def decision(self, run_id, id, approve):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=GenerationRun):
                row = await s.get(ToolExecution, id)
                run = await s.get(GenerationRun, run_id)
                if row is None or row.run_id != run_id or run is None:
                    raise ProviderError("not_found", "Вызов не найден")
                target = "approved" if approve else "denied"
                if run.status not in ACTIVE or row.status not in ("waiting_approval", target):
                    raise ProviderError("conflict", "Подтверждение уже обработано или запуск завершён")
                row.status = target
                return view(row)

    async def finish(self, id, status, result=None):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=GenerationRun):
                row = await s.get(ToolExecution, id)
                row.status, row.result = status, result
                if status != "running":
                    row.finished_at = utc_now()

    async def transcript(self, run_id, messages):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=GenerationRun):
                run = await s.get(GenerationRun, run_id)
                message = await s.get(ChatMessage, run.assistant_message_id)
                message.agent_transcript = [m.model_dump(mode="json") for m in messages]

    async def phase(self, run_id, phase):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=GenerationRun):
                run = await s.get(GenerationRun, run_id)
                run.phase = phase

    async def list(self, run_id):
        async with self.sessions() as s:
            rows = (await s.scalars(
                select(ToolExecution).where(ToolExecution.run_id == run_id).order_by(ToolExecution.started_at,
                                                                                     ToolExecution.id))).all()
            return [view(row) for row in rows]