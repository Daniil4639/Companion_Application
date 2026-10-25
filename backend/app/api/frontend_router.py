"""First-launch routing for the single local profile."""
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.config.settings import PROJECT_ROOT
from backend.app.db import get_db
from backend.app.services.user_service import find_user


frontend_router = APIRouter()
TEMPLATES = PROJECT_ROOT / "frontend" / "templates"


@frontend_router.get("/", include_in_schema=False)
@frontend_router.get("/templates/index.html", include_in_schema=False)
async def serve_index(session: AsyncSession = Depends(get_db)):
    page = "index.html" if await find_user(session) else "welcome.html"

    return FileResponse(TEMPLATES / page, headers={"Cache-Control": "no-store"})


@frontend_router.get("/welcome", include_in_schema=False)
@frontend_router.get("/templates/welcome.html", include_in_schema=False)
async def serve_welcome(session: AsyncSession = Depends(get_db)):
    if await find_user(session):
        return RedirectResponse("/", status_code=303)

    return FileResponse(TEMPLATES / "welcome.html", headers={"Cache-Control": "no-store"})