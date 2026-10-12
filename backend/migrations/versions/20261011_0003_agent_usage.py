"""Distinguish collected SDK usage from unknown historical/model usage.

Revision ID: 20261011_0003
Revises: 20261003_0002
"""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0003"
down_revision = "20261003_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("usage_collected", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("usage_collected")
