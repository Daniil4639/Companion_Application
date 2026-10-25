from datetime import date, datetime
from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskStatus(StrEnum):

    BACKLOG = "BACKLOG"
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class TaskPriority(StrEnum):

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class TaskCreate(BaseModel):

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    status: TaskStatus = TaskStatus.BACKLOG
    priority: TaskPriority = TaskPriority.MEDIUM
    position: int | None = Field(default=None, ge=0, strict=True)
    scheduled_date: date | None = None
    due_date: date | None = None

    @field_validator("scheduled_date", "due_date", mode="before")
    @classmethod
    def date_only(cls, value):
        if value is None or type(value) is date:
            return value
        if isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() == value:
                    return parsed
            except ValueError:
                pass
        raise ValueError("Use a calendar date YYYY-MM-DD without a time")

    @field_validator("description")
    @classmethod
    def empty_description(cls, value):
        return value or None


class TaskPatch(TaskCreate):

    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null(cls, data):
        if isinstance(data, dict):
            for key in ("title", "status", "priority", "position"):
                if key in data and data[key] is None:
                    raise ValueError(f"{key} cannot be null")
        return data


class TaskMove(BaseModel):

    model_config = ConfigDict(extra="forbid")
    status: TaskStatus
    position: int = Field(ge=0, strict=True)


class TaskResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    position: int
    scheduled_date: date | None
    due_date: date | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None