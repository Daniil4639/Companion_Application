"""Catalog CRUD and runtime reconciliation over real localhost HTTP/MCP."""
import os

os.environ["COMPANION_LOAD_DOTENV"] = "0"

import asyncio
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from backend.app.db.base import Base
from backend.app.db.session import make_engine
from backend.app.dto.mcp_servers import MCPServerCreate, MCPServerPatch
from backend.app.mcp_client.manager import MCPClientManager
from backend.app.services.mcp_servers import MCPServerService, InternalMCPServer
import test_mcp

PREFIX = "/api/mcp/servers"


class CatalogIntegration(unittest.IsolatedAsyncioTestCase):
    running = test_mcp.MCPIntegration.running
    assert_connections_returned = test_mcp.MCPIntegration.assert_connections_returned

    async def test_internal_bootstrap_discovery_and_protection(self):
        async with self.running() as (app, engine, rest, base):
            await asyncio.wait_for(app.state.mcp_discovery, 10)
            records = (await rest.get(PREFIX)).json()
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["is_internal"])
            self.assertEqual(records[0]["url"], base + "/mcp")
            status = (await rest.get(PREFIX + "/folliant/status")).json()
            self.assertEqual(status["state"], "connected")
            self.assertEqual(status["available_tools"], 20)
            tools = (await rest.get(PREFIX + "/folliant/tools")).json()
            self.assertEqual(len(tools), 20)
            self.assertIn("input_schema", tools[0])
            for change in ({"name": "Changed"}, {"url": base + "/other"}):
                self.assertEqual((await rest.patch(PREFIX + "/folliant", json=change)).status_code, 403)
            self.assertEqual((await rest.delete(PREFIX + "/folliant")).status_code, 403)
            self.assertEqual(
                (await rest.post(PREFIX, json={"id": "folliant", "name": "Fake", "url": base})).status_code, 403)
            self.assertEqual((await rest.patch(PREFIX + "/folliant", json={"is_internal": False})).status_code, 422)
            self.assertEqual((await rest.get(PREFIX)).json(), records)
            await self.assert_connections_returned(engine)

    async def test_crud_validation_offline_and_http_errors(self):
        async with self.running() as (app, _, rest, base):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                offline = f"http://127.0.0.1:{sock.getsockname()[1]}/mcp"
            data = {"id": "notes", "name": "Notes", "url": offline, "connect_timeout": 0.3}
            response = await rest.post(PREFIX, json=data)
            self.assertEqual(response.status_code, 201, response.text)
            self.assertFalse(response.json()["is_internal"])
            self.assertEqual(app.state.mcp_clients.state("notes"), "disconnected")
            self.assertEqual((await rest.post(PREFIX, json=data)).status_code, 409)
            for change in ({"id": "rename"}, {"name": " "}, {"name": None}, {}, {"enabled": True},
                           {"url": "file:///tmp/mcp"}, {"url": "http://user:secret@localhost/mcp"},
                           {"url": "http://localhost/mcp?token=secret"}, {"connect_timeout": -1}):
                self.assertEqual((await rest.patch(PREFIX + "/notes", json=change)).status_code, 422, change)
            self.assertEqual((await rest.post(PREFIX, json={**data, "id": "other", "is_internal": True})).status_code,
                             422)
            probe = await rest.post(PREFIX + "/notes/test")
            self.assertIn(probe.status_code, (502, 504), probe.text)
            self.assertIn(probe.json()["detail"]["code"], ("timeout", "connection_error"))
            status = (await rest.get(PREFIX + "/notes/status")).json()
            self.assertEqual(status["state"], "disconnected")
            self.assertIsNotNone(status["last_error"])
            self.assertEqual((await rest.patch(PREFIX + "/notes", json={"name": "Updated"})).status_code, 200)
            self.assertEqual((await rest.get(PREFIX + "/notes")).json()["name"], "Updated")
            self.assertEqual((await rest.delete(PREFIX + "/notes")).status_code, 204)
            for method, path, body in (("get", "/notes", None), ("get", "/notes/status", None),
                                       ("get", "/notes/tools", None), ("delete", "/notes", None),
                                       ("patch", "/notes", {"name": "Gone"}), ("post", "/notes/test", None)):
                self.assertEqual((await rest.request(method, PREFIX + path, json=body)).status_code, 404)
            # No arbitrary execution endpoint; foreign origins cannot edit local settings.
            self.assertEqual((await rest.post(PREFIX + "/folliant/call", json={})).status_code, 404)
            for headers in ({"Origin": "https://evil.example"},
                            {"X-Forwarded-For": "127.0.0.1"}):
                self.assertEqual((await rest.get(PREFIX, headers=headers)).status_code, 403)
            # Send Host literally: HTTP client transports can normalize it from the URL.
            reader, writer = await asyncio.open_connection("127.0.0.1", int(base.rsplit(":", 1)[1]))
            try:
                writer.write(f"GET {PREFIX} HTTP/1.1\r\nHost: evil.example\r\nConnection: close\r\n\r\n".encode())
                await writer.drain()
                status_line = await asyncio.wait_for(reader.readline(), 3)
                self.assertIn(b" 403 ", status_line)
            finally:
                writer.close()
                await writer.wait_closed()

    async def test_refresh_update_and_remove_clear_old_tools(self):
        async with self.running() as (app, _, rest, base):
            data = {"id": "notes", "name": "Notes", "url": base + "/mcp"}
            await rest.post(PREFIX, json=data)
            response = await rest.post(PREFIX + "/notes/refresh-tools")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()), 20)
            self.assertTrue(app.state.tool_registry.get("notes.tasks_list").available)
            await rest.patch(PREFIX + "/notes", json={"url": base + "/missing"})
            self.assertEqual((await rest.get(PREFIX + "/notes/tools")).json(), [])
            self.assertIsNone(app.state.tool_registry.get("notes.tasks_list"))
            self.assertTrue(app.state.tool_registry.get("folliant.tasks_list").available)
            self.assertEqual((await rest.post(PREFIX + "/notes/test")).status_code, 502)
            await rest.patch(PREFIX + "/notes", json={"url": base + "/mcp"})
            self.assertEqual((await rest.post(PREFIX + "/notes/test")).status_code, 200)
            await rest.delete(PREFIX + "/notes")
            self.assertEqual(app.state.tool_registry.list("notes"), [])
            self.assertEqual((await app.state.tool_executor.execute("notes.tasks_list", {})).status, "unknown_tool")

    async def test_edit_drains_active_calls_without_database_transaction(self):
        async with self.running() as (app, engine, rest, base):
            started, release = asyncio.Event(), asyncio.Event()

            @app.state.mcp_server.tool()
            async def slow_catalog_test() -> str:
                started.set()
                await release.wait()
                return "finished"

            await rest.post(PREFIX, json={"id": "notes", "name": "Notes", "url": base + "/mcp"})
            await rest.post(PREFIX + "/notes/test")
            invocation = asyncio.create_task(app.state.tool_executor.execute("notes.slow_catalog_test", {}))
            await asyncio.wait_for(started.wait(), 5)
            edit = asyncio.create_task(rest.patch(PREFIX + "/notes", json={"name": "Changed"}))
            try:
                async with asyncio.timeout(3):
                    while app.state.mcp_clients.state("notes") != "closing":
                        await asyncio.sleep(0.01)
                self.assertFalse(edit.done())
                self.assertEqual((await app.state.tool_executor.execute("notes.tasks_list", {})).status, "unavailable")
                await self.assert_connections_returned(engine)
                # Unrelated calendar/task writes remain possible while the call drains.
                self.assertEqual((await rest.post("/api/tasks", json={"title": "While editing"})).status_code, 201)
            finally:
                release.set()
                result, response = await asyncio.gather(invocation, edit)
            self.assertEqual(result.status, "success")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(app.state.tool_registry.list("notes"), [])


