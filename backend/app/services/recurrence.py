from datetime import timedelta
from dateutil.rrule import DAILY, WEEKLY, MONTHLY, YEARLY, MO, TU, WE, TH, FR, SA, SU, rrule
from backend.app.utils import RecurrenceFrequency
from backend.app.utils.time import as_utc, zone
from .errors import InvalidCalendarData


WEEKDAY_MAP = dict(zip(("MO", "TU", "WE", "TH", "FR", "SA", "SU"), (MO, TU, WE, TH, FR, SA, SU)))
FREQUENCY_MAP = {RecurrenceFrequency.DAILY: DAILY, RecurrenceFrequency.WEEKLY: WEEKLY,
                 RecurrenceFrequency.MONTHLY: MONTHLY, RecurrenceFrequency.YEARLY: YEARLY}
MAX_SCANNED_OCCURRENCES = 100000


def generate_occurrences(start_at, recurrence_rule, range_start, range_end, timezone="UTC"):
    """Return original UTC starts in [range_start, range_end).
    
    Wall-clock recurrence, gaps skipped, folds use the first instant (except an
    explicitly supplied DTSTART). COUNT counts real occurrences. Duration is
    handled by CalendarService as elapsed time.
    """

    start_at, range_start, range_end = map(as_utc, (start_at, range_start, range_end))

    if range_end <= range_start:
        return []

    local_start = start_at.astimezone(zone(timezone))
    tz = local_start.tzinfo

    try:
        wall_end = range_end.astimezone(tz).replace(tzinfo=None) + timedelta(days=2)

    except OverflowError as exc:
        raise InvalidCalendarData("Date range is too close to datetime limits") from exc

    kwargs = dict(freq=FREQUENCY_MAP[recurrence_rule.frequency],
                  dtstart=local_start.replace(tzinfo=None, microsecond=0),
                  interval=recurrence_rule.interval, until=wall_end)

    if recurrence_rule.by_weekday:
        kwargs["byweekday"] = [WEEKDAY_MAP[value] for value in recurrence_rule.by_weekday]

    if recurrence_rule.by_monthday:
        kwargs["bymonthday"] = recurrence_rule.by_monthday

    if recurrence_rule.by_month:
        kwargs["bymonth"] = recurrence_rule.by_month

    count = 0
    result = []

    for scanned, wall in enumerate(rrule(**kwargs), 1):
        if scanned > MAX_SCANNED_OCCURRENCES:
            raise InvalidCalendarData("Recurrence exceeds the 100000 occurrence scan limit")

        wall = wall.replace(microsecond=local_start.microsecond)
        fold = local_start.fold if wall == local_start.replace(tzinfo=None) else 0
        local = wall.replace(tzinfo=tz, fold=fold)
        instant = as_utc(local)

        if instant.astimezone(tz).replace(tzinfo=None) != wall:
            continue

        if recurrence_rule.until is not None and instant > as_utc(recurrence_rule.until):
            break

        count += 1
        if recurrence_rule.count is not None and count > recurrence_rule.count:
            break

        if instant >= range_end:
            break

        if instant >= range_start:
            result.append(instant)

    return result