from datetime import datetime
from typing import Iterable

from dateutil.rrule import (DAILY, WEEKLY, MONTHLY, YEARLY,
                            FR, MO, SA, SU, TH, TU, WE,
                            rrule)

from backend.app.utils import RecurrenceFrequency
from backend.app.models import RecurrenceRule


WEEKDAY_MAP = {
    "MO": MO,
    "TU": TU,
    "WE": WE,
    "TH": TH,
    "FR": FR,
    "SA": SA,
    "SU": SU,
}


FREQUENCY_MAP = {
    RecurrenceFrequency.DAILY: DAILY,
    RecurrenceFrequency.WEEKLY: WEEKLY,
    RecurrenceFrequency.MONTHLY: MONTHLY,
    RecurrenceFrequency.YEARLY: YEARLY,
}


def generate_occurrences(
    start_at: datetime,
    recurrence_rule: RecurrenceRule,
    range_start: datetime,
    range_end: datetime
) -> Iterable[datetime]:

    kwargs = {
        "freq": FREQUENCY_MAP[recurrence_rule.frequency],
        "dtstart": start_at,
        "interval": recurrence_rule.interval,
        "count": recurrence_rule.count,
        "until": recurrence_rule.until,
    }

    if recurrence_rule.by_weekday:
        kwargs["byweekday"] = [
            WEEKDAY_MAP[value]
            for value in recurrence_rule.by_weekday
        ]

    if recurrence_rule.by_monthday:
        kwargs["bymonthday"] = recurrence_rule.by_monthday

    if recurrence_rule.by_month:
        kwargs["bymonth"] = recurrence_rule.by_month

    rule = rrule(**kwargs)

    return rule.between(
        range_start,
        range_end,
        inc=True,
    )