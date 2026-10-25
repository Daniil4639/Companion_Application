import uuid
from sqlalchemy import Column, ForeignKey, String, Text, Uuid, Index, CheckConstraint, text
from sqlalchemy.orm import relationship
from backend.app.db.base import Base
from backend.app.db.types import UTCDateTime
from backend.app.utils.time import utc_now


class EventSeries(Base):

    __tablename__ = "event_series"
    __table_args__ = (
        Index("ix_event_series_start", "start_at"),
        CheckConstraint("finish_at > start_at", name="ck_event_series_finish_after_start"),
        CheckConstraint("length(trim(title)) BETWEEN 1 AND 255", name="ck_event_series_title"),
    )

    id = Column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4
    )

    recurrence_rule_id = Column(
        Uuid,
        ForeignKey("recurrence_rules.id", onupdate="CASCADE", ondelete="RESTRICT"),
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

    category = Column(
        String(32),
        nullable=False,
        default="default",
        server_default="default"
    )

    start_at = Column(
        UTCDateTime(),
        nullable=False
    )

    finish_at = Column(
        UTCDateTime(),
        nullable=False
    )

    timezone = Column(
        String(64),
        nullable=False
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

    recurrence_rule = relationship(
        "RecurrenceRule",
        lazy="raise"
    )

    exceptions = relationship(
        "EventException",
        back_populates="event_series",
        lazy="raise",
        passive_deletes="all"
    )