"""Persist MCP connection definitions; existing calendar data is unchanged."""
from alembic import op
import sqlalchemy as sa
from backend.app.db.types import UTCDateTime

revision = "d4e2819c6a10"
down_revision = "921b413473b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("mcp_servers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("transport", sa.String(32), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("connect_timeout", sa.Float(), nullable=False),
        sa.Column("operation_timeout", sa.Float(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("transport = 'streamable_http'", name="ck_mcp_transport"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 128", name="ck_mcp_name"),
        sa.CheckConstraint("connect_timeout > 0 AND connect_timeout <= 300", name="ck_mcp_connect_timeout"),
        sa.CheckConstraint("operation_timeout > 0 AND operation_timeout <= 600", name="ck_mcp_operation_timeout"),
        sa.CheckConstraint("(id = 'folliant' AND is_internal = 1) OR (id != 'folliant' AND is_internal = 0)",
                           name="ck_mcp_internal"))


def downgrade():
    op.drop_table("mcp_servers")