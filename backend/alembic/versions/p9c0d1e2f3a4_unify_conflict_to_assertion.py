"""unify conflict detection to assertion level

Revision ID: p9c0d1e2f3a4
Revises: o8b9c0d1e2f3
Create Date: 2026-08-07 20:30:00.000000

Implements §B.1 of the cross-validation spec:

1. ``assertions.engine`` — search-engine provenance (nullable, indexed).
   Inherited from ``InformationSource.meta.engine`` at ingestion time.
   Used by cross-engine consensus voting in ``auto_merge_node``.

2. ``assertions.conflicting_with_id`` FK — activates the previously dead
   column (it existed but had no foreign-key constraint). Now references
   ``assertions.id`` with ``ON DELETE SET NULL``.

3. ``conflict_resolutions`` extension — three new columns:
   - ``assertion_ids`` (JSONB list[str]) — all participating Assertion IDs
   - ``winning_assertion_id`` (String(36), nullable) — the winning Assertion
   - ``cross_engine_consensus`` (JSONB dict) — voting result from auto_merge

This migration is purely additive — no existing data is touched. The
``conflicting_with_id`` FK is safe because the column was previously unused
(all existing values are NULL).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "p9c0d1e2f3a4"
down_revision: Union[str, None] = "o8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Assertion.engine — search-engine provenance
    op.add_column(
        "assertions",
        sa.Column("engine", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_assertions_engine",
        "assertions",
        ["engine"],
    )

    # 2. Activate conflicting_with_id FK (previously a dead column).
    #    ON DELETE SET NULL — if the referenced assertion is deleted, the
    #    pointer is cleared rather than cascading the deletion.
    op.create_foreign_key(
        "fk_assertions_conflicting_with_id",
        "assertions",
        "assertions",
        ["conflicting_with_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. ConflictResolution extension — Assertion-level metadata.
    op.add_column(
        "conflict_resolutions",
        sa.Column(
            "assertion_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column(
        "conflict_resolutions",
        sa.Column("winning_assertion_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "conflict_resolutions",
        sa.Column(
            "cross_engine_consensus",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    # Reverse order of upgrade().
    op.drop_column("conflict_resolutions", "cross_engine_consensus")
    op.drop_column("conflict_resolutions", "winning_assertion_id")
    op.drop_column("conflict_resolutions", "assertion_ids")

    op.drop_constraint(
        "fk_assertions_conflicting_with_id",
        "assertions",
        type_="foreignkey",
    )

    op.drop_index("ix_assertions_engine", table_name="assertions")
    op.drop_column("assertions", "engine")
