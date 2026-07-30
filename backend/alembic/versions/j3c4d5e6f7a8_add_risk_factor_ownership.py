"""add risk factor ownership and identity

Revision ID: j3c4d5e6f7a8
Revises: i2b3c4d5e6f7
Create Date: 2026-07-29 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j3c4d5e6f7a8"
down_revision: str | None = "i2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "risk_factors",
        sa.Column("user_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "risk_factors",
        sa.Column("identity_key", sa.String(64), nullable=True),
    )
    op.create_foreign_key(
        "fk_risk_factors_user_id_user_profiles",
        "risk_factors",
        "user_profiles",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_risk_factors_user_id", "risk_factors", ["user_id"])
    op.create_index(
        "uq_risk_factors_user_identity",
        "risk_factors",
        ["user_id", "identity_key"],
        unique=True,
        postgresql_where=sa.text(
            "user_id IS NOT NULL AND identity_key IS NOT NULL AND deleted_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_risk_factors_user_identity", table_name="risk_factors")
    op.drop_index("ix_risk_factors_user_id", table_name="risk_factors")
    op.drop_constraint(
        "fk_risk_factors_user_id_user_profiles",
        "risk_factors",
        type_="foreignkey",
    )
    op.drop_column("risk_factors", "identity_key")
    op.drop_column("risk_factors", "user_id")
