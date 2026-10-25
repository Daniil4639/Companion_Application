from sqlalchemy import Column, Integer, String, CheckConstraint
from backend.app.db.base import Base
from backend.app.db.types import UTCDateTime
from backend.app.utils.time import utc_now


class User(Base):

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_user_singleton"),
        CheckConstraint("timezone_mode IN ('system', 'manual')", name="ck_user_timezone_mode"),
        CheckConstraint("length(trim(username)) BETWEEN 1 AND 64", name="ck_user_username"),
    )

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=False,
        default=1
    )

    username = Column(
        String(64),
        nullable=False
    )

    display_name = Column(
        String(128),
        nullable=True
    )

    timezone = Column(
        String(64),
        nullable=False
    )

    timezone_mode = Column(
        String(16),
        nullable=False,
        default="system"
    )

    locale = Column(
        String(16),
        nullable=False,
        default="ru-RU"
    )

    created_at = Column(
        UTCDateTime(),
        nullable=False,
        default=utc_now
    )

    updated_at = Column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now
    )