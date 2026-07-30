"""add canonical scenario pathway linkage

Revision ID: k4d5e6f7a8b9
Revises: j3c4d5e6f7a8
Create Date: 2026-07-29 22:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k4d5e6f7a8b9"
down_revision: str | None = "j3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scenarios",
        sa.Column("pathway_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_scenarios_pathway_id_pathways",
        "scenarios",
        "pathways",
        ["pathway_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_scenarios_pathway_id", "scenarios", ["pathway_id"])

    # Preserve links already recorded on the legacy Pathway.scenario_id field.
    op.execute(
        sa.text(
            "UPDATE scenarios AS s SET pathway_id = p.id "
            "FROM pathways AS p "
            "WHERE p.scenario_id = s.id AND s.pathway_id IS NULL"
        )
    )
    # Historical manually-created scenarios used the pathway name but never
    # persisted a link. Backfill only when the match is unique within a goal.
    op.execute(
        sa.text(
            "UPDATE scenarios AS s SET pathway_id = p.id "
            "FROM pathways AS p "
            "WHERE s.pathway_id IS NULL "
            "AND p.goal_id = s.goal_id "
            "AND lower(trim(p.name)) = lower(trim(s.name)) "
            "AND (SELECT count(*) FROM pathways AS candidate "
            "     WHERE candidate.goal_id = s.goal_id "
            "     AND lower(trim(candidate.name)) = lower(trim(s.name))) = 1"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_scenarios_pathway_id", table_name="scenarios")
    op.drop_constraint(
        "fk_scenarios_pathway_id_pathways",
        "scenarios",
        type_="foreignkey",
    )
    op.drop_column("scenarios", "pathway_id")
