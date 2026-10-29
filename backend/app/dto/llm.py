from pydantic import Field, SecretStr, model_validator
from backend.app.llm.schemas import Schema, ProviderConfig


class ProviderCreate(ProviderConfig):
    # Write-only input: the service always builds a separate public response.
    pass


class ProviderPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, max_length=2048)
    timeout: float | None = Field(default=None, gt=0, le=600, allow_inf_nan=False)
    connect_timeout: float | None = Field(default=None, gt=0, le=120, allow_inf_nan=False)
    api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)

    @model_validator(mode="after")
    def valid(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set - {"api_key"}):
            raise ValueError("Provide non-null fields; only api_key can be cleared")
        ProviderConfig(id="validation", kind="ollama", name=self.name or "Validation",
                       base_url=self.base_url or "http://localhost:11434")
        return self


class ProviderView(Schema):
    id: str
    kind: str
    name: str
    base_url: str
    timeout: float
    connect_timeout: float
    has_api_key: bool