import uuid
from sqlalchemy import Column, DateTime, ForeignKey, String, Text, Uuid, Index, CheckConstraint
from sqlalchemy.orm import relationship

from backend.app.db import Base


class EventSeries(Base):
    __tablename__ = "event_series"

    __table_args__ = (
        Index(
            "ix_event_series_start",
            "start_at"
        ),
        CheckConstraint(
            "finish_at > start_at",
            name="ck_event_series_finish_after_start",
        )
    )

    id = Column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4
    )

    recurrence_rule_id = Column(
        Uuid,
        ForeignKey(
            "recurrence_rules.id",
            onupdate="CASCADE",
            ondelete="RESTRICT"
        ),
        nullable=True,
        unique=True
    )

    title = Column(
        String(255),
        nullable=False
    )

    description = Column(
        Text,
        nullable=True
    )

    start_at = Column(
        DateTime(timezone=True),
        nullable=False
    )

    finish_at = Column(
        DateTime(timezone=True),
        nullable=False
    )

    timezone = Column(
        String(64),
        nullable=False
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False
    )

    recurrence_rule = relationship(
        "RecurrenceRule"
    )

    exceptions = relationship(
        "EventException",
        back_populates="event_series"
    )