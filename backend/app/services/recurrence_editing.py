"""Pure recurrence plans and their atomic persistence; no MCP dependencies."""
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from backend.app.db.session import write_transaction
from backend.app.dto.events import EventCreate, RecurrenceRuleCreate
from backend.app.dto.recurrence_editing import RecurrenceChange, SeriesSplit, RecurrenceResult, RecurrencePreview
from backend.app.dto.schedule import ScheduleOccurrenceResponse
from backend.app.models import EventSeries, RecurrenceRule
from backend.app.services.calendar import calendarService, validate, timestamp, render_schedule, MAX_RANGE_DAYS, \
    MAX_SCHEDULE_ITEMS
from backend.app.services.calendar_editing import calendarEditingService
from backend.app.services.errors import InvalidCalendarData, CalendarConflict, CalendarNotFound
from backend.app.services.recurrence import generate_occurrences
from backend.app.utils.time import utc_now


@dataclass
class RecurrencePlan:
    events: list
    discarded: list
    transferred: list
    warnings: list


def originals(event, start, end):
    return generate_occurrences(event.start_at, event.recurrence_rule, start, end, event.timezone)


def after_instant(value):
    try:
        return value + timedelta(microseconds=1)
    except OverflowError as exc:
        raise InvalidCalendarData("Date is too close to datetime limits") from exc


def check_anchor(event):
    # Validate the rule, interval and IANA zone through the existing DTO first.
    validate(EventCreate, {k: getattr(event, k) for k in EventCreate.model_fields})
    if originals(event, event.start_at, after_instant(event.start_at)) != [event.start_at]:
        raise InvalidCalendarData("DTSTART must match the new recurrence rule; supply a matching start_at")


def select_exceptions(exceptions, target, policy):
    if not exceptions:
        return [], []
    if policy == "reject":
        raise CalendarConflict("Exceptions exist; explicitly choose preserve or discard")
    if policy == "discard":
        return [], [e.id for e in exceptions]
    if len(exceptions) > MAX_SCHEDULE_ITEMS:
        raise InvalidCalendarData("Too many exceptions")
    starts = {e.original_start_at for e in exceptions}
    valid = set(originals(target, min(starts), after_instant(max(starts))))
    if not starts <= valid:
        raise CalendarConflict("Cannot preserve exceptions whose ORIGINAL starts no longer match the rule")
    return exceptions, []


def plan_change(before, data):
    """Build a complete plan without a session, SQL, or mutation of the input."""
    if before.recurrence_rule is None:
        raise InvalidCalendarData("This operation requires a recurring series")
    split = isinstance(data, SeriesSplit)
    data = validate(SeriesSplit if split else RecurrenceChange, data)
    target = before.model_copy(deep=True)
    history = None
    warnings = []
    affected = target.exceptions
    if split:
        boundary = data.original_start_at
        if originals(before, boundary, after_instant(boundary)) != [boundary]:
            raise CalendarNotFound("Split boundary is not an original occurrence")
        prior = originals(before, before.start_at, boundary)
        if not prior:
            raise InvalidCalendarData("Cannot split at the first occurrence; use schedule_update_recurrence")
        history = before.model_copy(deep=True)
        history.recurrence_rule = validate(RecurrenceRuleCreate, {
            **history.recurrence_rule.model_dump(), "count": len(prior), "until": None})
        history.exceptions = [e for e in history.exceptions if e.original_start_at < boundary]
        affected = [e for e in affected if e.original_start_at >= boundary]
        target.id, target.recurrence_rule_id = uuid4(), uuid4()
        start = data.start_at or boundary
        if start < boundary:
            raise InvalidCalendarData("New series start must not precede the split boundary")
        if data.recurrence_rule is None and before.recurrence_rule.count is not None:
            target.recurrence_rule = validate(RecurrenceRuleCreate, {
                **target.recurrence_rule.model_dump(), "count": before.recurrence_rule.count - len(prior)})
            warnings.append("Inherited COUNT is the number of remaining original occurrences, including cancelled ones")
        if any(e.start_at and e.start_at >= boundary for e in history.exceptions):
            warnings.append("Historical exceptions moved past the boundary remain attached to the historical series")
    else:
        start = data.start_at or before.start_at
        warnings.append("The replacement rule applies to the entire series, including its past")
    if data.recurrence_rule is not None:
        target.recurrence_rule = validate(RecurrenceRuleCreate, data.recurrence_rule.model_dump())
    try:
        target.start_at = start
        target.finish_at = start + (before.finish_at - before.start_at)
    except OverflowError as exc:
        raise InvalidCalendarData("Duration exceeds datetime range") from exc
    check_anchor(target)
    target.exceptions, discarded = select_exceptions(affected, target, data.exception_policy)
    if discarded:
        warnings.append(f"Explicit discard policy removes {len(discarded)} exception(s)")
    events = [history, target] if history else [target]
    return RecurrencePlan(events, discarded, [e.id for e in target.exceptions] if split else [], warnings)


