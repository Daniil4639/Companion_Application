import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import httpx
import httpx2
import openai
import ollama
from .schemas import GenerationRequest, ModelResponse, StreamEvent, ModelInfo, ProviderError


def classify(exc):
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx2.TimeoutException, openai.APITimeoutError)):
        return ProviderError("timeout", "Provider request timed out")
    if isinstance(exc, (ConnectionError, OSError, httpx.TransportError, httpx2.TransportError, openai.APIConnectionError)):
        return ProviderError("connection_error", "Cannot connect to provider")
    status = getattr(exc, "status_code", None)
    if isinstance(exc, (openai.APIStatusError, ollama.ResponseError)):
        if status in (401, 403):
            return ProviderError("authentication", "Provider rejected credentials or access", status)
        if status == 429:
            return ProviderError("rate_limit", "Provider rate limit exceeded", status)
        if status == 404:
            return ProviderError("not_found", "Provider endpoint or model not found", status)
        if status == 400 and "does not support" in str(exc).lower():
            return ProviderError("unsupported", "Model does not support the requested capability", status)
        return ProviderError("invalid_request" if status and status < 500 else "server_error",
                             "Provider rejected the request", status)
    return ProviderError("protocol_error", "Provider returned an invalid or incomplete response")


class ModelProvider(ABC):
    """One serial async lane per adapter; close drains the active operation.

    Consumers must use contextlib.aclosing on stream() if they may stop early.
    Cancellation propagates as CancelledError, never as a successful partial reply.
    """
    def __init__(self, config):
        self.config = config
        self._lock = asyncio.Lock()
        self._closing = False
        self._closed = False

    @asynccontextmanager
    async def operation(self):
        async with self._lock:
            if self._closing:
                raise ProviderError("closed", "Provider is closing or closed")
            try:
                yield
            except Exception as exc:
                raise classify(exc) from None

    def validate(self, request):
        if request.selection.provider_id != self.config.id:
            raise ProviderError("invalid_request", "Selection belongs to another provider")
        for message in request.messages:
            c = message.continuation
            if c and (c.provider_id != self.config.id or c.kind != self.config.kind or c.model != request.selection.model
                      or c.base_url != self.config.base_url):
                raise ProviderError("invalid_request", "Continuation belongs to another provider or model")

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> ModelResponse: ...

    @abstractmethod
    def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]: ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    async def check(self) -> list[ModelInfo]:
        return await self.list_models()

    async def aclose(self):
        self._closing = True
        async with self._lock:
            if not self._closed:
                await self._close_client()
                self._closed = True

    @abstractmethod
    async def _close_client(self): ...
