"""Provider-neutral text/tool contract. Continuation data is opaque to callers."""
import json
from typing import Any, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ProviderConfig(Schema):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: Literal["openai", "ollama"]
    name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(max_length=2048)
    timeout: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)
    connect_timeout: float = Field(default=10, gt=0, le=120, allow_inf_nan=False)
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
                or url.query or url.fragment or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError("Use HTTP(S) without credentials, query or fragment")
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError("Invalid port")
        return value.rstrip("/")

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


class ModelSelection(Schema):
    provider_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    model: str = Field(min_length=1, max_length=255)
    temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    max_output_tokens: int | None = Field(default=None, gt=0, le=1000000)

    @field_validator("model")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Model cannot be blank")
        return value.strip()


class ToolDefinition(Schema):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str = ""
    parameters: dict[str, Any]


class ToolCall(Schema):
    id: str
    name: str
    arguments_json: str  # Keep even malformed JSON for an explicit tool error later.

    def arguments(self) -> dict[str, Any]:
        value = json.loads(self.arguments_json)
        if not isinstance(value, dict):
            raise ValueError("Tool arguments must be an object")
        return value


class Continuation(Schema):
    provider_id: str
    kind: Literal["openai", "ollama"]
    model: str
    base_url: str
    items: list[dict[str, Any]] = Field(repr=False)


class Message(Schema):
    role: Literal["system", "user", "assistant", "tool"]
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    continuation: Continuation | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def consistent(self):
        if (self.role == "tool") != bool(self.tool_call_id):
            raise ValueError("Only tool messages require tool_call_id")
        if self.role != "assistant" and (self.tool_calls or self.continuation):
            raise ValueError("Only assistant messages can contain calls/continuation")
        return self


class GenerationRequest(Schema):
    context_window_tokens: int | None = Field(default=None, ge=1024, le=2000000)
    selection: ModelSelection
    messages: list[Message] = Field(min_length=1)
    tools: list[ToolDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_calls(self):
        calls, answered = {}, set()
        for message in self.messages:
            for call in message.tool_calls:
                if call.id in calls:
                    raise ValueError("Duplicate tool_call_id")
                calls[call.id] = call
            if message.role == "tool":
                if message.tool_call_id not in calls or message.tool_call_id in answered:
                    raise ValueError("Tool result must reference one preceding unanswered call")
                answered.add(message.tool_call_id)
        if len({tool.name for tool in self.tools}) != len(self.tools):
            raise ValueError("Duplicate tool names")
        return self


class Usage(Schema):
    input_tokens: int = 0
    output_tokens: int = 0


class ModelResponse(Schema):
    provider_id: str
    model: str
    response_id: str | None = None
    message: Message
    finish_reason: Literal["stop", "tool_calls", "length", "refusal", "other"] = "stop"
    usage: Usage = Field(default_factory=Usage)
    warnings: list[str] = Field(default_factory=list)


class StreamEvent(Schema):
    type: Literal["text_delta", "tool_call", "completed"]
    text: str | None = None
    tool_call: ToolCall | None = None
    response: ModelResponse | None = None


class ModelInfo(Schema):
    context_window_tokens: int | None = None
    id: str
    tools_supported: bool | None = None
    streaming_supported: bool | None = None


class ProviderError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code, self.status = code, status

    def details(self):
        return {"code": self.code, "message": str(self), "upstream_status": self.status}