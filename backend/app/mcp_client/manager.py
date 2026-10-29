"""One session-owning task per server, with a bounded serial command queue.

SDK/AnyIO contexts are always entered and exited in that same task. A caller's
cancellation does not cancel an in-flight tool (whose write outcome is unknown).
"""
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
import json
import time
import anyio
import httpx2
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT
from pydantic import ValidationError
from .models import MCPServerConfig, RuntimeFailure, MCPConnectionStatus
from .registry import ToolRegistry
from backend.app.config import character_helper_logger


def log(event, server_id, **fields):
    character_helper_logger.info(
        json.dumps(
            {
                "event": event,
                "server_id": server_id,
                **fields
            },
            ensure_ascii=True
        )
    )


def classify(exc):
    if isinstance(exc, BaseExceptionGroup):
        failures = [classify(e) for e in exc.exceptions]
        return next((e for e in failures if e.kind == "timeout"), failures[0])

    if isinstance(exc, RuntimeFailure):
        return exc

    if isinstance(exc, (TimeoutError, httpx2.TimeoutException)):
        return RuntimeFailure("timeout", "MCP operation timed out; check state before retrying writes")

    if isinstance(exc, MCPError):
        if exc.code == CONNECTION_CLOSED:
            return RuntimeFailure("connection_error", "MCP connection closed; write outcome may be unknown", exc.code)

        if exc.code == REQUEST_TIMEOUT:
            return RuntimeFailure("timeout", "MCP request timed out; write outcome may be unknown", exc.code)

        return RuntimeFailure("protocol_error", "MCP server rejected the protocol request", exc.code)

    if isinstance(exc,
                  (httpx2.HTTPError, OSError, anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError)):
        return RuntimeFailure("connection_error", "MCP connection failed; write outcome may be unknown")

    if isinstance(exc, ValidationError):
        return RuntimeFailure("protocol_error", "MCP server returned an invalid response")

    return RuntimeFailure("protocol_error", "MCP session failed")


@dataclass
class _Connection:
    config: MCPServerConfig
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=100))
    task: asyncio.Task | None = None
    state: str = "disconnected"
    closing: bool = False
    last_error: dict | None = None


