"""add_user_oauth_links

Revision ID: b1c2d3e4f5a6
Revises: a3b4c5d6e7f8
Create Date: 2026-07-27 19:00:00.000000

Adds a ``user_oauth_links`` table so a single user can bind multiple
OAuth providers (GitHub + Google + GitLab, …) to their account. The
existing ``user_profiles.external_id`` column is kept for backward
compatibility with the OAuth login-creation flow; this table is the
source of truth for the bind/unbind flow on the settings page.

Schema:
  - id            UUID primary key
  - user_id       FK → user_profiles.id (CASCADE)
  - provider_id   OAuth provider id (matches OAuthProvider.id in app_config)
  - external_sub  The provider-unique subject id (sub / id field from userinfo)
  - created_at    timestamp

Constraints:
  - UNIQUE (user_id, provider_id)     — one binding per provider per user
  - UNIQUE (provider_id, external_sub) — one user per provider account
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_oauth_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("external_sub", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "provider_id",
            name="uq_oauth_link_user_provider",
        ),
        sa.UniqueConstraint(
            "provider_id",
            "external_sub",
            name="uq_oauth_link_provider_sub",
        ),
    )
    op.create_index(
        "ix_user_oauth_links_user_id",
        "user_oauth_links",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_oauth_links_provider_id",
        "user_oauth_links",
        ["provider_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_oauth_links_provider_id", table_name="user_oauth_links"
    )
    op.drop_index("ix_user_oauth_links_user_id", table_name="user_oauth_links")
    op.drop_table("user_oauth_links")
