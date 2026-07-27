"""add_user_passkeys

Revision ID: c1d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-27 22:00:00.000000

Adds a ``user_passkeys`` table for WebAuthn / FIDO2 passkey authentication.

A single user may bind multiple passkeys (laptop Touch ID, phone Face ID,
hardware YubiKey, …). The table stores the credential id, public key,
server-side signature counter, transports, aaguid, device type, and an
optional nickname. Passkey login is gated behind an admin-configured
flag in ``app_config.passkey_login_enabled``.

Schema:
  - id              UUID primary key
  - user_id         FK → user_profiles.id (CASCADE)
  - credential_id   Base64url-encoded credential id (UNIQUE)
  - public_key      Base64url-encoded COSE public key
  - sign_count      Server-side replay-attack counter (FIDO §6.1.1)
  - transports      JSONB list of allowed transports
  - aaguid          Authenticator Attestation GUID (identifies model)
  - device_type     'singleDevice' | 'multiDevice'
  - backed_up       Whether the passkey is synced across devices
  - nickname        Human-readable label set by the user
  - created_at      Timestamp

Constraints:
  - UNIQUE (credential_id) — same credential can't be bound to two users
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d3e4f5a6b7"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_passkeys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("credential_id", sa.Text(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transports", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "aaguid",
            sa.String(length=64),
            nullable=False,
            server_default="00000000-0000-0000-0000-000000000000",
        ),
        sa.Column("device_type", sa.String(length=32), nullable=False, server_default="multiDevice"),
        sa.Column("backed_up", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("nickname", sa.String(length=128), nullable=False, server_default=""),
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
        sa.UniqueConstraint("credential_id", name="uq_user_passkey_credential_id"),
    )
    op.create_index(
        "ix_user_passkeys_user_id",
        "user_passkeys",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_passkeys_credential_id",
        "user_passkeys",
        ["credential_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_passkeys_credential_id", table_name="user_passkeys"
    )
    op.drop_index("ix_user_passkeys_user_id", table_name="user_passkeys")
    op.drop_table("user_passkeys")
