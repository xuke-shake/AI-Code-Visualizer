"""initial schema

Revision ID: 20260509_0001
Revises:
Create Date: 2026-05-09
"""
from alembic import op
import sqlalchemy as sa


def bigint():
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")

revision = "20260509_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(128), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("nickname", sa.String(64), nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="user"),
        sa.Column("status", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "quotas",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("user_id", bigint(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("max_projects", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("max_files_per_project", sa.Integer(), nullable=False, server_default="2000"),
        sa.Column("max_concurrent_tasks", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("monthly_token_limit", sa.Integer(), nullable=False, server_default="500000"),
        sa.Column("used_tokens_this_month", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("uq_quotas_user_id", "quotas", ["user_id"], unique=True)

    op.create_table(
        "projects",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", bigint(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("language", sa.String(64), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_index_version", sa.String(64), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_owner_updated", "projects", ["owner_id", "updated_at"])

    op.create_table(
        "repositories",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("project_id", bigint(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repo_url", sa.String(512), nullable=True),
        sa.Column("branch", sa.String(128), nullable=True),
        sa.Column("commit_hash", sa.String(64), nullable=True),
        sa.Column("zip_object_key", sa.String(512), nullable=True),
        sa.Column("local_path", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_repositories_project_id", "repositories", ["project_id"], unique=True)

    op.create_table(
        "source_files",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("project_id", bigint(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("language", sa.String(64), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parse_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "relative_path", name="uq_source_files_project_path"),
    )
    op.create_index("ix_source_files_project_hash", "source_files", ["project_id", "file_hash"])

    op.create_table(
        "code_chunks",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("project_id", bigint(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", bigint(), sa.ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_type", sa.String(32), nullable=False),
        sa.Column("symbol_name", sa.String(255), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("embedding_id", sa.String(128), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.create_index("ix_code_chunks_project_file", "code_chunks", ["project_id", "file_id"])

    op.create_table(
        "symbols",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("project_id", bigint(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", bigint(), sa.ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("qualified_name", sa.String(512), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("signature", sa.Text(), nullable=True),
    )
    op.create_index("ix_symbols_project_name", "symbols", ["project_id", "name"])

    op.create_table(
        "dependencies",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("project_id", bigint(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_symbol_id", bigint(), sa.ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_symbol_id", bigint(), sa.ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_file_id", bigint(), sa.ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_file_id", bigint(), sa.ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
    )
    op.create_index("ix_dependencies_project_source_symbol", "dependencies", ["project_id", "source_symbol_id"])

    op.create_table(
        "analysis_tasks",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("project_id", bigint(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", bigint(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_analysis_tasks_project_status_created", "analysis_tasks", ["project_id", "status", "created_at"])

    op.create_table(
        "diagrams",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("project_id", bigint(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creator_id", bigint(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("diagram_type", sa.String(64), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("mermaid_code", sa.Text(), nullable=False),
        sa.Column("node_mapping_json", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_outdated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("share_token", sa.String(128), nullable=True),
        sa.Column("share_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_diagrams_project_created", "diagrams", ["project_id", "created_at"])
    op.create_index("uq_diagrams_share_token", "diagrams", ["share_token"], unique=True)

    op.create_table(
        "agent_runs",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("task_id", bigint(), sa.ForeignKey("analysis_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", bigint(), primary_key=True, autoincrement=True),
        sa.Column("user_id", bigint(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", bigint(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_user_action_created", "audit_logs", ["user_id", "action", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_user_action_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("agent_runs")
    op.drop_index("uq_diagrams_share_token", table_name="diagrams")
    op.drop_index("ix_diagrams_project_created", table_name="diagrams")
    op.drop_table("diagrams")
    op.drop_index("ix_analysis_tasks_project_status_created", table_name="analysis_tasks")
    op.drop_table("analysis_tasks")
    op.drop_index("ix_dependencies_project_source_symbol", table_name="dependencies")
    op.drop_table("dependencies")
    op.drop_index("ix_symbols_project_name", table_name="symbols")
    op.drop_table("symbols")
    op.drop_index("ix_code_chunks_project_file", table_name="code_chunks")
    op.drop_table("code_chunks")
    op.drop_index("ix_source_files_project_hash", table_name="source_files")
    op.drop_table("source_files")
    op.drop_index("uq_repositories_project_id", table_name="repositories")
    op.drop_table("repositories")
    op.drop_index("ix_projects_owner_updated", table_name="projects")
    op.drop_table("projects")
    op.drop_index("uq_quotas_user_id", table_name="quotas")
    op.drop_table("quotas")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
