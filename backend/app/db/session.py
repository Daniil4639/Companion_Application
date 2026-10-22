from typing import AsyncGenerator, Any
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from backend.app.config import settings


DATABASE_URL = f"sqlite+aiosqlite:///./{settings.sql_lite_db_name}.db"

engine = create_async_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
    }
)

async_session_fabric = async_sessionmaker(
    engine,
    expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, Any]:
    async with async_session_fabric() as session:
        yield session


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()