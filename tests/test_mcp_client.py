import os

os.environ["COMPANION_LOAD_DOTENV"] = "0"

import asyncio
import socket
import sys
import unittest
from unittest.mock import patch

from mcp.types import CallToolResult, TextContent, ImageContent
from mcp.types import CONNECTION_CLOSED
from mcp.shared.exceptions import MCPError
from pydantic import ValidationError

import test_mcp
from backend.app.mcp_client.models import MCPServerConfig, RuntimeFailure
from backend.app.mcp_client.manager import MCPClientManager, classify
from backend.app.mcp_client.executor import ToolExecutor
from backend.app.config.settings import Settings


class ClientConfigTests(unittest.TestCase):
    def test_configuration_and_ids(self):
        with patch.dict(os.environ, {"APP_PORT": "9292", "MCP_SERVERS": "ignored legacy value"}):
            settings = Settings()
            self.assertEqual(settings.port, 9292)
            self.assertFalse(hasattr(settings, "mcp_servers"))
        for change in ({"id": "bad.server"}, {"url": "http://user:secret@localhost/mcp"},
                       {"url": "file:///tmp/mcp"}, {"url": "http://localhost/mcp?token=secret"},
                       {"operation_timeout": 0}):
            with self.assertRaises(ValidationError):
                MCPServerConfig.model_validate(
                    {"id": "test", "name": "Test", "url": "http://localhost/mcp", **change})

    def test_protocol_error_is_distinct(self):
        result = classify(MCPError(-32601, "PRIVATE server text"))
        self.assertEqual(result.kind, "protocol_error")
        self.assertEqual(result.protocol_code, -32601)
        self.assertNotIn("PRIVATE", str(result))
        self.assertEqual(classify(MCPError(CONNECTION_CLOSED, "Closed")).kind, "connection_error")


