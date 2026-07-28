"""widen_passkey_device_type

Revision ID: d2e4f6a8b9c0
Revises: c1d3e4f5a6b7
Create Date: 2026-07-27 23:30:00.000000

Widens ``user_passkeys.device_type`` from VARCHAR(32) to VARCHAR(64).

The webauthn 3.0.0 library's ``CredentialDeviceType`` enum, when
converted via ``str()``, yields values like
``"CredentialDeviceType.SINGLE_DEVICE"`` (36 chars), which exceed the
original VARCHAR(32) column width and cause
``StringDataRightTruncation`` errors on INSERT. Switching to ``.name``
yields ``"SINGLE_DEVICE"`` (13 chars), but we widen the column to
VARCHAR(64) anyway for headroom against future library changes.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e4f6a8b9c0"
down_revision: str | None = "c1d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "user_passkeys",
        "device_type",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
        existing_server_default="multiDevice",
    )


def downgrade() -> None:
    op.alter_column(
        "user_passkeys",
        "device_type",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
        existing_server_default="multiDevice",
    )
