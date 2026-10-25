from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserCreate(BaseModel):

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    username: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    timezone: str = Field(min_length=1, max_length=64)
    timezone_mode: Literal["system", "manual"] = "system"
    locale: Literal["ru-RU"] = "ru-RU"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Укажите существующий часовой пояс IANA")
        return value

    @field_validator("display_name")
    @classmethod
    def empty_name(cls, value):
        return value or None


class UserPatch(UserCreate):

    username: str | None = Field(default=None, min_length=1, max_length=64)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    timezone_mode: Literal["system", "manual"] | None = None
    locale: Literal["ru-RU"] | None = None

    @model_validator(mode="before")
    @classmethod
    def required_not_null(cls, data):
        if isinstance(data, dict):
            for key in ("username", "timezone", "timezone_mode", "locale"):
                if key in data and data[key] is None:
                    raise ValueError(f"{key} не может быть null")
        return data


class UserResponse(UserCreate):

    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime