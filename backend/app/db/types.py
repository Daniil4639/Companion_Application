from datetime import UTC
from sqlalchemy import DateTime, TypeDecorator
from backend.app.utils.time import as_utc


class UTCDateTime(TypeDecorator):
    """SQLite stores naive UTC; the application receives aware UTC."""
    impl = DateTime
    cache_ok = True


    def process_bind_param(self, value, dialect):
        return None if value is None else as_utc(value).replace(tzinfo=None)


    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=UTC)