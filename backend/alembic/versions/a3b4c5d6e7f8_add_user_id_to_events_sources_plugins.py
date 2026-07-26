"""add user_id to events, information_sources, user_plugins

Revision ID: a3b4c5d6e7f8
Revises: 751b2b52f093
Create Date: 2026-07-27 06:00:00.000000

Adds a nullable ``user_id`` column to ``information_sources``, ``events``,
and ``user_plugins`` so each row can be owned by a specific user. Existing
rows are back-filled with the default user's id so single-user deployments
keep working without data loss.

In multi-user mode:
  - New ingestions/events are tagged with the authenticated user's id.
  - List endpoints filter by ``user_id``.
  - NULL ``user_id`` rows (legacy/global) remain visible to all users via
    ``user_id IS NULL OR user_id = :uid`` filters.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- information_sources.user_id ---
    op.add_column(
        "information_sources",
        sa.Column("user_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_information_sources_user_id",
        "information_sources",
        ["user_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_information_sources_user_id",
        "information_sources",
        "user_profiles",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- events.user_id ---
    op.add_column(
        "events",
        sa.Column("user_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_events_user_id",
        "events",
        ["user_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_events_user_id",
        "events",
        "user_profiles",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- user_plugins.user_id ---
    op.add_column(
        "user_plugins",
        sa.Column("user_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_user_plugins_user_id",
        "user_plugins",
        ["user_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_user_plugins_user_id",
        "user_plugins",
        "user_profiles",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Backfill: assign all existing rows to the default user so single-user
    # deployments keep their data and list queries (which filter by user_id)
    # continue to return rows.
    op.execute(
        """
        UPDATE information_sources
        SET user_id = '00000000-0000-0000-0000-000000000001'
        WHERE user_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE events
        SET user_id = '00000000-0000-0000-0000-000000000001'
        WHERE user_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE user_plugins
        SET user_id = '00000000-0000-0000-0000-000000000001'
        WHERE user_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_plugins_user_id", "user_plugins", type_="foreignkey")
    op.drop_index("ix_user_plugins_user_id", table_name="user_plugins")
    op.drop_column("user_plugins", "user_id")

    op.drop_constraint("fk_events_user_id", "events", type_="foreignkey")
    op.drop_index("ix_events_user_id", table_name="events")
    op.drop_column("events", "user_id")

    op.drop_constraint("fk_information_sources_user_id", "information_sources", type_="foreignkey")
    op.drop_index("ix_information_sources_user_id", table_name="information_sources")
    op.drop_column("information_sources", "user_id")
