"""add avatar_url to user_profiles

Revision ID: 0001_add_user_avatar
Revises:
Create Date: 2026-07-26

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_add_user_avatar"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("avatar_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "avatar_url")