async def persist_plan(before, plan, session):
    """Apply a validated plan under the caller's writer reservation."""
    stored = await calendarService.get_event_details(before.id, session)
    historical = plan.events[0]
    now = utc_now()
    for key in ("start_at", "finish_at"):
        setattr(stored, key, getattr(historical, key))
    for key, value in historical.recurrence_rule.model_dump().items():
        setattr(stored.recurrence_rule, key, value)
    stored.updated_at = now
    if len(plan.events) == 2:
        future = plan.events[1]
        new_series = EventSeries(
            **future.model_dump(
                include={"id", "title", "description", "category", "start_at", "finish_at", "timezone"}),
            recurrence_rule=RecurrenceRule(id=future.recurrence_rule_id, **future.recurrence_rule.model_dump()),
            created_at=now, updated_at=now)
        session.add(new_series)
        await session.flush()
    for exception in list(stored.exceptions):
        if exception.id in plan.discarded:
            await session.delete(exception)
        elif exception.id in plan.transferred:
            exception.event_series_id = plan.events[1].id
            exception.updated_at = now
    await session.flush()


async def change_recurrence(event_series_id, expected_version, data, session):
    async with write_transaction(session):
        before = await calendarEditingService._checked(event_series_id, expected_version, session)
        plan = plan_change(before, data)
        await persist_plan(before, plan, session)
        return RecurrenceResult(event_series_id=event_series_id,
                                outcome="split" if len(plan.events) == 2 else "recurrence_updated",
                                series=[await calendarEditingService.get(e.id, session) for e in plan.events],
                                changed_fields=["recurrence_rule", "start_at", "finish_at", "exceptions"],
                                discarded_exception_ids=plan.discarded, transferred_exception_ids=plan.transferred,
                                warnings=plan.warnings)


async def restore_occurrence(event_series_id, original_start_at, expected_version, session):
    original = timestamp(original_start_at)
    async with write_transaction(session):
        before = await calendarEditingService._checked(event_series_id, expected_version, session)
        if before.recurrence_rule is None:
            raise InvalidCalendarData("Restoration requires a recurring series")
        await calendarService.restore_occurrence(event_series_id, original, session)
        exists = any(e.original_start_at == original for e in before.exceptions)
        return RecurrenceResult(event_series_id=event_series_id, outcome="restored",
                                series=[await calendarEditingService.get(event_series_id, session)],
                                changed_fields=["exceptions"] if exists else [],
                                warnings=[] if exists else ["Occurrence already follows its series rule"])


async def preview_change(event_series_id, expected_version, data, range_start, range_end, session):
    start, end = timestamp(range_start), timestamp(range_end)
    if end <= start or end - start > timedelta(days=MAX_RANGE_DAYS):
        raise InvalidCalendarData("Preview range must be positive and no longer than 366 days")
    before = await calendarEditingService._checked(event_series_id, expected_version, session)
    plan = plan_change(before, data)

    def render(events):
        if sum(len(e.exceptions) for e in events) > MAX_SCHEDULE_ITEMS:
            raise InvalidCalendarData("Too many exceptions for preview")
        rows = render_schedule(events, {e.id: {x.original_start_at: x for x in e.exceptions} for e in events}, start,
                               end)
        return [ScheduleOccurrenceResponse.model_validate({k: getattr(r, k) for k in r.__dataclass_fields__}) for r in
                rows]

    return RecurrencePreview(event_series_id=event_series_id, version=expected_version, range_start=start,
                             range_end=end,
                             before=render([before]), after=render(plan.events),
                             proposed_events=[calendarEditingService.snapshot(e) for e in plan.events],
                             discarded_exception_ids=plan.discarded, transferred_exception_ids=plan.transferred,
                             warnings=plan.warnings + [
                                 "Preview only: new-series IDs and proposed versions are provisional; use the original version to apply"])
