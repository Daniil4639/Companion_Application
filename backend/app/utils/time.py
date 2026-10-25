from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc_now():
    return datetime.now(UTC)


def as_utc(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must include a UTC offset")

    try:
        return value.astimezone(UTC)

    except OverflowError as exc:
        raise ValueError("Datetime is outside the supported UTC range") from exc


def zone(name):
    try:
        return ZoneInfo(name)

    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("Unknown IANA timezone") from exc