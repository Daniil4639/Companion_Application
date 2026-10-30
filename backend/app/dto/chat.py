from pydantic import Field, model_validator
from backend.app.llm.schemas import Schema


class ChatSettings(Schema):
    title: str = Field(default="Новый разговор", min_length=1, max_length=128)
    provider_id: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=255)
    system_prompt: str = Field(default="", max_length=100000)
    context_window_tokens: int = Field(default=8192, ge=1024, le=2000000)
    max_output_tokens: int = Field(default=2048, ge=1, le=1000000)

    @model_validator(mode="after")
    def valid(self):
        if not self.title.strip() or not self.model.strip():
            raise ValueError("Название и модель не могут быть пустыми")
        if self.max_output_tokens + 256 >= self.context_window_tokens:
            raise ValueError("Оставьте место для входного контекста и служебных данных")
        return self


class SendMessage(Schema):
    text: str = Field(min_length=1, max_length=200000)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")

    @model_validator(mode="after")
    def nonblank(self):
        if not self.text.strip():
            raise ValueError("Введите сообщение")
        return self