"""LLM connections and independent active model; credentials live in OS storage."""
from alembic import op
import sqlalchemy as sa

revision = "f1a205c8b910"
down_revision = "d4e2819c6a10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("llm_providers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("timeout", sa.Float(), nullable=False),
        sa.Column("connect_timeout", sa.Float(), nullable=False),
        sa.Column("secret_ref", sa.String(32), nullable=True),
        sa.CheckConstraint("kind IN ('openai','ollama')", name="ck_llm_kind"))
    op.create_table("llm_selection",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("provider_id", sa.String(64), sa.ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_llm_selection_singleton"))


def downgrade():
    op.drop_table("llm_selection")
    op.drop_table("llm_providers")