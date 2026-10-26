"""Protocol integration tests use a real loopback server and a disposable SQLite DB."""
import os
os.environ["COMPANION_LOAD_DOTENV"] = "0"

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
from uuid import uuid4

import httpx
from mcp import Client
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.exc import OperationalError
import uvicorn

import backend.app.main as application
import backend.app.db.session as database
from backend.app.services.tasks import taskService


class MCPIntegration(unittest.IsolatedAsyncioTestCase):
    async def assert_connections_returned(self, engine):
        # REST yield-dependency cleanup can finish after the response reaches the client.
        async with asyncio.timeout(2):
            while engine.pool.checkedout():
                await asyncio.sleep(0.01)
        self.assertEqual(engine.pool.checkedout(), 0)

    @asynccontextmanager
    async def running(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite+aiosqlite:///" + (Path(directory) / "mcp.db").as_posix()
            engine = database.make_engine(url)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            app = application.create_app()
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", proxy_headers=False))
            with patch.object(application.settings, "database_url", url), \
                 patch.object(application.settings, "port", port), \
                 patch.object(application, "engine", engine), \
                 patch.object(database, "async_session_fabric", factory):
                task = asyncio.create_task(server.serve(sockets=[sock]))
                try:
                    async with asyncio.timeout(15):
                        while not server.started:
                            if task.done():
                                await task
                                self.fail("Server failed to start")
                            await asyncio.sleep(0.01)
                    base = f"http://127.0.0.1:{port}"
                    async with httpx.AsyncClient(base_url=base) as rest:
                        yield app, engine, rest, base
                finally:
                    server.should_exit = True
                    await asyncio.wait_for(task, 15)
                    sock.close()
                    await engine.dispose()

    async def test_discovery_tasks_pagination_and_rest_compatibility(self):
        async with self.running() as (app, engine, rest, base):
            self.assertEqual((await rest.get("/api/health")).status_code, 200)
            self.assertEqual((await rest.get("/", follow_redirects=True)).status_code, 200)
            created = []
            for title, status in [("First", "TODO"), ("Second", "TODO"), ("Later", "BACKLOG")]:
                response = await rest.post("/api/tasks", json={"title": title, "status": status,
                    "priority": "High", "scheduled_date": "2026-10-26", "due_date": "2026-10-27"})
                self.assertEqual(response.status_code, 201, response.text)
                created.append(response.json())
            before = (await rest.get("/api/tasks")).json()
            async with Client(base + "/mcp") as client:
                tools = (await client.list_tools()).tools
                self.assertEqual({t.name for t in tools}, {"tasks_list", "schedule_list", "tasks_create", "tasks_update", "tasks_move", "tasks_complete", "schedule_create", "schedule_get", "schedule_update", "schedule_reschedule", "schedule_update_occurrence", "schedule_delete", "schedule_update_recurrence", "schedule_split_series", "schedule_restore_occurrence", "get_user_context", "schedule_preview_change"})
                self.assertEqual({t.name for t in tools if t.annotations.read_only_hint}, {"tasks_list", "schedule_list", "schedule_get", "get_user_context", "schedule_preview_change"})
                self.assertTrue(all(t.annotations.destructive_hint and t.annotations.idempotent_hint for t in tools if t.name in {"schedule_update", "schedule_reschedule", "schedule_update_occurrence", "schedule_delete"}))
                first = await client.call_tool("tasks_list", {"status": "TODO", "limit": 1})
                self.assertFalse(first.is_error, first)
                data = first.structured_content
                self.assertEqual(data["next_offset"], 1)
                self.assertEqual(data["tasks"][0], {k: created[0][k] for k in
                    ("id", "title", "status", "priority", "scheduled_date", "due_date")})
                second = (await client.call_tool("tasks_list", {"status": "TODO", "limit": 1, "offset": 1})).structured_content
                self.assertIsNone(second["next_offset"])
                self.assertEqual(second["tasks"][0]["id"], created[1]["id"])
                self.assertEqual(len((await client.call_tool("tasks_list")).structured_content["tasks"]), 3)
                for args in ({"status": "INVALID"}, {"limit": 0}, {"limit": 501}, {"offset": -1}):
                    self.assertTrue((await client.call_tool("tasks_list", args)).is_error)
                self.assertTrue((await client.call_tool("tasks_delete", {"task_id": str(uuid4())})).is_error)
            self.assertEqual((await rest.get("/api/tasks")).json(), before)
            await self.assert_connections_returned(engine)
            async with Client(base + "/mcp/", mode="legacy") as client:
                self.assertEqual(len((await client.list_tools()).tools), 17)

    async def test_schedule_dst_exceptions_and_range_validation(self):
        async with self.running() as (_, engine, rest, base):
            response = await rest.post("/api/events", json={"title": "Morning",
                "start_at": "2026-10-24T09:00:00+02:00", "finish_at": "2026-10-24T10:00:00+02:00",
                "timezone": "Europe/Berlin", "recurrence_rule": {"frequency": "daily", "count": 4}})
            self.assertEqual(response.status_code, 201, response.text)
            event = response.json()
            args = {"range_start": "2026-10-24T00:00:00+02:00", "range_end": "2026-10-29T00:00:00+01:00"}
            async with Client(base + "/mcp") as client:
                original = (await client.call_tool("schedule_list", args)).structured_content["occurrences"]
                self.assertEqual([x["start_at"] for x in original[:2]],
                                 ["2026-10-24T07:00:00Z", "2026-10-25T08:00:00Z"])
                prefix = f"/api/events/{event['id']}/occurrences/"
                self.assertEqual((await rest.post(prefix + "2026-10-25T08:00:00Z/cancel")).status_code, 200)
                self.assertEqual((await rest.post(prefix + "2026-10-24T07:00:00Z/move", json={
                    "start_at": "2026-10-28T12:00:00Z", "finish_at": "2026-10-28T13:00:00Z"})).status_code, 200)
                actual = (await client.call_tool("schedule_list", args)).structured_content
                self.assertEqual(actual, (await rest.get("/api/schedule", params=args)).json())
                self.assertEqual(len(actual["occurrences"]), 3)
                narrow = {"range_start": "2026-10-28T12:30:00Z", "range_end": "2026-10-28T13:00:00Z"}
                self.assertEqual(len((await client.call_tool("schedule_list", narrow)).structured_content["occurrences"]), 1)
                narrow["range_start"] = "2026-10-28T13:00:00Z"
                narrow["range_end"] = "2026-10-28T14:00:00Z"
                self.assertEqual((await client.call_tool("schedule_list", narrow)).structured_content["occurrences"], [])
                for start, end in [("2026-10-24T00:00:00", args["range_end"]),
                                   (args["range_end"], args["range_start"]),
                                   ("2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z")]:
                    self.assertTrue((await client.call_tool("schedule_list", {"range_start": start, "range_end": end})).is_error)
            await self.assert_connections_returned(engine)

    async def test_database_error_cleanup_and_recovery(self):
        async with self.running() as (_, engine, _, base):
            async with Client(base + "/mcp") as client:
                original = taskService.list
                async def fail_after_read(session, **kwargs):
                    await original(session, **kwargs)
                    raise OperationalError("SECRET SQL", {}, Exception("SECRET PATH"))
                with patch.object(taskService, "list", AsyncMock(side_effect=fail_after_read)):
                    result = await client.call_tool("tasks_list")
                self.assertTrue(result.is_error)
                self.assertNotIn("SECRET", str(result))
                self.assertEqual(engine.pool.checkedout(), 0)
                self.assertEqual((await client.call_tool("tasks_list")).structured_content["tasks"], [])

    async def test_concurrent_tools_use_independent_sessions(self):
        async with self.running() as (_, engine, _, base):
            sessions = []
            original = taskService.list
            async def observe(session, **kwargs):
                sessions.append(session)
                await asyncio.sleep(0.02)
                return await original(session, **kwargs)
            async with Client(base + "/mcp") as client:
                with patch.object(taskService, "list", AsyncMock(side_effect=observe)):
                    results = await asyncio.gather(*(client.call_tool("tasks_list") for _ in range(4)))
                self.assertTrue(all(not r.is_error for r in results))
                self.assertEqual(len({id(s) for s in sessions}), 4)
                self.assertTrue(all(not s.in_transaction() for s in sessions))
                await self.assert_connections_returned(engine)

    async def test_task_write_lifecycle(self):
        async with self.running() as (_, engine, rest, base):
            async with Client(base + "/mcp") as client:
                async def call(name, **args):
                    result = await client.call_tool(name, args)
                    self.assertFalse(result.is_error, result)
                    return result.structured_content
                task = await call("tasks_create", data={"title": " Draft "})
                other = await call("tasks_create", data={"title": "Second"})
                self.assertEqual(task["title"], "Draft")
                self.assertIsNone(task["scheduled_date"])
                self.assertIsNone(task["due_date"])
                changed = await call("tasks_update", task_id=task["id"], data={
                    "description": "Notes", "priority": "High", "scheduled_date": "2026-10-26", "due_date": "2026-10-27"})
                self.assertEqual(changed["title"], "Draft")
                cleared = await call("tasks_update", task_id=task["id"], data={"description": None, "due_date": None})
                self.assertIsNone(cleared["description"])
                self.assertIsNone(cleared["due_date"])
                self.assertEqual(cleared["scheduled_date"], "2026-10-26")
                self.assertEqual(cleared["priority"], "High")
                await call("tasks_move", task_id=other["id"], data={"status": "BACKLOG", "position": 0})
                rows = (await rest.get("/api/tasks", params={"status": "BACKLOG"})).json()
                self.assertEqual([(r["id"], r["position"]) for r in rows], [(other["id"], 0), (task["id"], 1)])
                await call("tasks_move", task_id=task["id"], data={"status": "IN_PROGRESS", "position": 20})
                done = await call("tasks_complete", task_id=task["id"])
                self.assertEqual(done["status"], "DONE")
                self.assertIsNotNone(done["completed_at"])
                repeated = await call("tasks_complete", task_id=task["id"])
                self.assertEqual(repeated["completed_at"], done["completed_at"])
                self.assertEqual(repeated["position"], done["position"])
                reopened = await call("tasks_move", task_id=task["id"], data={"status": "TODO", "position": 0})
                self.assertIsNone(reopened["completed_at"])
                self.assertEqual((await rest.get("/api/tasks/" + task["id"])).json(), reopened)
                for status in ("BACKLOG", "TODO", "IN_PROGRESS", "DONE"):
                    rows = (await rest.get("/api/tasks", params={"status": status})).json()
                    self.assertEqual([r["position"] for r in rows], list(range(len(rows))))
            await self.assert_connections_returned(engine)

    async def test_write_validation_and_missing_tasks(self):
        async with self.running() as (_, engine, rest, base):
            async with Client(base + "/mcp") as client:
                task = (await client.call_tool("tasks_create", {"data": {"title": "Keep"}})).structured_content
                cases = [("tasks_create", {"data": {"title": " "}}),
                         ("tasks_create", {"data": {"title": "Bad date", "due_date": "2026-10-26T12:00:00Z"}}),
                         ("tasks_update", {"task_id": task["id"], "data": {"title": None}}),
                         ("tasks_update", {"task_id": task["id"], "data": {"unexpected": 1}}),
                         ("tasks_move", {"task_id": task["id"], "data": {"status": "TODO", "position": -1}}),
                         ("tasks_move", {"task_id": task["id"], "data": {"status": "UNKNOWN", "position": 0}}),
                         ("tasks_complete", {"task_id": "invalid"})]
                for name, extra in [("tasks_update", {"data": {"title": "X"}}),
                                    ("tasks_move", {"data": {"status": "DONE", "position": 0}}),
                                    ("tasks_complete", {})]:
                    cases.append((name, {"task_id": str(uuid4()), **extra}))
                for name, args in cases:
                    result = await client.call_tool(name, args)
                    self.assertTrue(result.is_error, (name, result))
                self.assertEqual((await rest.get("/api/tasks")).json(), [task])
            await self.assert_connections_returned(engine)

    async def test_schedule_create_and_rollback(self):
        from backend.app.services.calendar import calendarService
        async with self.running() as (_, engine, rest, base):
            data = {"title": "Meeting", "start_at": "2026-10-26T09:00:00+03:00",
                    "finish_at": "2026-10-26T10:00:00+03:00", "timezone": "Europe/Moscow"}
            async with Client(base + "/mcp") as client:
                result = await client.call_tool("schedule_create", {"data": data})
                self.assertFalse(result.is_error, result)
                event = result.structured_content
                self.assertEqual(event["start_at"], "2026-10-26T06:00:00Z")
                self.assertIsNone(event["recurrence_rule_id"])
                self.assertIsNone(event["recurrence_rule"])
                self.assertEqual((await rest.get("/api/events/" + event["id"])).json(), event)
                schedule = await client.call_tool("schedule_list", {"range_start": "2026-10-26T00:00:00Z", "range_end": "2026-10-27T00:00:00Z"})
                self.assertEqual(len(schedule.structured_content["occurrences"]), 1)
                for change in ({"recurrence_rule": {"frequency": "daily", "count": 2}},
                               {"timezone": "Invalid/Zone"}, {"start_at": "2026-10-26T09:00:00"},
                               {"finish_at": data["start_at"]}, {"category": "invalid"}):
                    self.assertTrue((await client.call_tool("schedule_create", {"data": {**data, **change}})).is_error)
                original = calendarService.create_event
                async def fail_after_flush(**kwargs):
                    await original(**kwargs)
                    raise OperationalError("SECRET SQL", {}, Exception("SECRET PATH"))
                with patch.object(calendarService, "create_event", AsyncMock(side_effect=fail_after_flush)):
                    failed = await client.call_tool("schedule_create", {"data": data})
                self.assertTrue(failed.is_error)
                self.assertNotIn("SECRET", str(failed))
                self.assertEqual((await rest.get("/api/events")).json(), [event])
            await self.assert_connections_returned(engine)

    async def test_task_write_rollback(self):
        async with self.running() as (_, engine, rest, base):
            async with Client(base + "/mcp") as client:
                task = (await client.call_tool("tasks_create", {"data": {"title": "Keep"}})).structured_content
                original = taskService._reorder
                async def fail_after_reorder(*args, **kwargs):
                    await original(*args, **kwargs)
                    raise OperationalError("SECRET SQL", {}, Exception("SECRET PATH"))
                with patch.object(taskService, "_reorder", AsyncMock(side_effect=fail_after_reorder)):
                    failed = await client.call_tool("tasks_move", {"task_id": task["id"], "data": {"status": "DONE", "position": 0}})
                self.assertTrue(failed.is_error)
                self.assertNotIn("SECRET", str(failed))
                self.assertEqual((await rest.get("/api/tasks")).json(), [task])
            await self.assert_connections_returned(engine)

    async def calendar_fixture(self, rest, recurring=False):
        data = {"title": "Lesson", "description": "Shared", "start_at": "2026-10-24T09:00:00+02:00",
                "finish_at": "2026-10-24T10:30:00+02:00", "timezone": "Europe/Berlin"}
        if recurring:
            data["recurrence_rule"] = {"frequency": "daily", "count": 3}
        response = await rest.post("/api/events", json=data)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    async def mcp_ok(self, client, name, **args):
        result = await client.call_tool(name, args)
        self.assertFalse(result.is_error, result)
        return result.structured_content

    async def test_calendar_edit_single_and_versions(self):
        async with self.running() as (_, engine, rest, base):
            event_id = await self.calendar_fixture(rest)
            async with Client(base + "/mcp") as client:
                before = await self.mcp_ok(client, "schedule_get", event_series_id=event_id)
                edited = await self.mcp_ok(client, "schedule_update", event_series_id=event_id,
                    expected_version=before["version"], data={"title": "Renamed", "description": None})
                self.assertEqual(edited["changed_fields"], ["title", "description"])
                self.assertEqual(edited["event"]["title"], "Renamed")
                stale = await client.call_tool("schedule_update", {"event_series_id": event_id,
                    "expected_version": before["version"], "data": {"title": "Overwrite"}})
                self.assertTrue(stale.is_error)
                self.assertIn("VERSION_CONFLICT", str(stale))
                moved = await self.mcp_ok(client, "schedule_reschedule", event_series_id=event_id,
                    expected_version=edited["version"], start_at="2026-10-25T09:00:00+01:00")
                self.assertEqual(moved["event"]["finish_at"], "2026-10-25T09:30:00Z")
                self.assertEqual(moved["event"]["timezone"], "Europe/Berlin")
                self.assertTrue(moved["warnings"])
                # REST changes must invalidate the MCP token as well.
                self.assertEqual((await rest.patch("/api/events/" + event_id, json={"title": "REST edit"})).status_code, 200)
                conflict = await client.call_tool("schedule_delete", {"event_series_id": event_id, "expected_version": moved["version"]})
                self.assertTrue(conflict.is_error)
                fresh = await self.mcp_ok(client, "schedule_get", event_series_id=event_id)
                deleted = await self.mcp_ok(client, "schedule_delete", event_series_id=event_id, expected_version=fresh["version"])
                self.assertEqual(deleted["outcome"], "deleted")
                self.assertEqual((await rest.get("/api/events/" + event_id)).status_code, 404)
                self.assertTrue((await client.call_tool("schedule_delete", {"event_series_id": event_id, "expected_version": fresh["version"]})).is_error)
            await self.assert_connections_returned(engine)

    async def test_calendar_edit_occurrence_isolation_and_replay(self):
        async with self.running() as (_, engine, rest, base):
            event_id = await self.calendar_fixture(rest, recurring=True)
            query = {"range_start": "2026-10-24T00:00:00Z", "range_end": "2026-11-01T00:00:00Z"}
            baseline = (await rest.get("/api/schedule", params=query)).json()["occurrences"]
            original = "2026-10-25T08:00:00Z"
            async with Client(base + "/mcp") as client:
                before = await self.mcp_ok(client, "schedule_get", event_series_id=event_id)
                self.assertEqual(before["event"]["recurrence_rule"]["count"], 3)
                for name, extra in [("schedule_update", {"data": {"title": "All?"}}),
                                    ("schedule_reschedule", {"start_at": "2026-10-27T08:00:00Z"}),
                                    ("schedule_delete", {})]:
                    self.assertTrue((await client.call_tool(name, {"event_series_id": event_id, "expected_version": before["version"], **extra})).is_error)
                args = {"event_series_id": event_id, "original_start_at": original,
                        "expected_version": before["version"], "data": {"title": "Special", "description": "",
                        "start_at": "2026-10-28T12:00:00Z", "finish_at": "2026-10-28T13:00:00Z"}}
                first = await self.mcp_ok(client, "schedule_update_occurrence", **args)
                self.assertEqual(first["event"]["title"], "Lesson")
                self.assertEqual(len(first["event"]["exceptions"]), 1)
                self.assertTrue((await client.call_tool("schedule_update_occurrence", args)).is_error)
                args.update(expected_version=first["version"], data={"start_at": "2026-10-29T12:00:00Z", "finish_at": "2026-10-29T13:00:00Z"})
                second = await self.mcp_ok(client, "schedule_update_occurrence", **args)
                self.assertEqual(second["event"]["exceptions"][0]["id"], first["event"]["exceptions"][0]["id"])
                rows = (await rest.get("/api/schedule", params=query)).json()["occurrences"]
                target = next(r for r in rows if r["original_start_at"] == original)
                self.assertEqual(target["title"], "Special")
                self.assertEqual(target["description"], "")
                self.assertEqual([r for r in rows if r["original_start_at"] != original],
                                 [r for r in baseline if r["original_start_at"] != original])
                cancelled = await self.mcp_ok(client, "schedule_delete", event_series_id=event_id,
                    original_start_at=original, expected_version=second["version"])
                self.assertEqual(cancelled["outcome"], "cancelled")
                self.assertEqual((await rest.get("/api/schedule", params=query)).json()["occurrences"],
                                 [r for r in baseline if r["original_start_at"] != original])
                args["expected_version"] = cancelled["version"]
                self.assertTrue((await client.call_tool("schedule_update_occurrence", args)).is_error)
            await self.assert_connections_returned(engine)

    async def test_calendar_edit_validation_and_rest_exception_conflict(self):
        async with self.running() as (_, _, rest, base):
            event_id = await self.calendar_fixture(rest)
            series_id = await self.calendar_fixture(rest, recurring=True)
            async with Client(base + "/mcp") as client:
                before = await self.mcp_ok(client, "schedule_get", event_series_id=event_id)
                for change in ({"start_at": "2026-10-24T10:00:00"}, {"timezone": "Invalid/Zone"},
                               {"finish_at": "2020-01-01T00:00:00Z"}, {"title": " "},
                               {"recurrence_rule": {"frequency": "daily"}}, {}):
                    self.assertTrue((await client.call_tool("schedule_update", {"event_series_id": event_id,
                        "expected_version": before["version"], "data": change})).is_error)
                self.assertEqual(await self.mcp_ok(client, "schedule_get", event_series_id=event_id), before)
                self.assertTrue((await client.call_tool("schedule_get", {"event_series_id": str(uuid4())})).is_error)
                before = await self.mcp_ok(client, "schedule_get", event_series_id=series_id)
                for original in ("2026-10-25T08:00:00", "2026-10-25T08:01:00Z"):
                    self.assertTrue((await client.call_tool("schedule_update_occurrence", {"event_series_id": series_id,
                        "expected_version": before["version"], "original_start_at": original, "data": {"title": "X"}})).is_error)
                await rest.post(f"/api/events/{series_id}/occurrences/2026-10-25T08:00:00Z/cancel")
                stale = await client.call_tool("schedule_update_occurrence", {"event_series_id": series_id,
                    "expected_version": before["version"], "original_start_at": "2026-10-26T08:00:00Z", "data": {"title": "X"}})
                self.assertTrue(stale.is_error)
                self.assertIn("VERSION_CONFLICT", str(stale))

    async def test_calendar_edit_concurrent_version_and_rollback(self):
        from backend.app.services.calendar import calendarService
        async with self.running() as (_, engine, rest, base):
            event_id = await self.calendar_fixture(rest)
            async with Client(base + "/mcp") as client:
                before = await self.mcp_ok(client, "schedule_get", event_series_id=event_id)
                results = await asyncio.gather(*(client.call_tool("schedule_update", {"event_series_id": event_id,
                    "expected_version": before["version"], "data": {"title": title}}) for title in ("A", "B")))
                self.assertEqual(sum(not r.is_error for r in results), 1)
                fresh = await self.mcp_ok(client, "schedule_get", event_series_id=event_id)
                original = calendarService.update_event
                async def fail_after_flush(*args, **kwargs):
                    await original(*args, **kwargs)
                    raise OperationalError("SECRET", {}, Exception("SECRET"))
                with patch.object(calendarService, "update_event", AsyncMock(side_effect=fail_after_flush)):
                    failed = await client.call_tool("schedule_update", {"event_series_id": event_id,
                        "expected_version": fresh["version"], "data": {"title": "Should roll back"}})
                self.assertTrue(failed.is_error)
                self.assertNotIn("SECRET", str(failed))
                self.assertEqual(await self.mcp_ok(client, "schedule_get", event_series_id=event_id), fresh)
            await self.assert_connections_returned(engine)

    async def test_access_policy(self):
        app = application.create_app()
        cases = [(("192.168.1.8", 1234), {}), (("127.0.0.1", 1234), {"host": "evil.example"}),
                 (("127.0.0.1", 1234), {"origin": "https://evil.example"}),
                 (("127.0.0.1", 1234), {"origin": "null"}),
                 (("127.0.0.1", 1234), {"x-forwarded-for": "127.0.0.1"}),
                 (("127.0.0.1", 1234), {"forwarded": "for=127.0.0.1"})]
        for peer, headers in cases:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=peer), base_url="http://127.0.0.1") as client:
                for path in ("/mcp", "/mcp/"):
                    response = await client.post(path, headers=headers, json={})
                    self.assertEqual(response.status_code, 403, response.text)
        async with self.running() as (_, _, rest, base):
            response = await rest.post("/mcp", headers={"Origin": base}, json={})
            self.assertNotEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
