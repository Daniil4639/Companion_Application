import uuid
from sqlalchemy import Column, String, Text, Integer, Date, Uuid, CheckConstraint, UniqueConstraint, Index
from backend.app.db.base import Base
from backend.app.db.types import UTCDateTime
from backend.app.utils.time import utc_now


class Task(Base):

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("length(trim(title)) BETWEEN 1 AND 255", name="ck_task_title"),
        CheckConstraint("status IN ('BACKLOG','TODO','IN_PROGRESS','DONE')", name="ck_task_status"),
        CheckConstraint("priority IN ('Low','Medium','High')", name="ck_task_priority"),
        CheckConstraint("position >= 0", name="ck_task_position"),
        CheckConstraint("(status = 'DONE' AND completed_at IS NOT NULL) OR (status != 'DONE' AND completed_at IS NULL)", name="ck_task_completion"),
        UniqueConstraint("status", "position", name="uq_task_status_position"),
        Index("ix_task_scheduled_date", "scheduled_date"),
        Index("ix_task_due_date", "due_date"),
    )

    id = Column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4
    )

    title = Column(
        String(255),
        nullable=False
    )

    description = Column(
        Text,
        nullable=True
    )

    status = Column(
        String(16),
        nullable=False,
        default="BACKLOG"
    )

    priority = Column(
        String(6),
        nullable=False,
        default="Medium"
    )

    position = Column(
        Integer,
        nullable=False
    )

    scheduled_date = Column(
        Date,
        nullable=True
    )

    due_date = Column(
        Date,
        nullable=True
    )

    created_at = Column(
        UTCDateTime(),
        nullable=False,
        default=utc_now
    )

    updated_at = Column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now
    )

    completed_at = Column(
        UTCDateTime(),
        nullable=True
    )