class CatalogPersistence(unittest.IsolatedAsyncioTestCase):
    async def test_restart_port_change_internal_sql_constraint_and_cancelled_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = make_engine("sqlite+aiosqlite:///" + (Path(directory) / "catalog.db").as_posix())
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            manager = MCPClientManager()
            service = MCPServerService(factory, manager)
            try:
                await service.ensure_internal(8181)
                for record in await service.read_all():
                    manager.register(record.connection_config())
                internal = await service.get("folliant")
                await service.create(MCPServerCreate(id="notes", name="Notes", url="http://localhost:9999/mcp"))
                await service.ensure_internal(9292)
                self.assertEqual((await service.get("folliant")).url, "http://127.0.0.1:9292/mcp")
                self.assertEqual((await service.get("folliant")).created_at, internal.created_at)
                with self.assertRaises(InternalMCPServer):
                    await service.delete("folliant")
                with self.assertRaises(IntegrityError):
                    async with engine.begin() as conn:
                        await conn.execute(text("UPDATE mcp_servers SET is_internal=0 WHERE id='folliant'"))

                entered, release = asyncio.Event(), asyncio.Event()
                original = service._get

                async def delayed(session, server_id):
                    entered.set()
                    await release.wait()
                    return await original(session, server_id)

                with patch.object(service, "_get", delayed):
                    edit = asyncio.create_task(service.update("notes", MCPServerPatch(name="Persisted")))
                    await entered.wait()
                    edit.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await edit
                    release.set()
                    await service.aclose()
                await manager.aclose()

                restarted = MCPServerService(factory, MCPClientManager())
                records = await restarted.read_all()
                self.assertEqual(len(records), 2)
                self.assertEqual((await restarted.get("notes")).name, "Persisted")
                for record in records:
                    restarted.manager.register(record.connection_config())
                await restarted.delete("notes")
                await restarted.aclose()
                await restarted.manager.aclose()
            finally:
                await service.aclose()
                await manager.aclose()
                await engine.dispose()
