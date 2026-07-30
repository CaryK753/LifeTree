"""add source_proposals table

Revision ID: h1b2c3d4e5f6
Revises: g0a1b2c3d4e5
Create Date: 2026-07-29 23:00:00.000000

Implements P1 信源自动发现 (Source Auto-Discovery): a new ``source_proposals``
table holding LLM-suggested information sources pending user review. Each
proposal carries a Tavily Extract probe result and a status lifecycle
(proposed → accepted | rejected). Accepting a proposal promotes it to a
real ``InformationSource`` row with auto_refresh enabled.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h1b2c3d4e5f6"
down_revision: str | None = "g0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_proposals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="public"),
        sa.Column("publisher", sa.String(255), nullable=True),
        sa.Column("proposed_reason", sa.Text(), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("credibility_hint", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("probe_result", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_proposals_goal", "source_proposals", ["goal_id"])
    op.create_index("ix_source_proposals_user", "source_proposals", ["user_id"])
    op.create_index("ix_source_proposals_status", "source_proposals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_source_proposals_status", table_name="source_proposals")
    op.drop_index("ix_source_proposals_user", table_name="source_proposals")
    op.drop_index("ix_source_proposals_goal", table_name="source_proposals")
    op.drop_table("source_proposals")
