"""Persist local chats, messages and generation attempts."""
from alembic import op
import sqlalchemy as sa


revision = "a6b9201d4e33"
down_revision = "f1a205c8b910"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("conversations",
                    sa.Column("id", sa.String(32), primary_key=True),
                    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
                    sa.Column("title", sa.String(128), nullable=False),
                    sa.Column("provider_id", sa.String(64), sa.ForeignKey("llm_providers.id", ondelete="SET NULL")),
                    sa.Column("model", sa.String(255), nullable=False),
                    sa.Column("system_prompt", sa.Text(), nullable=False),
                    sa.Column("context_window_tokens", sa.Integer(), nullable=False),
                    sa.Column("max_output_tokens", sa.Integer(), nullable=False),
                    sa.Column("created_at", sa.DateTime(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("chat_messages",
                    sa.Column("id", sa.String(32), primary_key=True),
                    sa.Column("conversation_id", sa.String(32), sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                              nullable=False),
                    sa.Column("role", sa.String(16), nullable=False),
                    sa.Column("text", sa.Text(), nullable=False),
                    sa.Column("status", sa.String(16), nullable=False),
                    sa.Column("position", sa.Integer(), nullable=False),
                    sa.Column("provider_id", sa.String(64)),
                    sa.Column("model", sa.String(255), nullable=False),
                    sa.Column("created_at", sa.DateTime(), nullable=False),
                    sa.UniqueConstraint("conversation_id", "position"))
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])
    op.create_table("generation_runs",
                    sa.Column("id", sa.String(32), primary_key=True),
                    sa.Column("conversation_id", sa.String(32), sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                              nullable=False),
                    sa.Column("request_id", sa.String(64), nullable=False),
                    sa.Column("user_message_id", sa.String(32), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
                              nullable=False),
                    sa.Column("assistant_message_id", sa.String(32),
                              sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("status", sa.String(16), nullable=False),
                    sa.Column("error", sa.Text()),
                    sa.Column("started_at", sa.DateTime(), nullable=False),
                    sa.Column("finished_at", sa.DateTime()),
                    sa.UniqueConstraint("conversation_id", "request_id"))
    op.create_index("uq_chat_active_run", "generation_runs", ["conversation_id"], unique=True,
                    sqlite_where=sa.text("status IN ('pending','running')"))


def downgrade():
    op.drop_table("generation_runs")
    op.drop_table("chat_messages")
    op.drop_table("conversations")