from .base import Base


async def get_db():
    # Model imports must not construct an engine.
    from .session import async_session_fabric
    async with async_session_fabric() as session:
        yield session


__all__ = [
    "Base",
    "get_db"
]