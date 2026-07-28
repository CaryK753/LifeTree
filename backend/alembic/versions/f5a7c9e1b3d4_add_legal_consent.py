"""add legal consent audit fields to user profiles

Revision ID: f5a7c9e1b3d4
Revises: e4f6a8b0c1d2
Create Date: 2026-07-28 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a7c9e1b3d4"
down_revision: str | None = "e4f6a8b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("accepted_terms_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("terms_version", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("privacy_version", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "privacy_version")
    op.drop_column("user_profiles", "terms_version")
    op.drop_column("user_profiles", "accepted_terms_at")
