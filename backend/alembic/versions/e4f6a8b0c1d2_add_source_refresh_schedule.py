"""add per-source auto-refresh schedule columns

Revision ID: e4f6a8b0c1d2
Revises: f3a5b7c9d1e2
Create Date: 2026-07-28 08:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4f6a8b0c1d2"
down_revision: Union[str, None] = "f3a5b7c9d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # auto_refresh: whether this source should be periodically re-fetched
    op.add_column(
        "information_sources",
        sa.Column(
            "auto_refresh",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # refresh_interval_minutes: how often to re-fetch (default 1440 = 24h)
    op.add_column(
        "information_sources",
        sa.Column(
            "refresh_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="1440",
        ),
    )
    # next_refresh_at: when the next refresh is due (NULL = not scheduled)
    op.add_column(
        "information_sources",
        sa.Column(
            "next_refresh_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_information_sources_next_refresh_at",
        "information_sources",
        ["next_refresh_at"],
    )
    # last_refreshed_at: when the source was last successfully refreshed
    op.add_column(
        "information_sources",
        sa.Column(
            "last_refreshed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("information_sources", "last_refreshed_at")
    op.drop_index(
        "ix_information_sources_next_refresh_at",
        table_name="information_sources",
    )
    op.drop_column("information_sources", "next_refresh_at")
    op.drop_column("information_sources", "refresh_interval_minutes")
    op.drop_column("information_sources", "auto_refresh")
