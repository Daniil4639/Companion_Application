import asyncio
import logging
from contextlib import aclosing
from backend.app.llm.schemas import GenerationRequest, ModelSelection, ProviderError
from backend.app.config import character_helper_logger


class GenerationManager:
    """One process/worker. SSE observes snapshots; it never owns the producer task."""

    def __init__(self, service, providers, builder):
        self.service, self.providers, self.builder = service, providers, builder
        self.tasks, self.progress = {}, {}
        self.lock = asyncio.Lock()
        self.closing = False

    async def start(self, id, data):
        async with self.lock:
            if self.closing:
                raise ProviderError("closed", "Приложение завершает работу")
            run, settings, messages = await self.service.prepare(id, data, self.builder)
            if settings is not None:
                self.progress[run["id"]] = {"text": "", "status": "pending", "error": None}
                task = asyncio.create_task(self._generate(run, settings, messages), name="chat-" + run["id"])
                self.tasks[run["id"]] = task
            return run

    async def _generate(self, run, settings, messages):
        id = run["id"]
        state = self.progress[id]
        state["status"] = "running"

        async def checkpoint_loop():
            while True:
                await asyncio.sleep(3)
                await self.service.checkpoint(id, state["text"], "running")

        timer = None
        try:
            await self.service.checkpoint(id, "", "running")
            timer = asyncio.create_task(checkpoint_loop())
            request = GenerationRequest(selection=ModelSelection(provider_id=settings["provider_id"],
                                                                 model=settings["model"],
                                                                 max_output_tokens=settings["max_output_tokens"]),
                                        messages=messages, context_window_tokens=settings["context_window_tokens"])
            async with self.providers.provider(settings["provider_id"]) as provider:
                complete = False
                async with aclosing(provider.stream(request)) as stream:
                    async for event in stream:
                        if timer.done():
                            timer.result()
                        if event.type == "text_delta":
                            state["text"] += event.text or ""
                        elif event.type == "tool_call":
                            raise ProviderError("unsupported", "Вызовы инструментов пока не поддерживаются в чате")
                        elif event.type == "completed":
                            complete = True
                            state["text"] = event.response.message.text
                            if event.response.finish_reason == "length":
                                state["error"] = "Ответ достиг лимита токенов"
                if not complete:
                    raise ProviderError("protocol_error", "Поток завершился без подтверждения ответа")
            state["status"] = "completed"
        except asyncio.CancelledError:
            state["status"] = "interrupted" if self.closing else "cancelled"
        except Exception as exc:
            state["status"] = "failed"
            state["error"] = str(exc) if isinstance(exc, ProviderError) else "Не удалось завершить генерацию"
            character_helper_logger.warning("Chat generation failed (%s)", type(exc).__name__)
        finally:
            if timer:
                timer.cancel()
                await asyncio.gather(timer, return_exceptions=True)
            try:
                await self.service.checkpoint(id, state["text"], state["status"], state["error"])
            except Exception:
                character_helper_logger.exception("Chat final checkpoint failed")
                # Keep the in-memory snapshot; startup recovery handles unfinished DB state.
            else:
                self.progress.pop(id, None)
            self.tasks.pop(id, None)

    async def snapshot(self, id):
        saved = await self.service.snapshot(id)
        return {**saved, **self.progress.get(id, {})}

    async def cancel(self, id):
        async with self.lock:
            await self.service.snapshot(id)
            task = self.tasks.get(id)
            if task and not task.done():
                # Let a freshly-created task enter its try/finally before cancellation.
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return await self.snapshot(id)

    async def aclose(self):
        async with self.lock:
            self.closing = True
            await asyncio.sleep(0)
            tasks = list(self.tasks.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)