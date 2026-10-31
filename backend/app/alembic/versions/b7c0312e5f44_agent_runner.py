"""Persist agent execution audit and conversation-scoped MCP selection."""
from alembic import op
import sqlalchemy as sa
revision = "b7c0312e5f44"
down_revision = "a6b9201d4e33"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("conversations", sa.Column("mcp_servers", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("chat_messages", sa.Column("agent_transcript", sa.JSON()))
    op.add_column("generation_runs", sa.Column("phase", sa.String(32)))
    op.create_table("tool_executions",
        sa.Column("id",sa.String(32),primary_key=True),
        sa.Column("run_id",sa.String(32),sa.ForeignKey("generation_runs.id",ondelete="CASCADE"),nullable=False),
        sa.Column("call_id",sa.String(128),nullable=False),
        sa.Column("server_id",sa.String(64),nullable=False),
        sa.Column("tool_name",sa.String(255),nullable=False),
        sa.Column("arguments",sa.JSON(),nullable=False),
        sa.Column("status",sa.String(32),nullable=False),
        sa.Column("result",sa.JSON()),
        sa.Column("started_at",sa.DateTime(),nullable=False),
        sa.Column("finished_at",sa.DateTime()),
        sa.UniqueConstraint("run_id","call_id"))
    op.create_index("ix_tool_executions_run_id","tool_executions",["run_id"])

def downgrade():
    op.drop_table("tool_executions")
    op.drop_column("generation_runs","phase")
    op.drop_column("chat_messages","agent_transcript")
    op.drop_column("conversations","mcp_servers")

