"""Local single-worker chat persistence. Network calls never hold a DB session."""
from uuid import uuid4
from sqlalchemy import select
from backend.app.models.chat import Conversation, ChatMessage, GenerationRun, ToolExecution, ConversationSummary
from backend.app.models.mcp_server import MCPServerRecord
from backend.app.models.llm import LLMProviderRecord
from backend.app.db.session import write_transaction
from backend.app.utils.time import utc_now
from backend.app.llm.schemas import ProviderError


ACTIVE = ("pending", "running")


def view(record):
    return {c.name: getattr(record, c.name) for c in record.__table__.columns}


class ChatService:
    def __init__(self, sessions):
        self.sessions = sessions

    async def require(self, session, id):
        record = await session.get(Conversation, id)
        if record is None or record.user_id != 1:
            raise ProviderError("not_found", "Диалог не найден")
        return record

    async def list(self, offset=0, limit=50):
        async with self.sessions() as s:
            return [view(c) for c in (await s.scalars(
                select(Conversation).where(Conversation.user_id == 1).order_by(Conversation.updated_at.desc(),
                                                                               Conversation.id).offset(offset).limit(
                    limit))).all()]

    async def get(self, id):
        async with self.sessions() as s:
            return view(await self.require(s, id))

    async def save(self, data, id=None):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=Conversation):
                if not await s.get(LLMProviderRecord, data.provider_id):
                    raise ProviderError("invalid_request", "Выберите существующее подключение")
                for server_id in data.mcp_servers:
                    if not await s.get(MCPServerRecord, server_id):
                        raise ProviderError("invalid_request", "MCP-подключение не найдено")
                if id:
                    c = await self.require(s, id)
                    if await s.scalar(select(GenerationRun.id).where(GenerationRun.conversation_id == id,
                                                                     GenerationRun.status.in_(ACTIVE))):
                        raise ProviderError("conflict", "Остановите генерацию перед изменением настроек")
                    for k, v in data.model_dump().items():
                        setattr(c, k, v)
                else:
                    c = Conversation(id=uuid4().hex, **data.model_dump())
                    s.add(c)
                c.updated_at = utc_now()
                await s.flush()
                return view(c)

    async def delete(self, id):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=Conversation):
                c = await self.require(s, id)
                if await s.scalar(select(GenerationRun.id).where(GenerationRun.conversation_id == id,
                                                                 GenerationRun.status.in_(ACTIVE))):
                    raise ProviderError("conflict", "Остановите генерацию перед удалением")
                await s.delete(c)

    async def messages(self, id, before=None, limit=50):
        async with self.sessions() as s:
            await self.require(s, id)
            q = select(ChatMessage).where(ChatMessage.conversation_id == id)
            if before is not None:
                q = q.where(ChatMessage.position < before)
            rows = (await s.scalars(q.order_by(ChatMessage.position.desc()).limit(limit + 1))).all()
            more = len(rows) > limit
            rows = rows[:limit]
            items = [view(m) for m in reversed(rows)]
            assistant_ids = [m["id"] for m in items if m["role"] == "assistant"]
            executions_by_message = {}
            if assistant_ids:
                run_rows = (await s.execute(select(GenerationRun.id, GenerationRun.assistant_message_id,
                                                   GenerationRun.status).where(GenerationRun.conversation_id == id,
                                                                               GenerationRun.assistant_message_id.in_(
                                                                                   assistant_ids)))).all()
                run_info = {run_id: (message_id, status) for run_id, message_id, status in run_rows}
                run_ids = list(run_info)
                if run_ids:
                    executions = (await s.scalars(select(ToolExecution).where(ToolExecution.run_id.in_(run_ids))
                                                  .order_by(ToolExecution.started_at, ToolExecution.id))).all()
                    for execution in executions:
                        message_id, run_status = run_info[execution.run_id]
                        executions_by_message.setdefault(message_id, []).append(
                            {**view(execution), "run_status": run_status})
            for message in items:
                message["tool_executions"] = executions_by_message.get(message["id"], [])
            return {"items": items, "next_before": rows[-1].position if more else None}

    async def snapshot(self, id):
        async with self.sessions() as s:
            run = await s.get(GenerationRun, id)
            if not run:
                raise ProviderError("not_found", "Генерация не найдена")
            message = await s.get(ChatMessage, run.assistant_message_id)
            return {**view(run), "text": message.text, "position": message.position,
                    "answer_complete": message.status == "completed"}

    async def latest_run(self, id):
        async with self.sessions() as s:
            await self.require(s, id)
            run = await s.scalar(select(GenerationRun).where(GenerationRun.conversation_id == id).order_by(
                GenerationRun.started_at.desc()).limit(1))
            return view(run) if run else None

    async def recover(self):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=Conversation):
                runs = (await s.scalars(select(GenerationRun).where(GenerationRun.status.in_(ACTIVE)))).all()
                for run in runs:
                    for tool in (await s.scalars(select(ToolExecution).where(ToolExecution.run_id == run.id,
                                                                             ToolExecution.status.in_(
                                                                                     ("waiting_approval", "approved",
                                                                                      "running"))))).all():
                        tool.status = "unknown" if tool.status == "running" else "interrupted"
                        tool.finished_at = utc_now()
                    run.status, run.finished_at = "interrupted", utc_now()
                    run.error = "Генерация прервана перезапуском приложения"
                    m = await s.get(ChatMessage, run.assistant_message_id)
                    if m.status != "completed":
                        m.status = "interrupted"

    async def checkpoint(self, id, text, status, error=None, answer_complete=False, phase=None):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=Conversation):
                run = await s.get(GenerationRun, id)
                m = await s.get(ChatMessage, run.assistant_message_id)
                m.text, m.status = text, "completed" if answer_complete else status
                run.status, run.error = status, error
                if phase:
                    run.phase = phase
                if status not in ACTIVE:
                    run.finished_at = utc_now()
                c = await s.get(Conversation, run.conversation_id)
                c.updated_at = utc_now()

    async def busy_providers(self):
        async with self.sessions() as s:
            rows = (await s.execute(select(Conversation.provider_id, GenerationRun.conversation_id, GenerationRun.phase)
                                    .join(GenerationRun, GenerationRun.conversation_id == Conversation.id)
                                    .where(Conversation.user_id == 1, GenerationRun.status.in_(ACTIVE)))).all()
            return [{"provider_id": p, "conversation_id": c, "phase": phase} for p, c, phase in rows]

    async def catalog(self, offset=0, limit=20):
        limit = min(50, max(1, limit))
        rows = await self.list(max(0, offset), limit + 1)
        items = []
        async with self.sessions() as s:
            for row in rows[:limit]:
                items.append({"id": row["id"], "title": row["title"], "topic": row["title"],
                              "has_summary": await s.get(ConversationSummary, row["id"]) is not None})
        return {"items": items, "next_offset": offset + limit if len(rows) > limit else None}

    async def read_visible_messages(self, id, before=None, limit=10, text_offset=0):
        page = await self.messages(id, before, min(20, max(1, limit)))
        return {"items": [{"id": m["id"], "role": m["role"], "text": m["text"][text_offset:text_offset + 4000],
                           "truncated": len(m["text"]) > text_offset + 4000 or text_offset > 0,
                           "next_text_offset": text_offset + 4000 if len(m["text"]) > text_offset + 4000 else None,
                           "status": m["status"], "position": m["position"]}
                          for m in page["items"]], "next_before": page["next_before"]}

    async def prepare(self, id, data, builder):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=Conversation):
                c = await self.require(s, id)
                prior = await s.scalar(select(GenerationRun).where(GenerationRun.conversation_id == id,
                                                                   GenerationRun.request_id == data.request_id))
                if prior:
                    original = await s.get(ChatMessage, prior.user_message_id)
                    if original.text != data.text:
                        raise ProviderError("conflict", "Идентификатор запроса уже использован с другим текстом")
                    return view(prior), None, None
                if await s.scalar(select(GenerationRun.id).where(GenerationRun.conversation_id == id,
                                                                 GenerationRun.status.in_(ACTIVE))):
                    raise ProviderError("conflict", "В этом диалоге уже идёт генерация")
                if not c.provider_id:
                    raise ProviderError("invalid_request", "Подключение удалено. Выберите другое в настройках диалога")
                if await s.scalar(select(GenerationRun.id).join(Conversation,
                                                                Conversation.id == GenerationRun.conversation_id).where(
                        Conversation.provider_id == c.provider_id, GenerationRun.status.in_(ACTIVE))):
                    raise ProviderError("conflict",
                                        "Провайдер занят в другом диалоге. Дождитесь завершения ответа или сжатия истории.")
                history = (await s.scalars(
                    select(ChatMessage).where(ChatMessage.conversation_id == id).order_by(ChatMessage.position))).all()
                summary = await s.get(ConversationSummary, id)
                context = builder.build(c, history, data.text, summary=summary)
                pos = history[-1].position + 1 if history else 0
                user = ChatMessage(id=uuid4().hex, conversation_id=id, role="user", text=data.text,
                                   status="completed", position=pos, provider_id=c.provider_id, model=c.model)
                assistant = ChatMessage(id=uuid4().hex, conversation_id=id, role="assistant", text="",
                                        status="pending", position=pos + 1, provider_id=c.provider_id, model=c.model)
                s.add_all([user, assistant])
                await s.flush()
                run = GenerationRun(id=uuid4().hex, conversation_id=id, request_id=data.request_id,
                                    user_message_id=user.id, assistant_message_id=assistant.id, status="pending")
                s.add(run)
                c.updated_at = utc_now()
                await s.flush()
                chat_settings = view(c)
                chat_settings["_context_prefix"] = int(bool(builder.global_prompt or c.system_prompt)) + int(
                    summary is not None)
                return view(run), chat_settings, context