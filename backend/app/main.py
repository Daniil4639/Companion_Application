import asyncio
from contextlib import asynccontextmanager
import uvicorn
from alembic.config import Config
from alembic import command
from fastapi import FastAPI
from backend.app.config import settings, character_helper_logger
from backend.app.config.settings import PROJECT_ROOT
from backend.app.db.session import engine
from backend.app.api import events_router, schedule_router, occurrence_router, health_check_router
from backend.app.api.errors import register_error_handlers
from backend.app.api.frontend_router import frontend_router
from fastapi.staticfiles import StaticFiles
from backend.app.api.user_router import user_router
from backend.app.api.tasks_router import tasks_router
from starlette.routing import Route
from backend.app.mcp_adapter.server import create_mcp
from backend.app.mcp_adapter.security import LocalOnlyMCP


def migrate():
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")


@asynccontextmanager
async def lifespan(app):
    try:
        await asyncio.to_thread(migrate)
        character_helper_logger.info("Calendar database is ready")

        # SDK session managers are single-use; create one for each application start.
        app.state.mcp_server, app.state.mcp_http = create_mcp()
        app.state.mcp_endpoint.app = app.state.mcp_http

        async with app.state.mcp_http.router.lifespan_context(app.state.mcp_http):
            yield

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