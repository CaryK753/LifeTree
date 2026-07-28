"""add events.status column for review inbox & auto-sinking

Revision ID: f3a5b7c9d1e2
Revises: d2e4f6a8b9c0
Create Date: 2026-07-28 07:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a5b7c9d1e2"
down_revision: Union[str, None] = "d2e4f6a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add status column with default 'approved' so existing rows are treated
    # as approved (the pre-review-inbox behaviour).
    op.add_column(
        "events",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="approved",
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "status")
