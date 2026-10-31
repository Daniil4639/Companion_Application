import asyncio
import unittest
import test_chat
from uuid import uuid4
from sqlalchemy import select
from mcp.server import MCPServer
from backend.app.models.chat import ChatMessage, Conversation, ConversationSummary
from backend.app.services.conversation_summary import SummaryService
from backend.app.services.chat_generation import GenerationManager
from backend.app.dto.chat import SendMessage
from backend.app.llm.schemas import Message, ModelResponse, ProviderError
from backend.app.mcp_adapter.chat_reading import register_chat_tools


class SummaryModel:
    def __init__(self, fail_at=None):
        self.requests = []
        self.fail_at = fail_at

    async def generate(self, request):
        self.requests.append(request)
        if len(self.requests) == self.fail_at:
            raise ProviderError("timeout", "mock")
        return ModelResponse(provider_id="local", model="test", message=Message(role="assistant",
                                                                                text="Факты: решили сохранить историю. Открытый вопрос: сроки."))


class SummaryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_chat.ChatTests.asyncSetUp
    asyncTearDown = test_chat.ChatTests.asyncTearDown

    async def seed(self, count=6, length=1500):
        async with self.sessions() as s:
            async with s.begin():
                rows = (await s.scalars(
                    select(ChatMessage).where(ChatMessage.conversation_id == self.chat["id"]).order_by(
                        ChatMessage.position))).all()
                pos = rows[-1].position + 1 if rows else 0
                for i in range(count):
                    for role in ("user", "assistant"):
                        s.add(ChatMessage(id=uuid4().hex, conversation_id=self.chat["id"], role=role,
                                          text=role + " " + str(pos) + " " + ("x" * length), status="completed",
                                          position=pos, provider_id="local", model="test"))
                        pos += 1

    async def test_incremental_boundary_and_failure(self):
        await self.seed()
        service = SummaryService(self.service, self.builder, threshold=.75, keep=2)
        model = SummaryModel()
        state = {}
        self.assertTrue(await service.after_answer(self.chat["id"], model, state))
        first = await service.get(self.chat["id"])
        self.assertEqual(first["last_summarized_position"], 7)
        self.assertGreater(len(model.requests), 1)
        for request in model.requests:
            size = sum(self.builder.counter.count(m) for m in request.messages)
            self.assertLessEqual(size, request.context_window_tokens - request.selection.max_output_tokens - 256)
            self.assertEqual(request.tools, [])
        async with self.sessions() as s:
            c = await s.get(Conversation, self.chat["id"])
            summary = await s.get(ConversationSummary, c.id)
            history = (await s.scalars(
                select(ChatMessage).where(ChatMessage.conversation_id == c.id).order_by(ChatMessage.position))).all()
            context = self.builder.build(c, history, "next", summary)
            self.assertEqual(context[1].role, "user")
            self.assertIn(first["content"], context[1].text)
            self.assertFalse(any(m.text.startswith("user 0 ") for m in context))
        await self.seed(count=3)
        bad = SummaryModel(fail_at=2)
        with self.assertRaises(ProviderError):
            await service.after_answer(self.chat["id"], bad, {})
        self.assertEqual(await service.get(self.chat["id"]), first)
        newer = SummaryModel()
        await service.after_answer(self.chat["id"], newer, {})
        second = await service.get(self.chat["id"])
        self.assertEqual(second["last_summarized_position"], 13)
        self.assertIn(first["content"], newer.requests[0].messages[1].text)
        history = await self.service.messages(self.chat["id"], limit=100)
        self.assertEqual(len(history["items"]), 18)

    async def test_small_history_no_summary_and_mcp(self):
        await self.seed(count=2, length=20)
        summaries = SummaryService(self.service, self.builder)
        self.assertFalse(await summaries.after_answer(self.chat["id"], SummaryModel(), {}))
        server = MCPServer("Chat test")
        register_chat_tools(server, self.sessions)
        tools = await server.list_tools()
        self.assertEqual({t.name for t in tools}, {"chat_list", "chat_get_summary", "chat_read_messages"})
        result = await server.call_tool("chat_list", {})
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["items"][0]["has_summary"], False)
        result = await server.call_tool("chat_get_summary", {"conversation_id": self.chat["id"]})
        self.assertFalse(result.structured_content["exists"])
        result = await server.call_tool("chat_read_messages", {"conversation_id": self.chat["id"], "limit": 2})
        page = result.structured_content
        self.assertEqual([m["position"] for m in page["items"]], [2, 3])
        next_page = await server.call_tool("chat_read_messages",
                                           {"conversation_id": self.chat["id"], "before": page["next_before"],
                                            "limit": 2})
        self.assertEqual([m["position"] for m in next_page.structured_content["items"]], [0, 1])
        # Server's tool boundary surfaces invalid access as an error.
        try:
            missing = await server.call_tool("chat_read_messages", {"conversation_id": "missing"})
        except Exception:
            pass
        else:
            self.assertTrue(missing.is_error)
        async with self.sessions() as s:
            boundary = await s.scalar(
                select(ChatMessage).where(ChatMessage.conversation_id == self.chat["id"], ChatMessage.position == 1))
        await summaries.save(self.chat["id"], "Saved facts", boundary.id)
        result = await server.call_tool("chat_get_summary", {"conversation_id": self.chat["id"]})
        self.assertEqual(result.structured_content["content"], "Saved facts")
        self.assertEqual(result.structured_content["last_summarized_position"], 1)
        await self.service.delete(self.chat["id"])
        async with self.sessions() as s:
            self.assertIsNone(await s.get(ConversationSummary, self.chat["id"]))

    async def test_provider_busy_and_post_answer(self):
        second = await self.service.save(self.settings)
        run, _, _ = await self.service.prepare(self.chat["id"], SendMessage(text="Hi", request_id="busy"), self.builder)
        with self.assertRaises(ProviderError):
            await self.service.prepare(second["id"], SendMessage(text="Hi", request_id="other"), self.builder)
        await self.service.checkpoint(run["id"], "Done", "completed")

        class CheckSummary:
            async def after_answer(inner, id, provider, state, tool_bytes):
                history = await self.service.messages(id)
                self.assertEqual(history["items"][-1]["status"], "completed")
                self.assertEqual(state["text"], "Привет")
                state["phase"] = "summarizing"
                raise ProviderError("timeout", "mock")

        self.manager = GenerationManager(self.service, self.providers, self.builder, summaries=CheckSummary())
        run = await self.manager.start(second["id"], SendMessage(text="Hello", request_id="new"))
        await self.manager.tasks[run["id"]]
        result = await self.manager.snapshot(run["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["text"], "Привет")
        self.assertIn("Сжатие истории не удалось", result["error"])

    async def test_long_message_fragments(self):
        await self.seed(count=1, length=6000)
        first = await self.service.read_visible_messages(self.chat["id"], limit=1)
        item = first["items"][0]
        self.assertTrue(item["truncated"])
        second = await self.service.read_visible_messages(self.chat["id"], before=item["position"] + 1, limit=1,
                                                          text_offset=item["next_text_offset"])
        self.assertIsNone(second["items"][0]["next_text_offset"])
        full = (await self.service.messages(self.chat["id"], limit=1))["items"][0]["text"]
        self.assertEqual(item["text"] + second["items"][0]["text"], full)