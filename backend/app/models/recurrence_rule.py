import uuid

from sqlalchemy import Column, DateTime, Enum, Integer, JSON, Uuid, CheckConstraint

from backend.app.db import Base
from backend.app.utils import RecurrenceFrequency


class RecurrenceRule(Base):
    __tablename__ = "recurrence_rules"

    __table_args__ = (
        CheckConstraint(
            "interval > 0",
            name="ck_recurrence_rule_interval_positive",
        ),
        CheckConstraint(
            "count IS NULL OR count > 0",
            name="ck_recurrence_rule_count_positive",
        ),
        CheckConstraint(
            "NOT (count IS NOT NULL AND until IS NOT NULL)",
            name="ck_recurrence_rule_count_until_exclusive",
        ),
    )

    id = Column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4
    )

    frequency = Column(
        Enum(
            RecurrenceFrequency,
            name="recurrence_frequency",
            native_enum=False
        ),
        nullable=False
    )

    interval = Column(
        Integer,
        nullable=False,
        default=1
    )

    by_weekday = Column(
        JSON,
        nullable=True
    )

    by_monthday = Column(
        JSON,
        nullable=True
    )

    by_month = Column(
        JSON,
        nullable=True
    )

    until = Column(
        DateTime(timezone=True),
        nullable=True
    )

    count = Column(
        Integer,
        nullable=True
    )