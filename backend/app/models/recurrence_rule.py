import uuid
from sqlalchemy import Column, Enum, Integer, JSON, Uuid, CheckConstraint
from backend.app.db.base import Base
from backend.app.db.types import UTCDateTime
from backend.app.utils import RecurrenceFrequency


class RecurrenceRule(Base):

    __tablename__ = "recurrence_rules"
    __table_args__ = (
        CheckConstraint("frequency IN ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY')", name="recurrence_frequency"),
        CheckConstraint("interval > 0", name="ck_recurrence_rule_interval_positive"),
        CheckConstraint("count IS NULL OR count > 0", name="ck_recurrence_rule_count_positive"),
        CheckConstraint("NOT (count IS NOT NULL AND until IS NOT NULL)", name="ck_recurrence_rule_count_until_exclusive"),
    )

    id = Column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4
    )

    frequency = Column(
        Enum(RecurrenceFrequency, name="recurrence_frequency", native_enum=False, validate_strings=True),
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
        UTCDateTime(),
        nullable=True
    )

    count = Column(
        Integer,
        nullable=True
    )