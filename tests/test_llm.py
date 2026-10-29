"""Use real official SDK parsers with mocked HTTP transports; no network/API keys."""
import os

os.environ["COMPANION_LOAD_DOTENV"] = "0"
import asyncio
from contextlib import aclosing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock
import httpx
import httpx2
from openai import AsyncOpenAI
from ollama import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker
from backend.app.llm import OpenAIProvider, OllamaProvider
from backend.app.llm.schemas import (ProviderConfig, GenerationRequest, Message, ModelSelection,
                                     ToolDefinition, ProviderError)
from backend.app.dto.llm import ProviderCreate, ProviderPatch
from backend.app.services.llm_providers import LLMProviderService
from backend.app.db.base import Base
from backend.app.db.session import make_engine
from backend.app.main import create_app


def config(kind="openai"):
    return ProviderConfig(id="test", kind=kind, name="Test",
                          base_url="http://localhost:9999/v1" if kind == "openai" else "http://localhost:9999",
                          api_key="SECRET-test")


def request(messages=None, tools=False):
    return GenerationRequest(selection=ModelSelection(provider_id="test", model="test-model"),
                             messages=messages or [Message(role="user", text="Hello")],
                             tools=[ToolDefinition(name="weather", parameters={"type": "object", "properties": {
                                 "city": {"type": "string"}}})] if tools else [])