class MCPClientManager:
    def __init__(self, configs=(), registry=None):
        self.registry = registry if registry is not None else ToolRegistry()
        self._connections = {}

        self._closed = False

        for config in configs:
            self.register(config)

    def register(self, config):
        config = MCPServerConfig.model_validate(config)

        if self._closed or config.id in self._connections:
            raise ValueError("Manager closed or duplicate server ID")

        self._connections[config.id] = _Connection(config)

    def state(self, server_id):
        conn = self._connection(server_id)
        return "closing" if conn.closing else conn.state

    def status(self, server_id):
        conn = self._connection(server_id)
        return MCPConnectionStatus(server_id=server_id, state=self.state(server_id),
                                   available_tools=sum(t.available for t in self.registry.list(server_id)),
                                   last_error=conn.last_error)

    @asynccontextmanager
    async def edit_registration(self, server_id):
        """Caller serializes edits. Drain accepted calls before changing configuration."""
        conn = self._connection(server_id)
        await self.disconnect(server_id)
        conn.closing = True
        try:
            yield
        finally:
            conn.closing = False

    def replace_registration(self, config):
        config = MCPServerConfig.model_validate(config)
        conn = self._connection(config.id)
        if not conn.closing:
            raise RuntimeError("Pause connection before replacing its registration")
        conn.config = config
        conn.last_error = None
        self.registry.remove(config.id)

    def remove_registration(self, server_id):
        if not self._connection(server_id).closing:
            raise RuntimeError("Pause connection before removing its registration")
        del self._connections[server_id]
        self.registry.remove(server_id)

    def _connection(self, server_id):
        if server_id not in self._connections:
            raise RuntimeFailure("unavailable", "Unknown MCP server")

        return self._connections[server_id]

    async def _submit(self, server_id, operation, *args):
        conn = self._connection(server_id)

        if self._closed or conn.closing:
            raise RuntimeFailure("unavailable", "MCP server is closing")

        if conn.task is None or conn.task.done():
            conn.task = asyncio.create_task(self._worker(conn), name=f"mcp-client:{server_id}")

        future = asyncio.get_running_loop().create_future()
        # Consume errors even if the requesting task goes away while shielded.
        future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)

        try:
            conn.queue.put_nowait((operation, args, future))

        except asyncio.QueueFull:
            raise RuntimeFailure("unavailable", "MCP request queue is full") from None

        return await asyncio.shield(future)

    async def connect(self, server_id):
        await self._submit(server_id, "connect")

    async def refresh_tools(self, server_id):
        return await self._submit(server_id, "refresh")

    async def call_tool(self, server_id, name, arguments):
        return await self._submit(server_id, "call", name, arguments)

    async def _discover(self, client, conn):
        tools, cursor, seen = [], None, set()

        for _ in range(100):
            page = await client.list_tools(cursor=cursor, cache_mode="refresh")
            tools.extend(page.tools)

            if len(tools) > 10000:
                raise RuntimeFailure("protocol_error", "MCP tool catalog exceeds limit")
            cursor = page.next_cursor

            if not cursor:
                self.registry.replace(conn.config.id, tools)
                log("tools_discovered", conn.config.id, count=len(tools))
                return self.registry.list(conn.config.id)

            if cursor in seen:
                break

            seen.add(cursor)

        raise RuntimeFailure("protocol_error", "Invalid MCP pagination")

    async def _worker(self, conn):
        sid = conn.config.id
        current = None
        failure = RuntimeFailure("connection_error", "MCP connection closed")

        try:
            conn.last_error = None
            conn.state = "connecting"
            log("connecting", sid)

            async with AsyncExitStack() as stack:
                async with asyncio.timeout(conn.config.connect_timeout):
                    client = await stack.enter_async_context(Client(conn.config.url,
                                                                    read_timeout_seconds=conn.config.operation_timeout,
                                                                    cache=None))
                conn.state = "connected"
                log("connected", sid)

                async with asyncio.timeout(conn.config.operation_timeout):
                    await self._discover(client, conn)

                while True:
                    command = await conn.queue.get()

                    if command is None:
                        break

                    operation, args, current = command
                    started = time.monotonic()

                    if operation == "call":
                        log("tool_started", sid, tool=args[0])

                    try:
                        async with asyncio.timeout(conn.config.operation_timeout):
                            if operation == "connect":
                                result = None

                            elif operation == "refresh":
                                result = await self._discover(client, conn)

                            else:
                                # Low-level session avoids Client's automatic retry/input loops.
                                result = await client.session.call_tool(args[0], args[1])

                        current.set_result(result)
                        if operation == "call":
                            log("tool_error" if result.is_error else "tool_completed", sid,
                                tool=args[0], duration_ms=round((time.monotonic() - started) * 1000))

                        current = None

                    except Exception as exc:
                        failure = classify(exc)
                        if operation == "call":
                            log("tool_failed", sid, tool=args[0], error_kind=failure.kind,
                                duration_ms=round((time.monotonic() - started) * 1000))
                        raise

                # ExitStack closes the Client here, in its owning task, after accepted work.
        except Exception as exc:
            failure = classify(exc)
            conn.last_error = failure.details()
            log("connection_failed", sid, error_kind=failure.kind)

        finally:
            conn.state = "disconnected"
            self.registry.unavailable(sid)

            if current is not None and not current.done():
                current.set_exception(failure)

            while not conn.queue.empty():
                command = conn.queue.get_nowait()

                if command is not None and not command[2].done():
                    command[2].set_exception(failure)

            log("disconnected", sid)

    async def disconnect(self, server_id):
        conn = self._connection(server_id)

        if conn.closing:
            if conn.task:
                await asyncio.shield(conn.task)
            return

        conn.closing = True
        try:
            if conn.task and not conn.task.done():
                # Stop marker follows accepted operations. No cancellation during a tool.
                await conn.queue.put(None)
                await asyncio.shield(conn.task)
                # If a failed worker drained a full queue while put() waited, the stop
                # marker may have arrived after worker exit. Do not reuse that marker.
                while not conn.queue.empty():
                    conn.queue.get_nowait()

            self.registry.unavailable(server_id)

        finally:
            conn.closing = False

    async def reconnect(self, server_id):
        await self.disconnect(server_id)
        await self.connect(server_id)

    async def aclose(self):
        self._closed = True
        await asyncio.gather(*(self.disconnect(sid) for sid in self._connections))