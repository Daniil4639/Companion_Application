from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from backend.app.mcp_client.models import MCPServerConfig, MCPConnectionStatus


class MCPServerCreate(MCPServerConfig):
    bearer_token: str | None = Field(default=None, repr=False, exclude=True, max_length=4096)


class MCPServerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str | None = Field(None, min_length=1, max_length=128)
    url: str | None = Field(None, repr=False)
    connect_timeout: float | None = Field(None, gt=0, le=300, allow_inf_nan=False)
    operation_timeout: float | None = Field(None, gt=0, le=600, allow_inf_nan=False)
    bearer_token: str | None = Field(None, repr=False, exclude=True, max_length=4096)

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field")
        if any(getattr(self, key) is None for key in self.model_fields_set if key != "bearer_token"):
            raise ValueError("Connection fields cannot be null")
        # Reuse runtime validation, including URL rules and whitespace-only names.
        MCPServerConfig.model_validate({"id": "validation", "name": "Validation", "url": "http://localhost/mcp",
                                        **self.model_dump(exclude_unset=True, exclude={"bearer_token"})})
        return self


class MCPServerResponse(MCPServerConfig):
    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True, hide_input_in_errors=True)

    is_internal: bool
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def has_token(self) -> bool:
        return self.credential_ref is not None

    def connection_config(self):
        return MCPServerConfig.model_validate({**self.model_dump(include=set(MCPServerConfig.model_fields)),
                                               "credential_ref": self.credential_ref})
