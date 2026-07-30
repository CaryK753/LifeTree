"""add decision tree fields + pathway_requirements/pathway_risk_factors M2M

Revision ID: i2b3c4d5e6f7
Revises: h1b2c3d4e5f6
Create Date: 2026-07-30 00:30:00.000000

Implements §11.3 self-growing decision tree:
1. Extends pathways with node_type, decision_question, tree_level,
   display_order, evolution_hint fields.
2. Creates pathway_requirements M2M table (replaces Requirement.pathway_id
   one-to-many — requirements can now be shared across branches).
3. Creates pathway_risk_factors M2M table (fixes bug where all branches in
   the same region showed identical key_risk_factors — risk factors are now
   per-pathway, not global-by-region).
4. Migrates existing data: copies Requirement.pathway_id → M2M rows, and
   seeds pathway_risk_factors from the old region-based query.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op

revision: str = "i2b3c4d5e6f7"
down_revision: str | None = "h1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add decision-tree columns to pathways
    op.add_column("pathways", sa.Column("node_type", sa.String(16), server_default="branch", nullable=False))
    op.add_column("pathways", sa.Column("decision_question", sa.Text(), nullable=True))
    op.add_column("pathways", sa.Column("tree_level", sa.Integer(), server_default="0", nullable=False))
    op.add_column("pathways", sa.Column("display_order", sa.Integer(), server_default="0", nullable=False))
    op.add_column("pathways", sa.Column("evolution_hint", sa.Text(), nullable=True))

    # Mark top-level pathways (no parent) as 'root' node_type
    op.execute(
        "UPDATE pathways SET node_type = 'root' WHERE parent_pathway_id IS NULL"
    )

    # 2. Make requirement.pathway_id nullable (M2M is now the primary link)
    op.alter_column("requirements", "pathway_id", nullable=True)

    # 3. Create pathway_requirements M2M table
    op.create_table(
        "pathway_requirements",
        sa.Column("pathway_id", sa.String(36), sa.ForeignKey("pathways.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("requirement_id", sa.String(36), sa.ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("is_blocking", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.Text(), nullable=True),
    )
    op.create_index("ix_pathway_requirements_pathway", "pathway_requirements", ["pathway_id"])
    op.create_index("ix_pathway_requirements_requirement", "pathway_requirements", ["requirement_id"])

    # 4. Create pathway_risk_factors M2M table
    op.create_table(
        "pathway_risk_factors",
        sa.Column("pathway_id", sa.String(36), sa.ForeignKey("pathways.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("risk_factor_id", sa.String(36), sa.ForeignKey("risk_factors.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.Text(), nullable=True),
    )
    op.create_index("ix_pathway_risk_factors_pathway", "pathway_risk_factors", ["pathway_id"])
    op.create_index("ix_pathway_risk_factors_risk", "pathway_risk_factors", ["risk_factor_id"])

    # 5. Data migration: copy existing Requirement.pathway_id → M2M rows
    now_iso = datetime.now(timezone.utc).isoformat()
    op.execute(
        sa.text(
            "INSERT INTO pathway_requirements (pathway_id, requirement_id, is_blocking, created_at) "
            "SELECT pathway_id, id, true, :now FROM requirements WHERE pathway_id IS NOT NULL"
        ).bindparams(now=now_iso)
    )

    # 6. Data migration: seed pathway_risk_factors from region-based query
    # Global (NULL-region) templates can be shared. A regional risk is linked
    # automatically only when that region identifies exactly one pathway;
    # otherwise the association is ambiguous and must be adopted explicitly.
    op.execute(
        sa.text(
            "INSERT INTO pathway_risk_factors (pathway_id, risk_factor_id, created_at) "
            "SELECT p.id, rf.id, :now "
            "FROM pathways p "
            "CROSS JOIN risk_factors rf "
            "WHERE p.deleted_at IS NULL "
            "AND rf.deleted_at IS NULL "
            "AND (rf.region IS NULL OR ("
            "  p.region = rf.region AND "
            "  (SELECT count(*) FROM pathways peer "
            "   WHERE peer.goal_id = p.goal_id "
            "   AND peer.deleted_at IS NULL "
            "   AND peer.region = p.region) = 1"
            "))"
        ).bindparams(now=now_iso)
    )


def downgrade() -> None:
    op.drop_table("pathway_risk_factors")
    op.drop_table("pathway_requirements")
    op.alter_column("requirements", "pathway_id", nullable=False)
    op.drop_column("pathways", "evolution_hint")
    op.drop_column("pathways", "display_order")
    op.drop_column("pathways", "tree_level")
    op.drop_column("pathways", "decision_question")
    op.drop_column("pathways", "node_type")
