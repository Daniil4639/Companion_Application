import json
import httpx2
from openai import AsyncOpenAI
from .base import ModelProvider
from .schemas import (Continuation, Message, ModelInfo, ModelResponse, ProviderError,
                      StreamEvent, ToolCall, Usage)


class OpenAIProvider(ModelProvider):
    def __init__(self, config, *, client=None):
        super().__init__(config)
        if client is None and not config.api_key:
            raise ProviderError("authentication", "OpenAI API key is not configured")
        self.client = client or AsyncOpenAI(api_key=config.api_key.get_secret_value(), base_url=config.base_url,
            timeout=httpx2.Timeout(config.timeout, connect=config.connect_timeout), max_retries=0)

    def _payload(self, request):
        self.validate(request)
        items = []
        for message in request.messages:
            if message.continuation:
                items.extend(message.continuation.items)
            elif message.role == "tool":
                items.append({"type": "function_call_output", "call_id": message.tool_call_id, "output": message.text})
            else:
                if message.text:
                    items.append({"role": message.role, "content": message.text})
                items.extend({"type": "function_call", "call_id": c.id, "name": c.name,
                              "arguments": c.arguments_json} for c in message.tool_calls)
        payload = {"model": request.selection.model, "input": items, "store": False,
                   "include": ["reasoning.encrypted_content"]}
        if request.tools:
            # Do not silently rewrite users' JSON schemas to satisfy strict mode.
            payload["tools"] = [{"type": "function", "name": t.name, "description": t.description,
                                 "parameters": t.parameters, "strict": False} for t in request.tools]
        for key in ("temperature", "max_output_tokens"):
            if (value := getattr(request.selection, key)) is not None:
                payload[key] = value
        return payload

    def _normalize(self, response, model):
        raw = response.model_dump(mode="json", exclude_none=True)
        if raw.get("status") not in ("completed", "incomplete"):
            raise ProviderError("server_error", "Provider did not complete the response")
        texts, calls, warnings, refusal = [], [], [], False
        for item in raw.get("output", []):
            if item["type"] == "message":
                for content in item.get("content", []):
                    if content["type"] == "output_text":
                        texts.append(content["text"])
                    elif content["type"] == "refusal":
                        texts.append(content.get("refusal", ""))
                        refusal = True
            elif item["type"] == "function_call":
                call = ToolCall(id=item["call_id"], name=item["name"], arguments_json=item["arguments"])
                try:
                    call.arguments()
                except (ValueError, json.JSONDecodeError):
                    warnings.append("Tool arguments are not a JSON object; do not execute without validation")
                calls.append(call)
        continuation = Continuation(provider_id=self.config.id, kind="openai", model=model,
                                    base_url=self.config.base_url, items=raw.get("output", []))
        usage = raw.get("usage") or {}
        reason = "refusal" if refusal else "tool_calls" if calls else "stop"
        if raw.get("status") == "incomplete":
            reason = "length" if (raw.get("incomplete_details") or {}).get("reason") == "max_output_tokens" else "other"
            warnings.append("Response is incomplete; inspect finish_reason before using tool calls")
        return ModelResponse(provider_id=self.config.id, model=model, response_id=raw.get("id"),
            message=Message(role="assistant", text="".join(texts), tool_calls=calls, continuation=continuation),
            finish_reason=reason, warnings=warnings,
            usage=Usage(input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0)))

    async def generate(self, request):
        async with self.operation():
            response = await self.client.responses.create(**self._payload(request))
            return self._normalize(response, request.selection.model)

    async def stream(self, request):
        async with self.operation():
            async with self.client.responses.stream(**self._payload(request)) as stream:
                incomplete = None
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        yield StreamEvent(type="text_delta", text=event.delta)
                    elif event.type == "response.incomplete":
                        incomplete = event.response
                    elif event.type in ("error", "response.failed"):
                        raise ProviderError("server_error", "Provider stream failed")
                response = self._normalize(incomplete or await stream.get_final_response(), request.selection.model)
                # Calls are emitted only after completion, never from partial JSON deltas.
                for call in response.message.tool_calls:
                    yield StreamEvent(type="tool_call", tool_call=call)
                yield StreamEvent(type="completed", response=response)

    async def list_models(self):
        async with self.operation():
            return [ModelInfo(id=model.id) async for model in self.client.models.list()]

    async def _close_client(self):
        await self.client.close()
