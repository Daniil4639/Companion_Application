from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from backend.app.llm.schemas import ProviderError
from sqlalchemy.exc import IntegrityError, OperationalError
from backend.app.services.tasks import TaskNotFound, InvalidTaskData
from backend.app.services.user_service import UserNotFound, UserExists
from backend.app.services.errors import CalendarNotFound, CalendarConflict, InvalidCalendarData
from backend.app.config import character_helper_logger
from backend.app.services.mcp_servers import MCPServerNotFound, MCPServerConflict, InternalMCPServer
from backend.app.mcp_client.models import RuntimeFailure


async def task_error(_, exc):
    return JSONResponse(status_code=404 if isinstance(exc, TaskNotFound) else 422,
                        content={"detail": str(exc)})


async def profile_error(_, exc):
    return JSONResponse(status_code=404 if isinstance(exc, UserNotFound) else 409,
                        content={"detail": str(exc)})


async def domain_error(_, exc):
    code = 404 if isinstance(exc, CalendarNotFound) else 409 if isinstance(exc, CalendarConflict) else 422
    return JSONResponse(status_code=code, content={"detail": str(exc)})


async def mcp_catalog_error(_, exc):
    code = 404 if isinstance(exc, MCPServerNotFound) else 403 if isinstance(exc, InternalMCPServer) else 409
    return JSONResponse(status_code=code, content={"detail": str(exc)})


async def mcp_runtime_error(_, exc):
    code = 504 if exc.kind == "timeout" else 409 if exc.kind == "unavailable" else 502
    return JSONResponse(status_code=code, content={"detail": exc.details()})


async def llm_error(_, exc):
    code = {"not_found": 404, "conflict": 409, "invalid_request": 422, "unsupported": 422,
            "closed": 503, "credential_store": 503, "credential_cleanup": 503, "authentication": 502, "rate_limit": 429,
            "timeout": 504}.get(exc.code, 502)
    return JSONResponse(status_code=code, content={"detail": exc.details()})


async def safe_validation(request, exc):
    if request.url.path.startswith("/api/llm/"):
        # FastAPI normally echoes invalid input, including passwords inside a model-level error.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(error["loc"]), "type": error["type"], "msg": "Invalid provider setting"}
            for error in exc.errors()]})
    return await request_validation_exception_handler(request, exc)


def register_error_handlers(app):
    app.add_exception_handler(ProviderError, llm_error)
    app.add_exception_handler(RequestValidationError, safe_validation)
    for error in (MCPServerNotFound, MCPServerConflict, InternalMCPServer):
        app.add_exception_handler(error, mcp_catalog_error)
    app.add_exception_handler(RuntimeFailure, mcp_runtime_error)
    app.add_exception_handler(TaskNotFound, task_error)
    app.add_exception_handler(InvalidTaskData, task_error)

    app.add_exception_handler(UserNotFound, profile_error)
    app.add_exception_handler(UserExists, profile_error)

    for error in (CalendarNotFound, CalendarConflict, InvalidCalendarData):
        app.add_exception_handler(error, domain_error)

    @app.exception_handler(IntegrityError)
    async def integrity_error(_, exc):
        kind = getattr(exc.orig, "sqlite_errorname", "")

        if kind in {"SQLITE_CONSTRAINT_UNIQUE", "SQLITE_CONSTRAINT_PRIMARYKEY", "SQLITE_CONSTRAINT_FOREIGNKEY",
                    "SQLITE_CONSTRAINT_CHECK"}:
            return JSONResponse(status_code=409, content={"detail": "Data conflicts with database constraints"})

        character_helper_logger.error("Unexpected database integrity error (%s)", kind)
        return JSONResponse(status_code=500, content={"detail": "Database integrity error"})

    @app.exception_handler(OperationalError)
    async def database_error(_, exc):
        if "locked" in str(exc.orig).lower() or "busy" in str(exc.orig).lower():
            return JSONResponse(status_code=503, content={"detail": "Database is busy; retry the request"},
                                headers={"Retry-After": "1"})

        character_helper_logger.error("Database operation failed (%s)", type(exc.orig).__name__)
        return JSONResponse(status_code=500, content={"detail": "Database operation failed"})