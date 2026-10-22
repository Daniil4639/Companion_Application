"""Serves the PyScript frontend (HTML + static assets)."""

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path

frontend_router = APIRouter()

# ─── Resolve paths ──────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2].parent
print(_PROJECT_ROOT)
_TEMPLATES = _PROJECT_ROOT / "frontend" / "templates"
_STYLES = _PROJECT_ROOT / "frontend" / "styles"
_SCRIPTS = _PROJECT_ROOT / "frontend" / "scripts"


@frontend_router.get("/", response_class=HTMLResponse)
async def serve_index():
    return FileResponse(_TEMPLATES / "index.html")


@frontend_router.get("/chat", response_class=HTMLResponse)
async def serve_chat():
    return FileResponse(_TEMPLATES / "chat.html")


@frontend_router.get("/styles/{style_file}", response_class=FileResponse)
async def serve_style(style_file: str):
    return FileResponse(_STYLES / style_file)


@frontend_router.get("/scripts/{script_file}", response_class=FileResponse)
async def serve_script(script_file: str):
    return FileResponse(_SCRIPTS / script_file)