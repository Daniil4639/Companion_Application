import asyncio
from logging.config import fileConfig
from sqlalchemy import event, pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from backend.app.config import settings
from backend.app.models import EventSeries, EventException, RecurrenceRule
from backend.app.db.base import Base


config = context.config
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                      compare_type=True, compare_server_default=True, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()
        if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Migration failed foreign key validation")


async def run_async_migrations():
    engine = async_engine_from_config(config.get_section(config.config_ini_section, {}),
                                      prefix="sqlalchemy.", poolclass=pool.NullPool)
    @event.listens_for(engine.sync_engine, "connect")
    def configure(connection, _):
        connection.isolation_level = None
        # Batch rebuilds reference tables; integrity is checked before commit.
        connection.execute("PRAGMA foreign_keys=OFF")

    @event.listens_for(engine.sync_engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Calendar data migration requires an online database connection")
else:
    asyncio.run(run_async_migrations())