def response(output=None, status="completed"):
    return {"id": "resp_test", "object": "response", "created_at": 1, "model": "test-model", "status": status,
            "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
            "output": output if output is not None else [
                {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                 "content": [{"type": "output_text", "text": "Hello!", "annotations": []}]}],
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "metadata": {},
            "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}}


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def openai(self, handler):
        client = AsyncOpenAI(api_key="SECRET-test", base_url="http://localhost:9999/v1", max_retries=0,
                             http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
        return OpenAIProvider(config(), client=client)

    def ollama(self, handler):
        return OllamaProvider(config("ollama"),
                              client=AsyncClient(host="http://localhost:9999", transport=httpx.MockTransport(handler)))

    async def test_openai_text_tools_continuation_and_models(self):
        sent = []
        output = [{"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"},
                  {"type": "function_call", "id": "fc_1", "call_id": "call_one", "name": "weather",
                   "arguments": '{"city":"Moscow"}', "status": "completed"}]

        def handler(req):
            if req.url.path.endswith("/models"):
                return httpx2.Response(200, json={"object": "list", "data": [
                    {"id": "test-model", "object": "model", "created": 1, "owned_by": "test"}]})
            sent.append(json.loads(req.content))
            return httpx2.Response(200, json=response(output if len(sent) == 1 else None))

        provider = self.openai(handler)
        try:
            result = await provider.generate(request(tools=True))
            self.assertEqual(result.finish_reason, "tool_calls")
            call = result.message.tool_calls[0]
            self.assertEqual(call.id, "call_one")
            self.assertEqual(call.arguments(), {"city": "Moscow"})
            self.assertFalse(sent[0]["store"])
            self.assertFalse(sent[0]["tools"][0]["strict"])
            followup = request([Message(role="user", text="Weather?"), result.message,
                                Message(role="tool", tool_call_id=call.id, text="Sunny")], tools=True)
            final = await provider.generate(followup)
            self.assertEqual(final.message.text, "Hello!")
            self.assertEqual(sent[1]["input"][1]["encrypted_content"], "opaque")
            self.assertEqual(sent[1]["input"][-1]["call_id"], "call_one")
            self.assertEqual(final.usage.input_tokens, 7)
            self.assertEqual((await provider.list_models())[0].id, "test-model")
            followup.selection.model = "different-model"
            with self.assertRaises(ProviderError) as caught:
                await provider.generate(followup)
            self.assertEqual(caught.exception.code, "invalid_request")
        finally:
            await provider.aclose()
        self.assertTrue(provider.client.is_closed())

    async def test_openai_stream_and_early_close(self):
        events = [{"type": "response.created", "response": response([], "in_progress"), "sequence_number": 0},
                  {"type": "response.output_item.added", "output_index": 0, "sequence_number": 1,
                   "item": {"type": "message", "id": "msg_1", "role": "assistant", "status": "in_progress",
                            "content": []}},
                  {"type": "response.content_part.added", "output_index": 0, "content_index": 0, "item_id": "msg_1",
                   "sequence_number": 2,
                   "part": {"type": "output_text", "text": "", "annotations": []}},
                  {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "item_id": "msg_1",
                   "delta": "Hello!", "sequence_number": 3},
                  {"type": "response.completed", "response": response(), "sequence_number": 4}]

        def handler(req):
            return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                                   content="".join("data: " + json.dumps(e) + "\n\n" for e in events))

        provider = self.openai(handler)
        try:
            result = [event async for event in provider.stream(request())]
            self.assertEqual(result[0].text, "Hello!")
            self.assertEqual(result[-1].response.message.text, "Hello!")
            async with aclosing(provider.stream(request())) as stream:
                self.assertEqual((await anext(stream)).type, "text_delta")
            self.assertFalse(provider._lock.locked())
        finally:
            await provider.aclose()

    async def test_ollama_stream_tools_thinking_and_followup(self):
        sent = []
        call = {"function": {"index": 0, "name": "weather", "arguments": {"city": "Moscow"}}}

        def handler(req):
            if req.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"model": "test-model"}]})
            body = json.loads(req.content)
            sent.append(body)
            if body.get("stream"):
                chunks = [
                    {"message": {"role": "assistant", "thinking": "opaque thinking", "content": ""}, "done": False},
                    {"message": {"role": "assistant", "content": "Checking", "tool_calls": [call]}, "done": False},
                    {"message": {"role": "assistant", "content": ""}, "done": True, "eval_count": 4}]
                return httpx.Response(200, content="\n".join(json.dumps(chunk) for chunk in chunks))
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "Sunny"}, "done": True})

        provider = self.ollama(handler)
        try:
            events = [e async for e in provider.stream(request(tools=True))]
            self.assertEqual([e.type for e in events], ["text_delta", "tool_call", "completed"])
            result = events[-1].response
            self.assertEqual(result.message.continuation.items[0]["thinking"], "opaque thinking")
            tool_id = result.message.tool_calls[0].id
            self.assertEqual(events[1].tool_call.id, tool_id)
            final = await provider.generate(request([Message(role="user", text="Weather?"), result.message,
                                                     Message(role="tool", tool_call_id=tool_id, text="Sunny")],
                                                    tools=True))
            self.assertEqual(final.message.text, "Sunny")
            self.assertEqual(sent[-1]["messages"][-1]["tool_name"], "weather")
            self.assertEqual(sent[-1]["messages"][-2]["thinking"], "opaque thinking")
            self.assertEqual((await provider.list_models())[0].id, "test-model")
        finally:
            await provider.aclose()
        self.assertTrue(provider.client._client.is_closed)

    async def test_openai_fragmented_tool_stream_and_incomplete(self):
        tool = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "weather", "arguments": ""}
        completed = {**tool, "arguments": '{"city":"Moscow"}', "status": "completed"}
        events = [{"type": "response.created", "response": response([], "in_progress"), "sequence_number": 0},
                  {"type": "response.output_item.added", "output_index": 0, "item": tool, "sequence_number": 1},
                  {"type": "response.function_call_arguments.delta", "output_index": 0, "item_id": "fc_1",
                   "delta": '{"city":', "sequence_number": 2},
                  {"type": "response.function_call_arguments.delta", "output_index": 0, "item_id": "fc_1",
                   "delta": '"Moscow"}', "sequence_number": 3},
                  {"type": "response.output_item.done", "output_index": 0, "item": completed, "sequence_number": 4},
                  {"type": "response.completed", "response": response([completed]), "sequence_number": 5}]

        def handler(req):
            return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                                   content="".join("data: " + json.dumps(e) + "\n\n" for e in events))

        provider = self.openai(handler)
        try:
            results = [e async for e in provider.stream(request(tools=True))]
            self.assertEqual([e.type for e in results], ["tool_call", "completed"])
            self.assertEqual(results[0].tool_call.arguments(), {"city": "Moscow"})
            events[:] = [events[0], {"type": "response.incomplete", "sequence_number": 1,
                                     "response": response(status="incomplete")}]
            results = [e async for e in provider.stream(request())]
            self.assertEqual(results[-1].response.finish_reason, "length")
        finally:
            await provider.aclose()

    async def test_ollama_unsupported_tools_and_parallel_call_identity(self):
        provider = self.ollama(lambda _: httpx.Response(400, json={"error": "model does not support tools"}))
        try:
            with self.assertRaises(ProviderError) as caught:
                await provider.generate(request(tools=True))
            self.assertEqual(caught.exception.code, "unsupported")
        finally:
            await provider.aclose()
        calls = [{"function": {"name": "weather", "arguments": {"city": city}}} for city in ("Moscow", "Paris")]
        provider = self.ollama(
            lambda _: httpx.Response(200, json={"message": {"role": "assistant", "tool_calls": calls}, "done": True}))
        try:
            result = await provider.generate(request(tools=True))
            ids = [c.id for c in result.message.tool_calls]
            self.assertEqual(len(set(ids)), 2)
            # Never silently identify two calls to the same tool solely by its name.
            with self.assertRaises(ProviderError):
                await provider.generate(request([Message(role="user", text="Weather"), result.message,
                                                 Message(role="tool", tool_call_id=ids[1], text="Paris result"),
                                                 Message(role="tool", tool_call_id=ids[0], text="Moscow result")]))
        finally:
            await provider.aclose()

    async def test_errors_sanitized_and_not_retried(self):
        for kind in ("openai", "ollama"):
            for status, expected in [(401, "authentication"), (429, "rate_limit"), (404, "not_found"),
                                     (500, "server_error")]:
                count = 0

                def handler(req):
                    nonlocal count
                    count += 1
                    module = httpx2 if kind == "openai" else httpx
                    return module.Response(status, json={"error": "SECRET-test"})

                provider = self.openai(handler) if kind == "openai" else self.ollama(handler)
                try:
                    with self.assertRaises(ProviderError) as caught:
                        await provider.generate(request())
                    self.assertEqual(caught.exception.code, expected)
                    self.assertNotIn("SECRET", str(caught.exception))
                    self.assertEqual(count, 1)
                finally:
                    await provider.aclose()

    async def test_timeout_and_cancellation_close(self):
        def timeout(req):
            raise httpx.ReadTimeout("SECRET URL", request=req)

        provider = self.ollama(timeout)
        try:
            with self.assertRaises(ProviderError) as caught:
                await provider.generate(request())
            self.assertEqual(caught.exception.code, "timeout")
        finally:
            await provider.aclose()
        started = asyncio.Event()

        async def slow(req):
            started.set()
            await asyncio.Event().wait()

        provider = self.ollama(slow)
        job = asyncio.create_task(provider.generate(request()))
        await started.wait()
        closing = asyncio.create_task(provider.aclose())
        await asyncio.sleep(0)
        self.assertFalse(closing.done())
        job.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await job
        await closing
        self.assertTrue(provider.client._client.is_closed)

    async def test_incomplete_stream_malformed_arguments_and_invalid_tool_result(self):
        provider = self.ollama(lambda _: httpx.Response(200, content=json.dumps(
            {"message": {"role": "assistant", "content": "partial"}, "done": False})))
        try:
            with self.assertRaises(ProviderError) as caught:
                _ = [e async for e in provider.stream(request())]
            self.assertEqual(caught.exception.code, "protocol_error")
        finally:
            await provider.aclose()
        provider = self.openai(lambda _: httpx2.Response(200, json=response([
            {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "weather", "arguments": '{broken'}])))
        try:
            result = await provider.generate(request(tools=True))
            self.assertTrue(result.warnings)
            self.assertEqual(result.message.tool_calls[0].arguments_json, '{broken')
        finally:
            await provider.aclose()
        with self.assertRaises(ValidationError):
            request([Message(role="tool", tool_call_id="missing", text="no")])


