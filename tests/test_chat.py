import os

os.environ["COMPANION_LOAD_DOTENV"] = "0"

import asyncio
import tempfile
import unittest
from pathlib import Path
from contextlib import asynccontextmanager, closing
from sqlalchemy.ext.asyncio import async_sessionmaker
from backend.app.db.session import make_engine
from backend.app.db.base import Base
from backend.app.models import User, LLMProviderRecord
from backend.app.dto.chat import ChatSettings, SendMessage
from backend.app.services.chat import ChatService
from backend.app.services.chat_context import ContextBuilder
from backend.app.services.chat_generation import GenerationManager
from backend.app.llm.schemas import StreamEvent, ModelResponse, Message, ProviderError


class FakeProviders:
    slow = False

    @asynccontextmanager
    async def provider(self, _):
        yield self

    async def stream(self, request):
        self.request = request
        yield StreamEvent(type="text_delta", text="Привет")
        if self.slow:
            await asyncio.sleep(60)
        yield StreamEvent(type="completed", response=ModelResponse(provider_id="local", model="test",
                                                                   message=Message(role="assistant", text="Привет")))


class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = make_engine("sqlite+aiosqlite:///" + (Path(self.tmp.name) / "test.db").as_posix())
        async with self.engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as s:
            async with s.begin():
                s.add(User(id=1, username="test", timezone="UTC", timezone_mode="manual", locale="ru-RU"))
                s.add(LLMProviderRecord(id="local", kind="ollama", name="Local", base_url="http://localhost:11434",
                                        timeout=10, connect_timeout=2))
        self.service = ChatService(self.sessions)
        self.providers = FakeProviders()
        self.builder = ContextBuilder("Global instructions")
        self.manager = GenerationManager(self.service, self.providers, self.builder)
        self.settings = ChatSettings(provider_id="local", model="test", system_prompt="Local instructions")
        self.chat = await self.service.save(self.settings)

    async def asyncTearDown(self):
        await self.manager.aclose()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_crud_and_provider_deletion(self):
        data = self.settings.model_copy(update={"title": "Renamed", "context_window_tokens": 4096})
        result = await self.service.save(data, self.chat["id"])
        self.assertEqual(result["title"], "Renamed")
        async with self.sessions() as s:
            async with s.begin():
                await s.delete(await s.get(LLMProviderRecord, "local"))
        self.assertIsNone((await self.service.get(self.chat["id"]))["provider_id"])
        await self.service.delete(self.chat["id"])
        self.assertEqual(await self.service.list(), [])

    async def test_generation_and_idempotency(self):
        data = SendMessage(text="Hello", request_id="one")
        run = await self.manager.start(self.chat["id"], data)
        task = self.manager.tasks[run["id"]]
        await task
        retry = await self.manager.start(self.chat["id"], data)
        self.assertEqual(retry["id"], run["id"])
        history = await self.service.messages(self.chat["id"])
        self.assertEqual(len(history["items"]), 2)
        self.assertEqual(history["items"][1]["text"], "Привет")
        self.assertEqual((await self.manager.snapshot(run["id"]))["status"], "completed")
        self.assertIn("Global instructions", self.providers.request.messages[0].text)
        self.assertIn("Local instructions", self.providers.request.messages[0].text)
        page = await self.service.messages(self.chat["id"], limit=1)
        self.assertEqual(page["next_before"], 1)

    async def test_cancel_and_busy(self):
        self.providers.slow = True
        run = await self.manager.start(self.chat["id"], SendMessage(text="Hello", request_id="one"))
        while not self.manager.progress[run["id"]]["text"]:
            await asyncio.sleep(.01)
        with self.assertRaises(ProviderError):
            await self.manager.start(self.chat["id"], SendMessage(text="Again", request_id="two"))
        result = await self.manager.cancel(run["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["text"], "Привет")

    async def test_context_and_recovery(self):
        with self.assertRaises(ProviderError):
            self.builder.build(self.settings, [], "я" * 10000)
        run, _, _ = await self.service.prepare(self.chat["id"], SendMessage(text="x", request_id="lost"), self.builder)
        await self.service.recover()
        self.assertEqual((await self.service.snapshot(run["id"]))["status"], "interrupted")
        # Only complete exchanges enter the next model request.
        from types import SimpleNamespace as M
        history = [M(role="user", text="old" * 3000, status="completed"),
                   M(role="assistant", text="old", status="completed"),
                   M(role="user", text="recent", status="completed"),
                   M(role="assistant", text="answer", status="completed")]
        messages = self.builder.build(self.settings, history, "current")
        self.assertEqual([m.text for m in messages[1:]], ["recent", "answer", "current"])

    async def test_http_and_sse(self):
        import httpx
        from fastapi import FastAPI
        from backend.app.api.chat_router import chat_router
        app = FastAPI()
        app.state.chat_service = self.service
        app.state.chat_generations = self.manager
        app.include_router(chat_router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1234)),
                                     base_url="http://127.0.0.1") as client:
            response = await client.post("/api/chats/" + self.chat["id"] + "/messages",
                                         json={"text": "Hello", "request_id": "http"})
            self.assertEqual(response.status_code, 202)
            run = response.json()
            await self.manager.tasks[run["id"]]
            response = await client.get("/api/chats/runs/" + run["id"] + "/events")
            self.assertEqual(response.status_code, 200)
            self.assertIn("event: snapshot", response.text)
            self.assertIn("Привет", response.text)
            self.assertIn('"status": "completed"', response.text)


class MigrationTests(unittest.TestCase):
    def test_migration(self):
        from alembic.config import Config
        from alembic import command
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "migration.db"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", "sqlite+aiosqlite:///" + path.as_posix())
            command.upgrade(config, "head")
            with closing(sqlite3.connect(path)) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({"conversations", "chat_messages", "generation_runs"} <= tables)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()