"""add per-user services, MCP servers, and Skills

Revision ID: a6b8d0f2c4e6
Revises: f5a7c9e1b3d4
Create Date: 2026-07-28 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6b8d0f2c4e6"
down_revision: str | None = "f5a7c9e1b3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_service_configs",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("providers", postgresql.JSONB(), nullable=False),
        sa.Column("models", postgresql.JSONB(), nullable=False),
        sa.Column("role_assignments", postgresql.JSONB(), nullable=False),
        sa.Column("tavily_api_key", sa.Text(), server_default="", nullable=False),
        sa.Column("mineru_api_key", sa.Text(), server_default="", nullable=False),
        sa.Column("mineru_base_url", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "user_mcp_servers",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("protocol", sa.String(16), nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_mcp_servers_user_id", "user_mcp_servers", ["user_id"])
    op.create_table(
        "user_skills",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_ref", sa.String(1024), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_skills_user_id", "user_skills", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_skills_user_id", table_name="user_skills")
    op.drop_table("user_skills")
    op.drop_index("ix_user_mcp_servers_user_id", table_name="user_mcp_servers")
    op.drop_table("user_mcp_servers")
    op.drop_table("user_service_configs")
