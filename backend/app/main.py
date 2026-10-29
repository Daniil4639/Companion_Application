import asyncio
from contextlib import asynccontextmanager
import uvicorn
from alembic.config import Config
from alembic import command
from fastapi import FastAPI
from backend.app.config import settings, character_helper_logger
from backend.app.config.settings import PROJECT_ROOT
from backend.app.db.session import engine
from backend.app.db import session as database
from backend.app.api import events_router, schedule_router, occurrence_router, health_check_router
from backend.app.api.errors import register_error_handlers
from backend.app.api.frontend_router import frontend_router
from fastapi.staticfiles import StaticFiles
from backend.app.api.user_router import user_router
from backend.app.api.tasks_router import tasks_router
from backend.app.api.mcp_servers_router import mcp_servers_router
from backend.app.services.mcp_servers import MCPServerService
from backend.app.services.llm_providers import LLMProviderService
from backend.app.api.llm_router import llm_router
from backend.app.mcp_client.models import RuntimeFailure
from starlette.routing import Route
from backend.app.mcp_adapter.server import create_mcp
from backend.app.mcp_adapter.security import LocalOnlyMCP
from backend.app.mcp_client.manager import MCPClientManager
from backend.app.mcp_client.executor import ToolExecutor


def migrate():
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")


async def discover_connections(manager, records, port):
    async def discover(record):
        try:
            if record.is_internal:
                # lifespan yields before uvicorn listens. Probe asynchronously in a
                # background task, never wait for our own HTTP server during startup.
                async with asyncio.timeout(10):
                    while True:
                        try:
                            _, writer = await asyncio.open_connection("127.0.0.1", port)
                            writer.close()
                            await writer.wait_closed()
                            break
                        except OSError:
                            await asyncio.sleep(0.1)
            await manager.connect(record.id)
        except (RuntimeFailure, TimeoutError):
            character_helper_logger.info("Initial MCP discovery unavailable: %s", record.id)

    await asyncio.gather(*(discover(record) for record in records))


@asynccontextmanager
async def lifespan(app):
    try:
        await asyncio.to_thread(migrate)
        character_helper_logger.info("Calendar database is ready")

        # SDK session managers are single-use; create one for each application start.
        app.state.mcp_server, app.state.mcp_http = create_mcp()
        app.state.mcp_endpoint.app = app.state.mcp_http

        async with app.state.mcp_http.router.lifespan_context(app.state.mcp_http):
            manager = MCPClientManager()
            catalog = MCPServerService(database.async_session_fabric, manager)

            await catalog.ensure_internal(settings.port)
            records = await catalog.read_all()

            for record in records:
                manager.register(record.connection_config())

            app.state.mcp_catalog = catalog
            llm = LLMProviderService(database.async_session_fabric)
            app.state.llm_providers = llm

            app.state.mcp_clients = manager
            app.state.tool_registry = manager.registry
            app.state.tool_executor = ToolExecutor(manager)

            discovery = asyncio.create_task(discover_connections(manager, records, settings.port),
                                            name="mcp-initial-discovery")
            app.state.mcp_discovery = discovery

            try:
                yield

            finally:
                discovery.cancel()
                await asyncio.gather(discovery, return_exceptions=True)
                await llm.aclose()
                await catalog.aclose()
                await manager.aclose()

    finally:
        await engine.dispose()


def create_app():
    app = FastAPI(lifespan=lifespan, title="Companion Calendar API")
    app.state.mcp_server, app.state.mcp_http = create_mcp()
    mcp_endpoint = LocalOnlyMCP(app.state.mcp_http)
    app.state.mcp_endpoint = mcp_endpoint
    app.router.routes.extend([
        Route("/mcp", endpoint=mcp_endpoint),
        Route("/mcp/", endpoint=mcp_endpoint)
    ])

    register_error_handlers(app)

    app.include_router(events_router)
    app.include_router(schedule_router)
    app.include_router(occurrence_router)
    app.include_router(health_check_router)
    app.include_router(user_router)
    app.include_router(tasks_router)
    app.include_router(mcp_servers_router)
    app.include_router(llm_router)
    app.include_router(frontend_router)

    for directory in ("styles", "scripts", "resources"):
        app.mount("/" + directory, StaticFiles(directory=PROJECT_ROOT / "frontend" / directory), name=directory)

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.port,
        proxy_headers=False
    )