from enum import Enum


class RecurrenceFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class EventExceptionStatus(str, Enum):
    MODIFIED = "modified"
    CANCELLED = "cancelled"