from contextlib import asynccontextmanager
from sqlalchemy import event, text, update, false
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.app.config import settings


def make_engine(url):
    engine = create_async_engine(url, connect_args={"timeout": 5})

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(connection, _):
        # Explicit transactions include DDL and SAVEPOINTs on supported Python versions.
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    return engine


engine = make_engine(settings.database_url)
async_session_fabric = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def write_transaction(session, *, lock_model=None):
    """Shared by HTTP/MCP callers; acquire SQLite writer reservation before reads."""
    async with session.begin():
        # The engine's BEGIN hook already opened a deferred transaction.
        # A no-op write acquires the reservation, avoiding read-to-write races.
        if lock_model is None:
            await session.execute(text("UPDATE event_series SET id=id WHERE 0"))

        else:
            await session.execute(update(lock_model).where(false()).values(id=lock_model.id))

        yield