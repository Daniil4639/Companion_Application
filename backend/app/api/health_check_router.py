from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db import get_db


health_check_router = APIRouter(prefix="/api/health", tags=["Health check"])


@health_check_router.get("")
async def health_check(session: AsyncSession = Depends(get_db)):
    try:
        await session.execute(text("SELECT id FROM event_series LIMIT 1"))
        await session.execute(text("SELECT id FROM recurrence_rules LIMIT 1"))
        await session.execute(text("SELECT id FROM event_exceptions LIMIT 1"))

    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})

    return {"status": "ok"}