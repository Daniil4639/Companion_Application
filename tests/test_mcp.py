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
                self.assertEqual({t.name for t in tools}, {"tasks_list", "schedule_list"})
                self.assertTrue(all(t.annotations.read_only_hint for t in tools))
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
                self.assertTrue((await client.call_tool("tasks_create", {"title": "Forbidden"})).is_error)
            self.assertEqual((await rest.get("/api/tasks")).json(), before)
            await self.assert_connections_returned(engine)
            async with Client(base + "/mcp/", mode="legacy") as client:
                self.assertEqual(len((await client.list_tools()).tools), 2)

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
            response = await rest.post("/mcp", headers={"Origin": "http://localhost:6274"}, json={})
            self.assertNotEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
