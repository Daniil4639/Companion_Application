"""Persist input context usage for each generation run."""
from alembic import op
import sqlalchemy as sa

revision = "e4b8a13d7720"
down_revision = "d3a4b819c022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generation_runs", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("generation_runs", sa.Column("input_tokens_estimated", sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table("generation_runs") as batch:
        batch.drop_column("input_tokens_estimated")
        batch.drop_column("input_tokens")
