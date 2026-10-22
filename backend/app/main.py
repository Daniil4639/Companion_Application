import asyncio
from contextlib import asynccontextmanager
import uvicorn
from alembic.config import Config
from alembic import command
from fastapi import FastAPI

from backend.app.config import settings, character_helper_logger
from backend.app.api import *
from pathlib import Path
from fastapi.staticfiles import StaticFiles


@asynccontextmanager
async def lifespan(_: FastAPI):
    character_helper_logger.info("Запуск миграции БД...")

    try:
        alembic_cfg = Config("alembic.ini")
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
        character_helper_logger.info("Миграции успешно применены.")

    except Exception as e:
        character_helper_logger.warning(f"Пропуск или ошибка миграций (возможно, нет файлов в versions/): {e}")

    character_helper_logger.info("Запуск FastAPI...")
    yield


app = FastAPI(lifespan=lifespan, title="Character Helper App")
app.include_router(events_router)
app.include_router(schedule_router)
app.include_router(occurrence_router)
app.include_router(health_check_router)
app.include_router(frontend_router)


# ─── Static files (CSS, scripts, fonts) ─────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
app.mount("/static", StaticFiles(directory=str(_PROJECT_ROOT / "frontend")), name="static")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(settings.port),
        reload=False
    )