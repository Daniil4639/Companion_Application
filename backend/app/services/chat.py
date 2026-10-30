"""Local single-worker chat persistence. Network calls never hold a DB session."""
from uuid import uuid4
from sqlalchemy import select
from backend.app.models.chat import Conversation, ChatMessage, GenerationRun
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
        if record is None:
            raise ProviderError("not_found", "Диалог не найден")
        return record

    async def list(self, offset=0, limit=50):
        async with self.sessions() as s:
            return [view(c) for c in (await s.scalars(
                select(Conversation).order_by(Conversation.updated_at.desc(), Conversation.id).offset(offset).limit(
                    limit))).all()]

    async def get(self, id):
        async with self.sessions() as s:
            return view(await self.require(s, id))

    async def save(self, data, id=None):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=Conversation):
                if not await s.get(LLMProviderRecord, data.provider_id):
                    raise ProviderError("invalid_request", "Выберите существующее подключение")
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
            return {"items": [view(m) for m in reversed(rows)], "next_before": rows[-1].position if more else None}

    async def snapshot(self, id):
        async with self.sessions() as s:
            run = await s.get(GenerationRun, id)
            if not run:
                raise ProviderError("not_found", "Генерация не найдена")
            message = await s.get(ChatMessage, run.assistant_message_id)
            return {**view(run), "text": message.text, "position": message.position}

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
                    run.status, run.finished_at = "interrupted", utc_now()
                    run.error = "Генерация прервана перезапуском приложения"
                    m = await s.get(ChatMessage, run.assistant_message_id)
                    m.status = "interrupted"

    async def checkpoint(self, id, text, status, error=None):
        async with self.sessions() as s:
            async with write_transaction(s, lock_model=Conversation):
                run = await s.get(GenerationRun, id)
                m = await s.get(ChatMessage, run.assistant_message_id)
                m.text, m.status = text, status
                run.status, run.error = status, error
                if status not in ACTIVE:
                    run.finished_at = utc_now()
                c = await s.get(Conversation, run.conversation_id)
                c.updated_at = utc_now()

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
                history = (await s.scalars(
                    select(ChatMessage).where(ChatMessage.conversation_id == id).order_by(ChatMessage.position))).all()
                context = builder.build(c, history, data.text)
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
                return view(run), view(c), context