class ClientIntegration(unittest.IsolatedAsyncioTestCase):
    running = test_mcp.MCPIntegration.running
    assert_connections_returned = test_mcp.MCPIntegration.assert_connections_returned

    def manager(self, base, **overrides):
        return MCPClientManager([MCPServerConfig(id="test", name="Test", url=base + "/mcp", **overrides)])

    async def test_app_runtime_real_tasks_schedule_and_validation(self):
        async with self.running() as (app, engine, rest, base):
            manager, executor = app.state.mcp_clients, app.state.tool_executor
            await asyncio.wait_for(app.state.mcp_discovery, 10)
            self.assertEqual(manager.state("folliant"), "connected")
            created = await rest.post("/api/tasks", json={"title": "PRIVATE task", "status": "TODO"})
            self.assertEqual(created.status_code, 201)
            await rest.post("/api/events", json={"title": "Event", "start_at": "2026-10-27T09:00:00+03:00",
                                                 "finish_at": "2026-10-27T10:00:00+03:00", "timezone": "Europe/Moscow"})
            with self.assertLogs("character_helper", level="INFO") as logs:
                await manager.connect("folliant")
                self.assertEqual(len(manager.registry.list()), 20)
                self.assertEqual(manager.state("folliant"), "connected")
                result = await executor.execute("folliant.tasks_list", {"status": "TODO"})
                self.assertEqual(result.status, "success", result)
                self.assertEqual(result.result["structuredContent"]["tasks"][0]["id"], created.json()["id"])
                result = await executor.execute("folliant.schedule_list", {"range_start": "2026-10-27T00:00:00Z",
                                                                           "range_end": "2026-10-28T00:00:00Z"})
                self.assertEqual(result.status, "success", result)
                self.assertEqual(len(result.result["structuredContent"]["occurrences"]), 1)
            self.assertNotIn("PRIVATE", " ".join(logs.output))
            self.assertEqual((await executor.execute("missing", {})).status, "unknown_tool")
            self.assertEqual((await executor.execute("folliant.tasks_list", {"limit": 0})).status, "invalid_arguments")
            # JSON Schema accepts datetimes, but the calendar's reversed range is a tool error.
            result = await executor.execute("folliant.schedule_list", {"range_start": "2026-10-28T00:00:00Z",
                                                                       "range_end": "2026-10-27T00:00:00Z"})
            self.assertEqual(result.status, "tool_error")
            self.assertTrue(result.result["isError"])
            await self.assert_connections_returned(engine)
        self.assertEqual(manager.state("folliant"), "disconnected")
        self.assertFalse(any(t.available for t in manager.registry.list()))

    async def test_namespaces_refresh_reconnect_and_original_names(self):
        async with self.running() as (app, _, _, base):
            @app.state.mcp_server.tool()
            async def echo(value: str) -> str:
                return value

            manager = self.manager(base)
            manager.register({"id": "other", "name": "Other", "url": base + "/mcp"})
            with self.assertRaises(ValueError):
                manager.register({"id": "other", "name": "Duplicate", "url": base + "/mcp"})
            try:
                await asyncio.gather(manager.connect("test"), manager.connect("other"))
                executor = ToolExecutor(manager)
                for name in ("test.echo", "other.echo"):
                    result = await executor.execute(name, {"value": "exact value"})
                    self.assertEqual(result.status, "success", result)
                    self.assertIn("exact value", str(result.result))
                app.state.mcp_server.remove_tool("echo")
                await manager.refresh_tools("test")
                self.assertIsNone(manager.registry.get("test.echo"))
                await manager.disconnect("other")
                self.assertFalse(manager.registry.get("other.echo").available)
                await manager.reconnect("other")
                self.assertIsNone(manager.registry.get("other.echo"))
                self.assertTrue(manager.registry.get("other.tasks_list").available)
            finally:
                await manager.aclose()

    async def test_timeout_no_retry_and_unavailable_server(self):
        async with self.running() as (app, _, _, base):
            calls = []

            @app.state.mcp_server.tool()
            async def slow() -> str:
                calls.append(1)
                await asyncio.sleep(2)
                return "finished"

            manager = self.manager(base, operation_timeout=0.3)
            try:
                await manager.connect("test")
                result = await ToolExecutor(manager).execute("test.slow", {})
                self.assertEqual(result.status, "timeout", result)
                self.assertEqual(len(calls), 1)
                self.assertEqual(manager.state("test"), "disconnected")
                self.assertFalse(manager.registry.get("test.slow").available)
            finally:
                await manager.aclose()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        manager = self.manager(base, connect_timeout=1)
        try:
            with self.assertRaises(RuntimeFailure) as failure:
                await manager.connect("test")
            self.assertIn(failure.exception.kind, {"connection_error", "timeout"})
            self.assertEqual(manager.state("test"), "disconnected")
        finally:
            await manager.aclose()

    async def test_serial_calls_and_shutdown_drains_active_work(self):
        async with self.running() as (app, _, _, base):
            active, maximum = 0, 0
            started = asyncio.Event()

            @app.state.mcp_server.tool()
            async def serial(value: int) -> int:
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                started.set()
                await asyncio.sleep(0.08)
                active -= 1
                return value

            manager = self.manager(base)
            await manager.connect("test")
            executor = ToolExecutor(manager)
            jobs = [asyncio.create_task(executor.execute("test.serial", {"value": i})) for i in range(3)]
            await started.wait()
            await manager.aclose()
            results = await asyncio.gather(*jobs)
            self.assertTrue(all(r.status == "success" for r in results), results)
            self.assertEqual(maximum, 1)
            self.assertEqual(active, 0)
            self.assertEqual(manager.state("test"), "disconnected")
            self.assertEqual((await executor.execute("test.serial", {"value": 4})).status, "unavailable")

    async def test_cancelled_waiter_does_not_abort_active_write(self):
        async with self.running() as (app, _, _, base):
            started, finished = asyncio.Event(), asyncio.Event()

            @app.state.mcp_server.tool()
            async def operation() -> str:
                started.set()
                await asyncio.sleep(0.1)
                finished.set()
                return "done"

            manager = self.manager(base)
            await manager.connect("test")
            waiter = asyncio.create_task(ToolExecutor(manager).execute("test.operation", {}))
            await started.wait()
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            await manager.aclose()
            self.assertTrue(finished.is_set())

    async def test_content_and_permission_hook(self):
        async with self.running() as (app, _, _, base):
            @app.state.mcp_server.tool()
            async def rich() -> CallToolResult:
                return CallToolResult(content=[TextContent(type="text", text="hello"),
                                               ImageContent(type="image", mime_type="image/png", data="AA==")],
                                      structured_content={"answer": 42})

            manager = self.manager(base)
            try:
                await manager.connect("test")
                result = await ToolExecutor(manager).execute("test.rich", {})
                self.assertEqual(result.status, "success", result)
                self.assertEqual([b["type"] for b in result.result["content"]], ["text", "image"])
                self.assertEqual(result.result["structuredContent"], {"answer": 42})

                async def deny(tool, arguments):
                    return False

                result = await ToolExecutor(manager, authorize=deny).execute("test.rich", {})
                self.assertEqual(result.status, "permission_denied")
            finally:
                await manager.aclose()

    async def test_untrusted_schema_refs_do_not_fetch_resources(self):
        from mcp.types import Tool
        async with self.running() as (_, _, _, base):
            manager = self.manager(base)
            manager.registry.replace("test",
                                     [Tool(name="bad", input_schema={"$ref": "https://example.invalid/private"})])
            result = await ToolExecutor(manager).execute("test.bad", {})
            self.assertEqual(result.status, "protocol_error", result)
            self.assertEqual(manager.state("test"), "disconnected")
            await manager.aclose()

    async def test_protocol_error_over_http(self):
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        async with self.running() as (app, _, _, base):
            async def reject(request):
                message = await request.json()
                return JSONResponse({"jsonrpc": "2.0", "id": message.get("id"),
                                     "error": {"code": -32600, "message": "PRIVATE detail"}})

            app.router.routes.insert(0, Route("/broken", reject, methods=["POST"]))
            manager = MCPClientManager([{"id": "broken", "name": "Broken", "url": base + "/broken"}])
            try:
                with self.assertRaises(RuntimeFailure) as failed:
                    await manager.connect("broken")
                self.assertEqual(failed.exception.kind, "protocol_error")
                self.assertEqual(failed.exception.protocol_code, -32600)
                self.assertNotIn("PRIVATE", str(failed.exception))
            finally:
                await manager.aclose()

    async def test_diagnostic_script_over_real_http(self):
        async with self.running() as (_, engine, rest, base):
            await rest.post("/api/tasks", json={"title": "Diagnostic task"})
            env = {**os.environ,
                   "DATABASE_URL": str(engine.url)}
            process = await asyncio.create_subprocess_exec(sys.executable, "-B", "-m", "scripts.check_mcp_client",
                                                           stdout=asyncio.subprocess.PIPE,
                                                           stderr=asyncio.subprocess.PIPE, env=env)
            try:
                output, error = await asyncio.wait_for(process.communicate(), 20)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            self.assertEqual(process.returncode, 0, error.decode(errors="replace"))
            self.assertIn(b"folliant.tasks_list", output)
            self.assertIn(b"Diagnostic task", output)


if __name__ == "__main__":
    unittest.main()
