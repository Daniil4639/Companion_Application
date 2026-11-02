"""Add optional keyring reference for MCP authorization."""
from alembic import op
import sqlalchemy as sa

revision = "d3a4b819c022"
down_revision = "c8d1423f6055"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("mcp_servers", sa.Column("credential_ref", sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_column("credential_ref")
