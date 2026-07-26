"""add_user_auth_fields

Add password_hash, role, is_enabled columns to user_profiles for
multi-user authentication support.

Revision ID: a1b2c3d4e5f6
Revises: 751b2b52f093
Create Date: 2026-07-27 02:00:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '751b2b52f093'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'user_profiles',
        sa.Column('password_hash', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'user_profiles',
        sa.Column('role', sa.String(length=16), nullable=False, server_default='user'),
    )
    op.add_column(
        'user_profiles',
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
    )
    op.create_index(
        op.f('ix_user_profiles_role'),
        'user_profiles',
        ['role'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_user_profiles_role'), table_name='user_profiles')
    op.drop_column('user_profiles', 'is_enabled')
    op.drop_column('user_profiles', 'role')
    op.drop_column('user_profiles', 'password_hash')
