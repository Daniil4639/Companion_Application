import uuid
from sqlalchemy import Column, Enum, ForeignKey, String, Text, UniqueConstraint, Uuid, Index, CheckConstraint, text
from sqlalchemy.orm import relationship
from backend.app.db.base import Base
from backend.app.db.types import UTCDateTime
from backend.app.utils import EventExceptionStatus
from backend.app.utils.time import utc_now


class EventException(Base):

    __tablename__ = "event_exceptions"
    __table_args__ = (
        UniqueConstraint("event_series_id", "original_start_at", name="uq_event_exception_occurrence"),
        Index("ix_event_exceptions_series_id", "event_series_id"),
        Index("ix_event_exceptions_start", "start_at"),
        CheckConstraint("status IN ('MODIFIED', 'CANCELLED')", name="event_exception_status"),
        CheckConstraint(
            "(status = 'CANCELLED' AND start_at IS NULL AND finish_at IS NULL) OR "
            "(status = 'MODIFIED' AND start_at IS NOT NULL AND finish_at IS NOT NULL AND finish_at > start_at)",
            name="ck_event_exception_state"),
    )

    id = Column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4
    )

    event_series_id = Column(
        Uuid,
        ForeignKey("event_series.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False
    )

    original_start_at = Column(
        UTCDateTime(),
        nullable=False
    )

    status = Column(
        Enum(EventExceptionStatus, name="event_exception_status", native_enum=False, validate_strings=True),
        nullable=False
    )

    start_at = Column(
        UTCDateTime(),
        nullable=True
    )

    finish_at = Column(
        UTCDateTime(),
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
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP")
    )

    updated_at = Column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP")
    )

    event_series = relationship(
        "EventSeries",
        back_populates="exceptions",
        lazy="raise"
    )