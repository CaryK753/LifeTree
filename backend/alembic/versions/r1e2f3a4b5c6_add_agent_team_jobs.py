"""add agent_team_jobs table

Revision ID: r1e2f3a4b5c6
Revises: q0d1e2f3a4b5
Create Date: 2026-08-07 22:00:00.000000

Implements §D.2 of the cross-validation / deep-research spec: the
``agent_team_jobs`` table stores one row per AgentTeam task. The
``run_agent_team`` Celery task advances each row through the seven-state
machine (decomposing → dispatching → running → aggregating → reviewing
→ completed | failed | cancelled).

The table is purely additive — no existing tables are touched. Two indexes
cover the common access patterns: list-by-user-and-status (the
``/agent-team`` page) and list-by-created-at (recent-jobs sidebar).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "r1e2f3a4b5c6"
down_revision: Union[str, None] = "q0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_team_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("user_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column(
            "scope",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "subtasks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "specialist_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="decomposing",
            nullable=False,
        ),
        sa.Column(
            "progress",
            sa.Float(),
            server_default="0.0",
            nullable=False,
        ),
        sa.Column("current_step", sa.String(length=128), nullable=True),
        sa.Column("aggregated", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "review_gaps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "iterations",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "final_output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "failure_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_team_jobs_user_status",
        "agent_team_jobs",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_agent_team_jobs_created_at",
        "agent_team_jobs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_team_jobs_created_at", table_name="agent_team_jobs")
    op.drop_index("ix_agent_team_jobs_user_status", table_name="agent_team_jobs")
    op.drop_table("agent_team_jobs")
