class CalendarError(Exception):
    pass


class InvalidCalendarData(CalendarError):
    pass


class CalendarNotFound(CalendarError):
    pass


class CalendarConflict(CalendarError):
    pass