class MemoryCredentials:
    def __init__(self): self.values = {}

    async def get(self, reference): return self.values.get(reference)

    async def set(self, reference, value): self.values[reference] = value

    async def delete(self, reference): del self.values[reference]


class ProviderSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = make_engine("sqlite+aiosqlite:///" + (Path(self.temp.name) / "llm.db").as_posix())
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.keys = MemoryCredentials()
        self.service = LLMProviderService(self.sessions, self.keys)

    async def asyncTearDown(self):
        await self.service.aclose()
        await self.engine.dispose()
        self.temp.cleanup()

    async def test_settings_keys_model_selection_and_restart(self):
        view = await self.service.save(
            ProviderCreate(id="local", kind="ollama", name="Local", base_url="http://localhost:11434",
                           api_key="SECRET"))
        self.assertTrue(view.has_api_key)
        self.assertNotIn("SECRET", view.model_dump_json())
        self.assertNotIn("SECRET", (Path(self.temp.name) / "llm.db").read_bytes().decode(errors="replace"))
        await self.service.select(ModelSelection(provider_id="local", model="qwen3:8b"))
        restarted = LLMProviderService(self.sessions, self.keys)
        self.assertEqual((await restarted.active()).model, "qwen3:8b")
        with self.assertRaises(ProviderError):
            await self.service.save(ProviderPatch(base_url="https://different.example"), "local")
        await self.service.save(ProviderPatch(name="Renamed"), "local")
        self.assertEqual(len(self.keys.values), 1)
        await self.service.save(ProviderPatch(api_key="NEW-SECRET"), "local")
        self.assertEqual(list(self.keys.values.values()), ["NEW-SECRET"])
        await self.service.delete("local")
        self.assertIsNone(await self.service.active())
        self.assertFalse(self.keys.values)
        await restarted.aclose()

    async def test_http_secret_redaction_and_local_only(self):
        app = create_app()
        app.state.llm_providers = self.service
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            data = {"id": "test", "kind": "openai", "name": "Test", "base_url": "https://api.openai.com/v1",
                    "api_key": "PRIVATE_KEY"}
            created = await client.post("/api/llm/providers", json=data)
            self.assertEqual(created.status_code, 201, created.text)
            self.assertNotIn("PRIVATE_KEY", created.text)
            invalid = await client.post("/api/llm/providers", json={**data, "name": " "})
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn("PRIVATE_KEY", invalid.text)
            self.assertNotIn("api_key", (await client.get("/api/llm/providers")).text.replace("has_api_key", ""))
            self.assertEqual(
                (await client.get("/api/llm/providers", headers={"origin": "https://evil.example"})).status_code, 403)
            self.assertEqual(
                (await client.put("/api/llm/active", json={"provider_id": "test", "model": "chosen"})).status_code, 200)
            self.assertEqual((await client.get("/api/llm/active")).json()["model"], "chosen")

    async def test_lease_releases_sql_and_shutdown_cancels_and_closes(self):
        await self.service.save(
            ProviderCreate(id="local", kind="ollama", name="Local", base_url="http://localhost:11434"))
        adapter = AsyncMock()
        self.service.factory = lambda config: adapter
        started = asyncio.Event()

        async def use():
            async with self.service.provider("local"):
                self.assertEqual(self.engine.pool.checkedout(), 0)
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(use())
        await started.wait()
        await self.service.aclose()
        self.assertTrue(task.cancelled())
        adapter.aclose.assert_awaited_once()

    async def test_failed_secret_write_and_duplicate_do_not_leave_records_or_keys(self):
        data = ProviderCreate(id="test", kind="openai", name="Test", base_url="https://api.openai.com/v1",
                              api_key="SECRET")
        original = self.keys.set
        self.keys.set = AsyncMock(side_effect=ProviderError("credential_store", "Unavailable"))
        with self.assertRaises(ProviderError):
            await self.service.save(data)
        self.assertEqual(await self.service.read_all(), [])
        self.keys.set = original
        await self.service.save(data)
        with self.assertRaises(ProviderError):
            await self.service.save(data)
        self.assertEqual(len(self.keys.values), 1)
