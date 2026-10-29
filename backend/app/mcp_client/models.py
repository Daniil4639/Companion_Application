from typing import Any, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True
    )

    id: str = Field(
        pattern=r"^[A-Za-z0-9_-]{1,64}$"
    )

    name: str = Field(
        min_length=1,
        max_length=128
    )

    transport: Literal["streamable_http"] = "streamable_http"

    url: str = Field(
        repr=False,
        max_length=2048
    )

    connect_timeout: float = Field(
        default=10,
        gt=0,
        le=300,
        allow_inf_nan=False
    )

    operation_timeout: float = Field(
        default=30,
        gt=0,
        le=600,
        allow_inf_nan=False
    )

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()

    @field_validator("url")
    @classmethod
    def http_endpoint(cls, value):
        if len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Invalid HTTP URL")
        parsed = urlsplit(value)

        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
            raise ValueError("Use an HTTP(S) URL without credentials, query or fragment")

        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("Invalid port")

        return value


class RegisteredTool(BaseModel):
    id: str
    server_id: str
    name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    annotations: dict[str, Any] | None
    available: bool = True


class ExecutionResult(BaseModel):
    tool_id: str
    status: Literal["success", "tool_error", "protocol_error", "connection_error", "timeout",
    "invalid_arguments", "unknown_tool", "unavailable", "permission_denied"]
    # Full SDK result (all content block types, structuredContent, metadata), not text extraction.
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class RuntimeFailure(Exception):
    def __init__(self, kind, message, protocol_code=None):
        super().__init__(message)
        self.kind = kind
        self.protocol_code = protocol_code

    def details(self):
        return {
            "code": self.kind,
            "message": str(self),
            "protocol_code": self.protocol_code
        }


class MCPConnectionStatus(BaseModel):
    server_id: str
    state: Literal["disconnected", "connecting", "connected", "closing"]
    available_tools: int
    last_error: dict | None = None