import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4
from sqlalchemy import select
from pydantic import SecretStr
from backend.app.db.session import write_transaction
from backend.app.models.llm import LLMProviderRecord, LLMSelectionRecord
from backend.app.dto.llm import ProviderView
from backend.app.llm import create_provider
from backend.app.llm.schemas import ProviderConfig, ModelSelection, ProviderError
from backend.app.llm.credentials import CredentialStore


class LLMProviderService:
    """Settings persistence and short-lived adapter leases; no chat or MCP dependency."""

    def __init__(self, session_factory, credentials=None, factory=create_provider):
        self.sessions, self.credentials, self.factory = session_factory, credentials or CredentialStore(), factory
        self._lock = asyncio.Lock()
        self._changes, self._users = set(), {}
        self._closing = False

    @staticmethod
    def _view(record):
        return ProviderView(**{key: getattr(record, key) for key in ProviderView.model_fields if key != "has_api_key"},
                            has_api_key=bool(record.secret_ref))

    @staticmethod
    async def _record(session, provider_id):
        record = await session.get(LLMProviderRecord, provider_id)
        if record is None:
            raise ProviderError("not_found", "LLM provider not found")
        return record

    async def read_all(self):
        async with self.sessions() as session:
            return [self._view(record) for record in
                    (await session.scalars(select(LLMProviderRecord).order_by(LLMProviderRecord.name))).all()]

    async def get(self, provider_id):
        async with self.sessions() as session:
            return self._view(await self._record(session, provider_id))

    async def _change(self, operation):
        if self._closing:
            raise ProviderError("closed", "Provider settings are closing")

        async def run():
            async with self._lock:
                return await operation()

        task = asyncio.create_task(run())
        self._changes.add(task)

        def done(t):
            self._changes.discard(t)
            if not t.cancelled():
                t.exception()

        task.add_done_callback(done)
        return await asyncio.shield(task)

    async def _retire_key(self, reference):
        try:
            await self.credentials.delete(reference)
        except ProviderError:
            raise ProviderError("credential_cleanup",
                                "Settings were saved, but the old OS credential could not be removed") from None

    async def save(self, data, provider_id=None):
        async def operation():
            old_ref = None
            if provider_id is not None:
                async with self.sessions() as session:
                    old = await self._record(session, provider_id)
                    old_ref = old.secret_ref
                    values = {key: getattr(old, key) for key in ProviderConfig.model_fields if key != "api_key"}
                if data.base_url is not None and data.base_url.rstrip("/") != values[
                    "base_url"] and old_ref and "api_key" not in data.model_fields_set:
                    raise ProviderError("invalid_request",
                                        "Changing an authenticated endpoint requires replacing or clearing its key")
                values.update(data.model_dump(exclude_unset=True))
            else:
                values = data.model_dump()
            config = ProviderConfig.model_validate(values)
            replace_key = provider_id is None or "api_key" in data.model_fields_set
            new_ref = old_ref
            if replace_key:
                new_ref = uuid4().hex if data.api_key and data.api_key.get_secret_value() else None
                if new_ref:
                    await self.credentials.set(new_ref, data.api_key.get_secret_value())
            try:
                async with self.sessions() as session:
                    async with write_transaction(session, lock_model=LLMProviderRecord):
                        if provider_id is None:
                            if await session.get(LLMProviderRecord, config.id):
                                raise ProviderError("conflict", "Provider ID already exists")
                            record = LLMProviderRecord(**config.model_dump(), secret_ref=new_ref)
                            session.add(record)
                        else:
                            record = await self._record(session, provider_id)
                            for key, value in config.model_dump().items():
                                setattr(record, key, value)
                            record.secret_ref = new_ref
                        await session.flush()
                        result = self._view(record)
            except BaseException:
                if new_ref and new_ref != old_ref:
                    await self.credentials.delete(new_ref)
                raise
            if old_ref and old_ref != new_ref:
                await self._retire_key(old_ref)
            return result

        return await self._change(operation)

    async def delete(self, provider_id):
        async def operation():
            async with self.sessions() as session:
                async with write_transaction(session, lock_model=LLMProviderRecord):
                    record = await self._record(session, provider_id)
                    reference = record.secret_ref
                    await session.delete(record)
            if reference:
                await self._retire_key(reference)

        await self._change(operation)

    async def active(self):
        async with self.sessions() as session:
            record = await session.get(LLMSelectionRecord, 1)
            return ModelSelection(
                **{key: getattr(record, key) for key in ModelSelection.model_fields}) if record else None

    async def select(self, selection):
        async def operation():
            async with self.sessions() as session:
                async with write_transaction(session, lock_model=LLMProviderRecord):
                    await self._record(session, selection.provider_id)
                    record = await session.get(LLMSelectionRecord, 1)
                    if record is None:
                        session.add(LLMSelectionRecord(id=1, **selection.model_dump()))
                    else:
                        for key, value in selection.model_dump().items():
                            setattr(record, key, value)
            return selection

        return await self._change(operation)

    @asynccontextmanager
    async def provider(self, provider_id):
        if self._closing:
            raise ProviderError("closed", "Provider runtime is closing")
        task = asyncio.current_task()
        self._users[task] = self._users.get(task, 0) + 1
        adapter = None
        try:
            # Read configuration and resolve its secret under the edit lock so a
            # simultaneous key replacement cannot delete it between those reads.
            async with self._lock:
                async with self.sessions() as session:
                    record = await self._record(session, provider_id)
                    values = {key: getattr(record, key) for key in ProviderConfig.model_fields if key != "api_key"}
                    reference = record.secret_ref
                key = await self.credentials.get(reference) if reference else None
                if reference and not key:
                    raise ProviderError("credential_store", "Saved provider key is unavailable")
                config = ProviderConfig(**values, api_key=SecretStr(key) if key else None)
            adapter = self.factory(config)
            yield adapter
        finally:
            try:
                if adapter:
                    await adapter.aclose()
            finally:
                self._users[task] -= 1
                if not self._users[task]:
                    del self._users[task]

    async def aclose(self):
        self._closing = True
        users = set(self._users) - {asyncio.current_task()}
        for task in users:
            task.cancel()
        await asyncio.gather(*users, *tuple(self._changes), return_exceptions=True)