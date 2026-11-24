"""Add control_flow_error column to source_files.

Revision ID: 20261030_0005
Revises: 20261030_0004
"""
from alembic import op
import sqlalchemy as sa

revision = "20261030_0005"
down_revision = "20261030_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_files") as batch:
        batch.add_column(sa.Column("control_flow_error", sa.String(512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("source_files") as batch:
        batch.drop_column("control_flow_error")
