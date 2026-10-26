import os
os.environ["COMPANION_LOAD_DOTENV"] = "0"

import hashlib
import asyncio
import unittest
from datetime import datetime, timedelta, UTC
from pathlib import Path
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from mcp import Client
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
import test_mcp
from backend.app.dto.calendar_editing import EventDetails, ExceptionDetails
from backend.app.dto.events import RecurrenceRuleCreate
from backend.app.dto.recurrence_editing import RecurrenceChange, SeriesSplit
from backend.app.services.recurrence_editing import plan_change, originals
from backend.app.services.errors import InvalidCalendarData, CalendarConflict


def dt(value):
    return datetime.fromisoformat(value)


def fixture(start="2026-10-24T07:00:00Z", count=5, **rule):
    start = dt(start)
    return EventDetails(id=uuid4(), title="Lesson", description="Base", category="default",
        start_at=start, finish_at=start + timedelta(hours=1), timezone="Europe/Berlin",
        recurrence_rule_id=uuid4(), recurrence_rule=RecurrenceRuleCreate(frequency="daily", count=count, **rule),
        created_at=start, updated_at=start, exceptions=[])


class RecurrencePlans(unittest.TestCase):
    def test_until_and_unbounded_split_preserve_originals(self):
        for until in (None, dt("2026-11-03T08:00:00Z")):
            before = fixture(count=None, until=until, interval=2)
            plan = plan_change(before, SeriesSplit(original_start_at="2026-10-28T08:00:00Z"))
            self.assertEqual(plan.events[1].recurrence_rule.until, until)
            self.assertIsNone(plan.events[1].recurrence_rule.count)
            end = dt("2026-11-10T00:00:00Z")
            self.assertEqual([o for e in plan.events for o in originals(e, before.start_at, end)],
                             originals(before, before.start_at, end))

    def test_count_split_and_input_immutability(self):
        before = fixture()
        copy = before.model_dump()
        plan = plan_change(before, SeriesSplit(original_start_at="2026-10-26T08:00:00Z"))
        self.assertEqual([e.recurrence_rule.count for e in plan.events], [2, 3])
        end = dt("2026-11-01T00:00:00Z")
        combined = [o for e in plan.events for o in originals(e, before.start_at, end)]
        self.assertEqual(combined, originals(before, before.start_at, end))
        self.assertEqual(before.model_dump(), copy)

    def test_dst_gap_count_is_real_occurrences(self):
        before = fixture("2026-03-28T01:30:00Z", count=4)
        plan = plan_change(before, SeriesSplit(original_start_at="2026-03-30T00:30:00Z"))
        self.assertEqual([e.recurrence_rule.count for e in plan.events], [1, 3])
        after = originals(plan.events[1], dt("2026-03-28T00:00:00Z"), dt("2026-04-04T00:00:00Z"))
        self.assertEqual(len(after), 3)
        self.assertEqual(after[0], dt("2026-03-30T00:30:00Z"))

    def test_anchor_rule_and_strict_validation(self):
        before = fixture()
        with self.assertRaises(InvalidCalendarData):
            plan_change(before, RecurrenceChange(recurrence_rule={"frequency": "weekly", "by_weekday": ["MO"]}))
        for rule in ({"frequency": "daily", "count": 2, "until": "2026-11-01T00:00:00Z"},
                     {"frequency": "daily", "interval": True}, {"frequency": "daily", "count": "3"},
                     {"frequency": "weekly", "by_weekday": ["NO"]}, {"frequency": "monthly", "by_monthday": [0]}):
            with self.assertRaises(ValidationError):
                RecurrenceChange(recurrence_rule=rule)
        with self.assertRaises(InvalidCalendarData):
            plan_change(before, SeriesSplit(original_start_at=before.start_at))
        with self.assertRaises(InvalidCalendarData):
            plan_change(before, SeriesSplit(original_start_at="2026-10-26T08:00:00Z", start_at=before.start_at))

    def test_exception_policies_no_silent_drop(self):
        before = fixture()
        before.exceptions = [ExceptionDetails(id=uuid4(), original_start_at=dt("2026-10-26T08:00:00Z"),
            status="cancelled", start_at=None, finish_at=None, title=None, description=None,
            created_at=before.created_at, updated_at=before.updated_at)]
        for policy in ("reject", "preserve"):
            with self.assertRaises(CalendarConflict):
                plan_change(before, RecurrenceChange(recurrence_rule={"frequency": "daily", "count": 1}, exception_policy=policy))
        plan = plan_change(before, RecurrenceChange(recurrence_rule={"frequency": "daily", "count": 1}, exception_policy="discard"))
        self.assertEqual(plan.discarded, [before.exceptions[0].id])
        self.assertEqual(plan.events[0].exceptions, [])


