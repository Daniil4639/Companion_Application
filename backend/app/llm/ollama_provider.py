import json
from uuid import uuid4
from contextlib import aclosing
import httpx
from ollama import AsyncClient
from .base import ModelProvider
from .schemas import Continuation, Message, ModelInfo, ModelResponse, ProviderError, StreamEvent, ToolCall, Usage


class OllamaProvider(ModelProvider):
    def __init__(self, config, *, client=None):
        super().__init__(config)
        headers = {"Authorization": "Bearer " + config.api_key.get_secret_value()} if config.api_key else {}
        self.client = client or AsyncClient(host=config.base_url, headers=headers,
                                            timeout=httpx.Timeout(config.timeout, connect=config.connect_timeout))

    def _payload(self, request):
        self.validate(request)
        messages, names, pending = [], {}, []
        for message in request.messages:
            names.update({call.id: call.name for call in message.tool_calls})
            pending.extend(call.id for call in message.tool_calls)
            if message.continuation:
                messages.extend(message.continuation.items)
                continue
            item = {"role": message.role, "content": message.text}
            if message.role == "tool":
                # Ollama 0.6.3 uses tool_name on the wire, not OpenAI call_id.
                if not pending or pending.pop(0) != message.tool_call_id:
                    raise ProviderError("invalid_request", "Ollama tool results must follow assistant call order")
                item["tool_name"] = names[message.tool_call_id]
            if message.tool_calls:
                item["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments()}} for c in
                                      message.tool_calls]
            messages.append(item)
        options = {}
        if request.context_window_tokens is not None:
            options["num_ctx"] = request.context_window_tokens
        if request.selection.temperature is not None:
            options["temperature"] = request.selection.temperature
        if request.selection.max_output_tokens is not None:
            options["num_predict"] = request.selection.max_output_tokens
        return {"model": request.selection.model, "messages": messages, "options": options,
                "tools": [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                            "parameters": t.parameters}} for t in
                          request.tools] or None}

    def _normalize(self, raw, message, model):
        if not raw.get("done"):
            raise ProviderError("protocol_error", "Ollama stream ended before completion")
        calls = [ToolCall(id="ollama_" + uuid4().hex, name=c["function"]["name"],
                          arguments_json=json.dumps(c["function"]["arguments"], ensure_ascii=False))
                 for c in message.get("tool_calls", [])]
        continuation = Continuation(provider_id=self.config.id, kind="ollama", model=model,
                                    base_url=self.config.base_url, items=[message])
        return ModelResponse(provider_id=self.config.id, model=model,
                             message=Message(role="assistant", text=message.get("content", ""), tool_calls=calls,
                                             continuation=continuation),
                             finish_reason="length" if raw.get(
                                 "done_reason") == "length" else "tool_calls" if calls else "stop",
                             usage=Usage(input_tokens=raw.get("prompt_eval_count") or 0,
                                         output_tokens=raw.get("eval_count") or 0))

    async def generate(self, request):
        async with self.operation():
            raw = (await self.client.chat(**self._payload(request), stream=False)).model_dump(mode="json",
                                                                                              exclude_none=True)
            return self._normalize(raw, raw["message"], request.selection.model)

    async def stream(self, request):
        async with self.operation():
            message = {"role": "assistant", "content": "", "thinking": "", "tool_calls": []}
            final = None
            async with aclosing(await self.client.chat(**self._payload(request), stream=True)) as stream:
                async for chunk in stream:
                    raw = chunk.model_dump(mode="json", exclude_none=True)
                    delta = raw.get("message", {})
                    text = delta.get("content", "")
                    message["content"] += text
                    message["thinking"] += delta.get("thinking", "")
                    # Ollama emits complete calls in each chunk (not Responses JSON deltas).
                    message["tool_calls"].extend(delta.get("tool_calls", []))
                    if text:
                        yield StreamEvent(type="text_delta", text=text)
                    if raw.get("done"):
                        final = raw
            response = self._normalize(final or {}, message, request.selection.model)
            for call in response.message.tool_calls:
                yield StreamEvent(type="tool_call", tool_call=call)
            yield StreamEvent(type="completed", response=response)

    async def list_models(self):
        async with self.operation():
            result = await self.client.list()
            return [ModelInfo(id=model.model) for model in result.models if model.model]

    async def model_info(self, model):
        async with self.operation():
            info = await self.client.show(model)
            capabilities = info.model_dump().get("capabilities")
            metadata = info.model_dump().get("modelinfo") or {}
            context = next((v for k, v in metadata.items() if k.endswith(".context_length") and isinstance(v, int)),
                           None)
            return ModelInfo(id=model, context_window_tokens=context,
                             tools_supported="tools" in capabilities if capabilities is not None else None)

    async def _close_client(self):
        # Official ollama 0.6.3 has no public aclose; isolate this version-specific access here.
        await self.client._client.aclose()