import asyncio
import unittest
import test_chat
from contextlib import asynccontextmanager
from backend.app.services.agent_runner import AgentRunner
from backend.app.services.agent_store import AgentStore
from backend.app.services.chat_generation import GenerationManager
from backend.app.llm.schemas import Message, ToolCall, StreamEvent, ModelResponse
from backend.app.mcp_client.models import RegisteredTool, ExecutionResult, RuntimeFailure
from backend.app.dto.chat import SendMessage
from backend.app.models.mcp_server import MCPServerRecord


class FakeMCP:
    def __init__(self, read=True):
        self.tool = RegisteredTool(id="folliant.demo", server_id="folliant", name="demo",
                                   description="Demo", input_schema={"type": "object", "properties": {}},
                                   output_schema=None,
                                   annotations={"readOnlyHint": read, "destructiveHint": False})
        self.registry = self
        self.calls = 0
        self.failure = False
        self.payload = "ok"

    async def connect(self, id):
        if self.failure: raise RuntimeFailure("connection_error", "offline")

    async def refresh_tools(self, id): pass

    def list(self, id): return [self.tool]

    def get(self, id): return self.tool.model_copy(deep=True)

    async def execute(self, id, args):
        self.calls += 1
        return ExecutionResult(tool_id=id, status="success", result={"text": self.payload})


class Model:
    def __init__(self, rounds=1, parallel=1):
        self.rounds, self.parallel = rounds, parallel
        self.requests = []

    @asynccontextmanager
    async def provider(self, id): yield self

    async def stream(self, request):
        self.requests.append(request.model_copy(deep=True))
        i = len(self.requests)
        calls = []
        if i <= self.rounds and request.tools:
            calls = [ToolCall(id=f"call_{i}_{j}", name=request.tools[0].name, arguments_json="{}") for j in
                     range(self.parallel)]
        response = ModelResponse(provider_id="local", model="test",
                                 message=Message(role="assistant", text="" if calls else "Done", tool_calls=calls),
                                 finish_reason="tool_calls" if calls else "stop")
        yield StreamEvent(type="completed", response=response)


class AgentTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_chat.ChatTests.asyncSetUp
    asyncTearDown = test_chat.ChatTests.asyncTearDown

    async def setup_agent(self, read=True, rounds=1, parallel=1, max_steps=8):
        async with self.sessions() as s:
            async with s.begin():
                s.add(MCPServerRecord(id="folliant", name="Local", url="http://127.0.0.1:8181/mcp",
                                      transport="streamable_http", connect_timeout=10, operation_timeout=30,
                                      is_internal=True))
        self.chat = await self.service.save(
            self.settings.model_copy(update={"mcp_servers": ["folliant"], "context_window_tokens": 64000}),
            self.chat["id"])
        self.mcp = FakeMCP(read)
        self.model = Model(rounds, parallel)
        self.store = AgentStore(self.sessions)
        self.agent = AgentRunner(self.mcp, self.mcp, self.store, self.builder, max_steps, {"folliant"})
        self.manager = GenerationManager(self.service, self.model, self.builder, self.agent)

    async def start(self):
        run = await self.manager.start(self.chat["id"], SendMessage(text="Help", request_id="agent"))
        return run, self.manager.tasks[run["id"]]

    async def waiting(self, run):
        for _ in range(200):
            rows = await self.store.list(run["id"])
            if rows and rows[-1]["status"] == "waiting_approval": return rows[-1]
            await asyncio.sleep(.01)
        self.fail("Approval never appeared")

    async def test_parallel_and_sequential_history(self):
        await self.setup_agent(rounds=2, parallel=2)
        run, task = await self.start()
        await task
        self.assertEqual(self.mcp.calls, 4)
        self.assertEqual((await self.manager.snapshot(run["id"]))["status"], "completed")
        self.assertEqual((await self.manager.snapshot(run["id"]))["text"], "Done")
        self.assertEqual(len(await self.store.list(run["id"])), 4)
        _, _, context = await self.service.prepare(self.chat["id"], SendMessage(text="Next", request_id="next"),
                                                   self.builder)
        calls = {c.id for m in context for c in m.tool_calls}
        results = {m.tool_call_id for m in context if m.role == "tool"}
        self.assertEqual(calls, results)
        self.assertEqual(len(calls), 4)

    async def test_approval(self):
        await self.setup_agent(read=False)
        run, task = await self.start()
        row = await self.waiting(run)
        self.assertEqual(self.mcp.calls, 0)
        await self.store.decision(run["id"], row["id"], True)
        await task
        self.assertEqual(self.mcp.calls, 1)

    async def test_denied(self):
        await self.setup_agent(read=False)
        run, task = await self.start()
        row = await self.waiting(run)
        await self.store.decision(run["id"], row["id"], False)
        await task
        self.assertEqual(self.mcp.calls, 0)
        self.assertIn("permission_denied", self.model.requests[-1].messages[-1].text)

    async def test_cancel_waiting(self):
        await self.setup_agent(read=False)
        run, task = await self.start()
        row = await self.waiting(run)
        await self.manager.cancel(run["id"])
        self.assertEqual(self.mcp.calls, 0)
        self.assertEqual((await self.store.get(row["id"]))["status"], "cancelled")

    async def test_offline_plain_chat(self):
        await self.setup_agent()
        self.mcp.failure = True
        run, task = await self.start()
        await task
        self.assertEqual(self.mcp.calls, 0)
        self.assertEqual((await self.manager.snapshot(run["id"]))["status"], "completed")

    async def test_step_limit_and_large_result(self):
        await self.setup_agent(rounds=10, max_steps=2)
        self.mcp.payload = "long result" * 100000
        run, task = await self.start()
        await task
        self.assertEqual(self.mcp.calls, 2)
        self.assertEqual((await self.manager.snapshot(run["id"]))["status"], "failed")
        self.assertIn("truncated", self.model.requests[-1].messages[-1].text)

    async def test_untrusted_annotations_require_approval(self):
        await self.setup_agent()
        self.agent.trusted_read_servers = set()
        run, task = await self.start()
        row = await self.waiting(run)
        self.assertEqual(self.mcp.calls, 0)
        await self.manager.cancel(run["id"])

    async def test_unknown_result_not_retried(self):
        await self.setup_agent()

        async def timeout(id, args):
            self.mcp.calls += 1
            return ExecutionResult(tool_id=id, status="timeout")

        self.mcp.execute = timeout
        run, task = await self.start()
        await task
        self.assertEqual(self.mcp.calls, 1)
        self.assertEqual((await self.store.list(run["id"]))[0]["status"], "unknown")
        self.assertEqual((await self.manager.snapshot(run["id"]))["status"], "failed")