class RecurrenceMCP(unittest.IsolatedAsyncioTestCase):
    running = test_mcp.MCPIntegration.running
    mcp_ok = test_mcp.MCPIntegration.mcp_ok
    assert_connections_returned = test_mcp.MCPIntegration.assert_connections_returned

    async def create(self, rest, **overrides):
        response = await rest.post("/api/events", json={"title": "Lesson", "description": "Base",
            "start_at": "2026-10-24T09:00:00+02:00", "finish_at": "2026-10-24T10:00:00+02:00",
            "timezone": "Europe/Berlin", "recurrence_rule": {"frequency": "daily", "count": 5}, **overrides})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    async def test_rule_days_until_and_stale_version(self):
        async with self.running() as (_, _, rest, base):
            eid = await self.create(rest, start_at="2026-10-26T09:00:00+01:00", finish_at="2026-10-26T10:00:00+01:00")
            async with Client(base + "/mcp") as client:
                snap = await self.mcp_ok(client, "schedule_get", event_series_id=eid)
                args = {"event_series_id": eid, "expected_version": snap["version"], "data": {
                    "recurrence_rule": {"frequency": "weekly", "by_weekday": ["MO", "WE"], "until": "2026-11-04T09:00:00+01:00"}}}
                updated = await self.mcp_ok(client, "schedule_update_recurrence", **args)
                self.assertTrue((await client.call_tool("schedule_update_recurrence", args)).is_error)
                rows = (await rest.get("/api/schedule", params={"range_start": "2026-10-26T00:00:00Z", "range_end": "2026-11-10T00:00:00Z"})).json()["occurrences"]
                self.assertEqual([r["start_at"][:10] for r in rows], ["2026-10-26", "2026-10-28", "2026-11-02", "2026-11-04"])
                args["expected_version"] = updated["series"][0]["version"]
                args["data"]["recurrence_rule"]["until"] = "2026-10-28T08:00:00Z"
                final = await self.mcp_ok(client, "schedule_update_recurrence", **args)
                self.assertEqual(final["series"][0]["event"]["recurrence_rule"]["until"], "2026-10-28T08:00:00Z")

    async def test_split_preview_preserves_history_count_exceptions(self):
        async with self.running() as (_, engine, rest, base):
            eid = await self.create(rest)
            # Historical original moved into future, future original cancelled.
            await rest.post(f"/api/events/{eid}/occurrences/2026-10-24T07:00:00Z/move", json={
                "start_at": "2026-10-30T09:00:00Z", "finish_at": "2026-10-30T10:00:00Z"})
            await rest.post(f"/api/events/{eid}/occurrences/2026-10-27T08:00:00Z/cancel")
            async with Client(base + "/mcp") as client:
                snap = await self.mcp_ok(client, "schedule_get", event_series_id=eid)
                args = {"event_series_id": eid, "expected_version": snap["version"],
                        "data": {"original_start_at": "2026-10-26T08:00:00Z"}}
                self.assertTrue((await client.call_tool("schedule_split_series", args)).is_error)
                args["data"]["exception_policy"] = "preserve"
                window = {"range_start": "2026-10-23T00:00:00Z", "range_end": "2026-11-02T00:00:00Z"}
                path = Path(engine.url.database)
                before_bytes = hashlib.sha256(path.read_bytes()).hexdigest()
                sql = []
                def capture(conn, cursor, statement, parameters, context, executemany):
                    sql.append(statement)
                event.listen(engine.sync_engine, "before_cursor_execute", capture)
                try:
                    preview = await self.mcp_ok(client, "schedule_preview_change", **args, **window)
                finally:
                    event.remove(engine.sync_engine, "before_cursor_execute", capture)
                self.assertFalse(any(s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE", "SAVEPOINT")) for s in sql), sql)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before_bytes)
                self.assertEqual(await self.mcp_ok(client, "schedule_get", event_series_id=eid), snap)
                result = await self.mcp_ok(client, "schedule_split_series", **args)
                old, new = result["series"]
                self.assertEqual([s["event"]["recurrence_rule"]["count"] for s in result["series"]], [2, 3])
                self.assertEqual(old["event"]["exceptions"][0], snap["event"]["exceptions"][0])
                self.assertEqual(new["event"]["exceptions"][0]["original_start_at"], "2026-10-27T08:00:00Z")
                self.assertEqual(len(result["transferred_exception_ids"]), 1)
                rows = (await rest.get("/api/schedule", params=window)).json()["occurrences"]
                def content(items):
                    return sorted([{k: v for k, v in r.items() if k != "event_series_id"} for r in items], key=lambda x: x["start_at"])
                self.assertEqual(content(rows), content(preview["after"]))
                self.assertEqual(content(rows), content(preview["before"]))
                self.assertTrue((await client.call_tool("schedule_split_series", args)).is_error)
                self.assertEqual(len((await rest.get("/api/events")).json()), 2)
            await self.assert_connections_returned(engine)

    async def test_explicit_discard_shift_and_transaction_rollback(self):
        from backend.app.services import recurrence_editing
        async with self.running() as (_, _, rest, base):
            eid = await self.create(rest)
            await rest.post(f"/api/events/{eid}/occurrences/2026-10-27T08:00:00Z/cancel")
            async with Client(base + "/mcp") as client:
                snap = await self.mcp_ok(client, "schedule_get", event_series_id=eid)
                args = {"event_series_id": eid, "expected_version": snap["version"], "data": {
                    "original_start_at": "2026-10-26T08:00:00Z", "start_at": "2026-10-26T12:00:00Z",
                    "recurrence_rule": {"frequency": "daily", "count": 2}, "exception_policy": "preserve"}}
                self.assertTrue((await client.call_tool("schedule_split_series", args)).is_error)
                args["data"]["exception_policy"] = "discard"
                original = recurrence_editing.persist_plan
                async def fail_after_flush(*a, **kw):
                    await original(*a, **kw)
                    raise OperationalError("SECRET", {}, Exception("SECRET"))
                with patch.object(recurrence_editing, "persist_plan", AsyncMock(side_effect=fail_after_flush)):
                    self.assertTrue((await client.call_tool("schedule_split_series", args)).is_error)
                self.assertEqual(await self.mcp_ok(client, "schedule_get", event_series_id=eid), snap)
                self.assertEqual(len((await rest.get("/api/events")).json()), 1)
                result = await self.mcp_ok(client, "schedule_split_series", **args)
                self.assertEqual(len(result["discarded_exception_ids"]), 1)
                self.assertEqual(result["series"][1]["event"]["start_at"], "2026-10-26T12:00:00Z")

    async def test_restore_modified_cancelled_and_aba_protection(self):
        async with self.running() as (_, _, rest, base):
            eid = await self.create(rest)
            async with Client(base + "/mcp") as client:
                initial = await self.mcp_ok(client, "schedule_get", event_series_id=eid)
                for action in ("cancel", "move"):
                    kw = {} if action == "cancel" else {"json": {"start_at": "2026-11-01T08:00:00Z", "finish_at": "2026-11-01T09:00:00Z"}}
                    await rest.post(f"/api/events/{eid}/occurrences/2026-10-25T08:00:00Z/{action}", **kw)
                    before = await self.mcp_ok(client, "schedule_get", event_series_id=eid)
                    args = {"event_series_id": eid, "expected_version": before["version"], "original_start_at": "2026-10-25T08:00:00Z"}
                    restored = await self.mcp_ok(client, "schedule_restore_occurrence", **args)
                    self.assertEqual(restored["series"][0]["event"]["exceptions"], [])
                    self.assertNotEqual(restored["series"][0]["version"], initial["version"])
                    self.assertTrue((await client.call_tool("schedule_restore_occurrence", args)).is_error)
                rows = (await rest.get("/api/schedule", params={"range_start": "2026-10-25T00:00:00Z", "range_end": "2026-10-26T00:00:00Z"})).json()["occurrences"]
                self.assertEqual(rows[0]["start_at"], "2026-10-25T08:00:00Z")
                before_rest = await self.mcp_ok(client, "schedule_get", event_series_id=eid)
                await rest.post(f"/api/events/{eid}/occurrences/2026-10-25T08:00:00Z/cancel")
                await rest.post(f"/api/events/{eid}/occurrences/2026-10-25T08:00:00Z/restore")
                after_rest = await self.mcp_ok(client, "schedule_get", event_series_id=eid)
                self.assertNotEqual(before_rest["version"], after_rest["version"])

    async def test_update_preview_and_concurrent_split(self):
        async with self.running() as (_, _, rest, base):
            eid = await self.create(rest)
            async with Client(base + "/mcp") as client:
                snap = await self.mcp_ok(client, "schedule_get", event_series_id=eid)
                window = {"range_start": "2026-10-24T00:00:00Z", "range_end": "2026-11-05T00:00:00Z"}
                args = {"event_series_id": eid, "expected_version": snap["version"],
                        "data": {"recurrence_rule": {"frequency": "daily", "count": 2}}}
                preview = await self.mcp_ok(client, "schedule_preview_change", **args, **window)
                self.assertEqual(len(preview["after"]), 2)
                self.assertEqual(await self.mcp_ok(client, "schedule_get", event_series_id=eid), snap)
                self.assertTrue((await client.call_tool("schedule_preview_change", {**args,
                    "range_start": "2026-01-01T00:00:00Z", "range_end": "2028-01-01T00:00:00Z"})).is_error)
                args["data"] = {"original_start_at": "2026-10-26T08:00:00Z"}
                results = await asyncio.gather(*(client.call_tool("schedule_split_series", args) for _ in range(2)))
                self.assertEqual(sum(not r.is_error for r in results), 1)
                self.assertEqual(len((await rest.get("/api/events")).json()), 2)

    async def test_context_timezone_privacy_and_fallback(self):
        async with self.running() as (_, _, rest, base):
            async with Client(base + "/mcp") as client:
                fallback = await self.mcp_ok(client, "get_user_context")
                self.assertEqual(fallback["timezone_source"], "utc_fallback")
                response = await rest.post("/user", json={"username": "PRIVATE", "display_name": "PRIVATE NAME",
                    "timezone": "Asia/Tokyo", "timezone_mode": "manual", "locale": "ru-RU"})
                self.assertEqual(response.status_code, 201, response.text)
                with patch("backend.app.services.user_service.utc_now", return_value=dt("2026-10-26T23:30:00Z")):
                    context = await self.mcp_ok(client, "get_user_context")
                self.assertEqual(context["local_date"], "2026-10-27")
                self.assertNotIn("PRIVATE", str(context))
                self.assertNotIn("id", context)
                await rest.patch("/user", json={"timezone_mode": "system"})
                self.assertTrue((await self.mcp_ok(client, "get_user_context"))["warnings"])


if __name__ == "__main__":
    unittest.main()
