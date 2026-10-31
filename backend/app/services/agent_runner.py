"""Provider-neutral bounded tool loop. No HTTP/SSE or concrete tool names."""
import asyncio
import hashlib
import json
from contextlib import aclosing
from types import SimpleNamespace
from backend.app.llm.schemas import Message, ToolDefinition, ProviderError
from backend.app.mcp_client.models import RuntimeFailure


def bounded(value, limit=24000):
    raw = json.dumps(value, ensure_ascii=False, default=str)
    if len(raw.encode("utf-8")) <= limit:
        return raw
    prefix = raw.encode("utf-8")[:max(0, limit - 200)].decode("utf-8", errors="ignore")
    return json.dumps({"truncated": True, "notice": "Result shortened; request narrower data.", "preview": prefix},
                      ensure_ascii=False)


class AgentRunner:
    def __init__(self, manager, executor, store, builder, max_steps=8, trusted_read_servers=()):
        self.manager, self.executor, self.store, self.builder = manager, executor, store, builder
        self.max_steps, self.trusted_read_servers = max_steps, set(trusted_read_servers)

    def approval_required(self, tool):
        hints = tool.annotations or {}
        return not (tool.server_id in self.trusted_read_servers and hints.get("readOnlyHint") is True
                    and hints.get("destructiveHint") is not True)

    async def discover(self, server_ids):
        tools = {}
        for server_id in dict.fromkeys(server_ids):
            try:
                await self.manager.connect(server_id)
                await self.manager.refresh_tools(server_id)
            except (RuntimeFailure, KeyError):
                continue
            for tool in self.manager.registry.list(server_id):
                if tool.available:
                    alias = "mcp_" + hashlib.sha256(tool.id.encode()).hexdigest()[:40]
                    tools[alias] = tool
        return tools

    def fit(self, request, protected_start, protected_prefix=1):
        budget = request.context_window_tokens - request.selection.max_output_tokens - 256

        def size():
            return sum(self.builder.counter.count(m) for m in request.messages) + len(
                json.dumps([t.model_dump() for t in request.tools], ensure_ascii=False).encode())

        # Drop oldest whole user exchanges, never active call/result groups.
        while size() > budget and protected_start > protected_prefix:
            end = next((i for i in range(protected_prefix + 1, protected_start) if request.messages[i].role == "user"),
                       protected_start)
            del request.messages[protected_prefix:end]
            protected_start -= end - protected_prefix
        if size() > budget:
            raise ProviderError("invalid_request",
                                "Инструкции, инструменты и текущий обмен не помещаются в контекст. Увеличьте окно или подключите меньше MCP.")
        return protected_start

    async def run(self, run_id, settings, request, provider, state):
        tools = await self.discover(settings.get("mcp_servers", []))
        request.tools = [ToolDefinition(name=alias, description=t.description or "", parameters=t.input_schema) for
                         alias, t in tools.items()]
        state["tool_schema_bytes"] = len(
            json.dumps([t.model_dump() for t in request.tools], ensure_ascii=False).encode())
        transcript = []
        protected = len(request.messages) - 1
        for step in range(self.max_steps):
            previous_text = state["text"]
            protected = self.fit(request, protected, settings.get("_context_prefix", 1))
            state["phase"] = "generating"
            await self.store.phase(run_id, "generating")
            response = None

            async def stream_once():
                nonlocal response
                async with aclosing(provider.stream(request)) as stream:
                    async for event in stream:
                        if event.type == "text_delta":
                            state["text"] += event.text or ""
                        elif event.type == "completed":
                            response = event.response

            try:
                await stream_once()
            except ProviderError as exc:
                if exc.code != "unsupported" or step or not request.tools:
                    raise
                # No tools have executed: safe text-only fallback.
                request.tools = []
                tools = {}
                state["text"] = ""
                await stream_once()
            if response is None:
                raise ProviderError("protocol_error", "Поток завершился без итогового ответа")
            message = response.message
            state["text"] = previous_text + message.text
            if message.tool_calls and response.finish_reason not in ("tool_calls", "stop"):
                raise ProviderError("protocol_error", "Неполный ответ с вызовами инструментов: выполнение остановлено")
            if len(message.tool_calls) > 16:
                raise ProviderError("invalid_request", "Слишком много вызовов за один шаг")
            transcript.append(message)
            request.messages.append(message)
            if not message.tool_calls:
                await self.store.transcript(run_id, transcript)
                if response.finish_reason == "length":
                    state["error"] = "Ответ достиг лимита токенов"
                return
            for call in message.tool_calls:
                audited = False
                tool = tools.get(call.name)
                result = {"status": "unknown_tool"}
                if tool is not None:
                    try:
                        args = call.arguments()
                        if len(call.arguments_json.encode()) > 32000:
                            raise ValueError()
                    except (ValueError, TypeError):
                        result = {"status": "invalid_arguments", "message": "Expected a bounded JSON object"}
                    else:
                        approval = self.approval_required(tool)
                        row = await self.store.create(run_id, call.id, tool, args, approval)
                        audited = True
                        sent = False
                        try:
                            if approval:
                                state["phase"] = "waiting_approval"
                                await self.store.phase(run_id, "waiting_approval")
                                while (await self.store.get(row["id"]))["status"] == "waiting_approval":
                                    await asyncio.sleep(.25)
                            decision = await self.store.get(row["id"])
                            if decision["status"] == "denied":
                                result = {"status": "permission_denied",
                                          "message": "User rejected this action; do not retry it."}
                                await self.store.finish(row["id"], "denied", result)
                            else:
                                current = self.manager.registry.get(tool.id)
                                if current != tool:
                                    raise ProviderError("conflict",
                                                        "Описание инструмента изменилось. Запросите действие заново.")
                                state["phase"] = "tool_running"
                                await self.store.phase(run_id, "tool_running")
                                await self.store.finish(row["id"], "running")
                                sent = True
                                result = (await self.executor.execute(tool.id, args)).model_dump(mode="json")
                                uncertain = result["status"] in ("connection_error", "timeout", "protocol_error")
                                await self.store.finish(row["id"], "unknown" if uncertain else "completed" if result[
                                                                                                                  "status"] == "success" else "failed",
                                                        json.loads(bounded(result, 64000)))
                                if uncertain:
                                    raise ProviderError("unknown_outcome",
                                                        "Результат MCP-операции неизвестен. Проверьте данные перед повтором.")
                        except asyncio.CancelledError:
                            await self.store.finish(row["id"], "unknown" if sent else "cancelled",
                                                    {
                                                        "message": "Operation may have reached the server; verify before retrying."} if sent else None)
                            raise
                        except Exception:
                            current_row = await self.store.get(row["id"])
                            if current_row["status"] in ("approved", "running", "waiting_approval"):
                                await self.store.finish(row["id"], "unknown" if sent else "failed")
                            raise
                if not audited:
                    unknown = tool or SimpleNamespace(server_id="", name=call.name[:255])
                    row = await self.store.create(run_id, call.id, unknown,
                                                  {"invalid_arguments_preview": call.arguments_json[:1000]}, False)
                    await self.store.finish(row["id"], "failed", result)
                result_message = Message(role="tool", tool_call_id=call.id,
                                         text=bounded(result, min(12000, max(512, (
                                                     request.context_window_tokens - request.selection.max_output_tokens) // 4))))
                request.messages.append(result_message)
                transcript.append(result_message)
            await self.store.transcript(run_id, transcript)
            state["text"] += "\n\n" if state["text"] else ""
        raise ProviderError("step_limit",
                            "Достигнут лимит шагов агента. Выполненные операции сохранены; автоматического повтора нет.")