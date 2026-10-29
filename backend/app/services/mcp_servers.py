"""Single persistence boundary for MCP connections, independent of HTTP.

Network work never holds a SQLAlchemy session. Runtime configuration changes
are serialized and finish even when an HTTP caller disconnects.
"""
import asyncio
from contextlib import nullcontext
from sqlalchemy import select
from backend.app.db.session import write_transaction
from backend.app.dto.mcp_servers import MCPServerCreate, MCPServerPatch, MCPServerResponse
from backend.app.mcp_client.models import MCPServerConfig
from backend.app.models.mcp_server import MCPServerRecord


class MCPServerNotFound(Exception):
    pass


class MCPServerConflict(Exception):
    pass


class InternalMCPServer(Exception):
    pass


class MCPServerService:
    def __init__(self, session_factory, manager=None):
        self.session_factory = session_factory
        self.manager = manager
        self._lock = asyncio.Lock()
        self._pending = set()
        self._closed = False

    async def read_all(self):
        async with self.session_factory() as session:
            records = (await session.scalars(select(MCPServerRecord).order_by(MCPServerRecord.id))).all()
            return [MCPServerResponse.model_validate(record) for record in records]

    async def get(self, server_id):
        async with self.session_factory() as session:
            return MCPServerResponse.model_validate(await self._get(session, server_id))

    @staticmethod
    async def _get(session, server_id):
        record = await session.get(MCPServerRecord, server_id)
        if record is None:
            raise MCPServerNotFound("MCP server not found")
        return record

    @staticmethod
    def _editable(record):
        if record.is_internal:
            raise InternalMCPServer("The internal Folliant connection cannot be edited or deleted")

    async def ensure_internal(self, port):
        """Application bootstrap only; refresh the derived URL when APP_PORT changes."""
        config = MCPServerConfig(id="folliant", name="Folliant Local MCP", url=f"http://127.0.0.1:{port}/mcp")
        async with self.session_factory() as session:
            async with write_transaction(session, lock_model=MCPServerRecord):
                record = await session.get(MCPServerRecord, "folliant")
                if record is None:
                    session.add(MCPServerRecord(**config.model_dump(), is_internal=True))
                else:
                    for key, value in {**config.model_dump(), "is_internal": True}.items():
                        setattr(record, key, value)

    async def _change(self, operation):
        if self._closed:
            raise MCPServerConflict("MCP catalog is shutting down")

        async def run():
            async with self._lock:
                return await operation()

        task = asyncio.create_task(run(), name="mcp-catalog-change")
        self._pending.add(task)

        def finished(done):
            self._pending.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def create(self, data: MCPServerCreate):
        data = MCPServerCreate.model_validate(data)
        if data.id == "folliant":
            raise InternalMCPServer("The ID folliant is reserved for the internal connection")

        async def operation():
            async with self.session_factory() as session:
                async with write_transaction(session, lock_model=MCPServerRecord):
                    if await session.get(MCPServerRecord, data.id):
                        raise MCPServerConflict("MCP server ID already exists")
                    record = MCPServerRecord(**data.model_dump(), is_internal=False)
                    session.add(record)
                    await session.flush()
                    result = MCPServerResponse.model_validate(record)
            if self.manager is not None:
                self.manager.register(result.connection_config())
            return result

        return await self._change(operation)

    async def update(self, server_id, data: MCPServerPatch):
        data = MCPServerPatch.model_validate(data)

        async def operation():
            # Check protection before disturbing the internal live session.
            self._editable(await self.get(server_id))
            async with self.manager.edit_registration(server_id) if self.manager is not None else nullcontext():
                async with self.session_factory() as session:
                    async with write_transaction(session, lock_model=MCPServerRecord):
                        record = await self._get(session, server_id)
                        self._editable(record)
                        old = MCPServerResponse.model_validate(record).connection_config()
                        config = MCPServerConfig.model_validate({**old.model_dump(),
                                                                 **data.model_dump(exclude_unset=True)})
                        for key, value in config.model_dump().items():
                            setattr(record, key, value)
                        await session.flush()
                        result = MCPServerResponse.model_validate(record)
                if self.manager is not None:
                    self.manager.replace_registration(result.connection_config())
                return result

        return await self._change(operation)

    async def delete(self, server_id):
        async def operation():
            self._editable(await self.get(server_id))
            async with self.manager.edit_registration(server_id) if self.manager is not None else nullcontext():
                async with self.session_factory() as session:
                    async with write_transaction(session, lock_model=MCPServerRecord):
                        record = await self._get(session, server_id)
                        self._editable(record)
                        await session.delete(record)
                if self.manager is not None:
                    self.manager.remove_registration(server_id)

        return await self._change(operation)

    async def aclose(self):
        self._closed = True
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)