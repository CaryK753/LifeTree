"""add research_jobs table

Revision ID: q0d1e2f3a4b5
Revises: p9c0d1e2f3a4
Create Date: 2026-08-07 21:00:00.000000

Implements §C.1 of the cross-validation / deep-research spec: the
``research_jobs`` table stores one row per deep-research task. The
``run_research_job`` Celery task advances each row through the eight-state
machine (planning → searching → extracting → structuring → validating →
synthesizing → completed | failed | cancelled).

The table is purely additive — no existing tables are touched. Two indexes
cover the common access patterns: list-by-user-and-status (the ``/research``
page) and list-by-created-at (recent-jobs sidebar).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "q0d1e2f3a4b5"
down_revision: Union[str, None] = "p9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("user_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "scope",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "engines",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="planning",
            nullable=False,
        ),
        sa.Column(
            "progress",
            sa.Float(),
            server_default="0.0",
            nullable=False,
        ),
        sa.Column("current_step", sa.String(length=128), nullable=True),
        sa.Column(
            "source_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "assertion_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "conflict_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        "ix_research_jobs_user_status",
        "research_jobs",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_research_jobs_created_at",
        "research_jobs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_research_jobs_created_at", table_name="research_jobs")
    op.drop_index("ix_research_jobs_user_status", table_name="research_jobs")
    op.drop_table("research_jobs")
