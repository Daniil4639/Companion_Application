from sqlalchemy import Boolean, CheckConstraint, Column, Float, String, Text
from backend.app.db.base import Base
from backend.app.db.types import UTCDateTime
from backend.app.utils.time import utc_now


class MCPServerRecord(Base):
    """Saved connection definitions. Tool schemas and live sessions stay in memory."""

    __tablename__ = "mcp_servers"
    __table_args__ = (
        CheckConstraint("transport = 'streamable_http'", name="ck_mcp_transport"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 128", name="ck_mcp_name"),
        CheckConstraint("connect_timeout > 0 AND connect_timeout <= 300", name="ck_mcp_connect_timeout"),
        CheckConstraint("operation_timeout > 0 AND operation_timeout <= 600", name="ck_mcp_operation_timeout"),
        CheckConstraint("(id = 'folliant' AND is_internal = 1) OR (id != 'folliant' AND is_internal = 0)",
                        name="ck_mcp_internal"),
    )

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    transport = Column(String(32), nullable=False, default="streamable_http")
    url = Column(Text, nullable=False)
    connect_timeout = Column(Float, nullable=False, default=10)
    operation_timeout = Column(Float, nullable=False, default=30)
    is_internal = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at = Column(UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now)