"""Add control_flow JSON column to source_files.

Revision ID: 20261030_0004
Revises: 20261011_0003
"""
from alembic import op
import sqlalchemy as sa

revision = "20261030_0004"
down_revision = "20261011_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_files") as batch:
        batch.add_column(sa.Column("control_flow", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("source_files") as batch:
        batch.drop_column("control_flow")
