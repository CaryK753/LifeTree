"""add_user_plugins

Revision ID: 751b2b52f093
Revises: 0002
Create Date: 2026-07-26 19:25:27.878043

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '751b2b52f093'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('user_plugins',
    sa.Column('plugin_id', sa.String(length=64), nullable=False),
    sa.Column('original_filename', sa.String(length=128), nullable=False),
    sa.Column('source_sha256', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_plugins_enabled'), 'user_plugins', ['enabled'], unique=False)
    op.create_index(op.f('ix_user_plugins_plugin_id'), 'user_plugins', ['plugin_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_plugins_plugin_id'), table_name='user_plugins')
    op.drop_index(op.f('ix_user_plugins_enabled'), table_name='user_plugins')
    op.drop_table('user_plugins')
