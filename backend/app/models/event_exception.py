import uuid
from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, Uuid, Index
from sqlalchemy.orm import relationship
from backend.app.db import Base
from backend.app.utils import EventExceptionStatus


class EventException(Base):
    __tablename__ = "event_exceptions"

    __table_args__ = (
        UniqueConstraint(
            "event_series_id",
            "original_start_at",
            name="uq_event_exception_occurrence"
        ),
        Index(
            "ix_event_exceptions_series_id",
            "event_series_id"
        )
    )

    id = Column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4
    )

    event_series_id = Column(
        Uuid,
        ForeignKey(
            "event_series.id",
            onupdate="CASCADE",
            ondelete="RESTRICT"
        ),
        nullable=False
    )

    original_start_at = Column(
        DateTime(timezone=True),
        nullable=False
    )

    status = Column(
        Enum(
            EventExceptionStatus,
            name="event_exception_status",
            native_enum=False
        ),
        nullable=False
    )

    start_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    finish_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    title = Column(
        String(255),
        nullable=True
    )

    description = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False
    )

    event_series = relationship(
        "EventSeries",
        back_populates="exceptions"
    )