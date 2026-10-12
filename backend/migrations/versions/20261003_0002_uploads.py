"""add private upload records and repository upload references

Revision ID: 20261003_0002
Revises: 20260509_0001
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20261003_0002"
down_revision = "20260509_0001"
branch_labels = None
depends_on = None


def bigint():
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", bigint(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_source_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_status", sa.String(32), nullable=False, server_default="validated"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_uploads_owner_id", "uploads", ["owner_id"])
    op.create_index("uq_uploads_object_key", "uploads", ["object_key"], unique=True)

    with op.batch_alter_table("repositories", schema=None, recreate="always") as batch_op:
        batch_op.add_column(sa.Column("upload_id", bigint(), nullable=True))
        batch_op.create_index("ix_repositories_upload_id", ["upload_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_repositories_upload_id_uploads",
            "uploads",
            ["upload_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("repositories", schema=None, recreate="always") as batch_op:
        batch_op.drop_constraint("fk_repositories_upload_id_uploads", type_="foreignkey")
        batch_op.drop_index("ix_repositories_upload_id")
        batch_op.drop_column("upload_id")

    op.drop_index("uq_uploads_object_key", table_name="uploads")
    op.drop_index("ix_uploads_owner_id", table_name="uploads")
    op.drop_table("uploads")
