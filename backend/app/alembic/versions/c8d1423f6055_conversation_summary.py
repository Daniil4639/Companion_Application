"""Rolling conversation summaries; original messages stay intact."""
from alembic import op
import sqlalchemy as sa


revision = "c8d1423f6055"
down_revision = "b7c0312e5f44"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("conversation_summaries",
                    sa.Column("conversation_id", sa.String(32), sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                              primary_key=True),
                    sa.Column("content", sa.Text(), nullable=False),
                    sa.Column("last_summarized_message_id", sa.String(32),
                              sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("updated_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("conversation_summaries")