"""merge scenario into pathway

Revision ID: m6f7a8b9c0d1
Revises: l5e6f7a8b9c0
Create Date: 2026-07-30

Merges Scenario's computation fields into Pathway so that the decision
tree node is the single source of truth for both route selection and
probability reasoning. The scenarios table is kept for backward compat
but new writes go to pathways.

Fields added to pathways:
- assumptions (JSONB) — what-if assumptions previously on Scenario
- success_probability (JSONB) — {p10, p50, p90} cached output
- risk_score (Float) — overall risk score
- key_risk_factors (JSONB) — top risk factors from last computation
- impact_threshold (Float) — branch retention threshold
- computed_at (DateTime) — last reasoning engine run
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "m6f7a8b9c0d1"
down_revision = "l5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add Scenario's computation fields to Pathway.
    op.add_column("pathways", sa.Column("assumptions", JSONB(), nullable=False, server_default="{}"))
    op.add_column("pathways", sa.Column("success_probability", JSONB(), nullable=False, server_default="{}"))
    op.add_column("pathways", sa.Column("risk_score", sa.Float(), nullable=True))
    op.add_column("pathways", sa.Column("key_risk_factors", JSONB(), nullable=False, server_default="[]"))
    op.add_column("pathways", sa.Column("impact_threshold", sa.Float(), nullable=False, server_default="0.05"))
    op.add_column("pathways", sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True))

    # 2. Backfill: copy values from linked Scenario → Pathway.
    # Use the existing pathway.scenario_id soft link.
    op.execute("""
        UPDATE pathways p
        SET
            assumptions        = COALESCE(s.assumptions, '{}'::jsonb),
            success_probability = COALESCE(s.success_probability, '{}'::jsonb),
            risk_score         = s.risk_score,
            key_risk_factors   = COALESCE(s.key_risk_factors, '[]'::jsonb),
            impact_threshold   = COALESCE(s.impact_threshold, 0.05),
            computed_at        = s.computed_at
        FROM scenarios s
        WHERE p.scenario_id = s.id
    """)

    # 3. Also backfill from the reverse direction (scenarios.pathway_id → pathways).
    # This catches cases where pathway.scenario_id was never set but the FK
    # on scenarios.pathway_id exists (added in migration k4d5e6f7a8b9).
    op.execute("""
        UPDATE pathways p
        SET
            assumptions        = COALESCE(s.assumptions, p.assumptions),
            success_probability = COALESCE(NULLIF(p.success_probability::text, '{}'), s.success_probability),
            risk_score         = COALESCE(p.risk_score, s.risk_score),
            key_risk_factors   = COALESCE(NULLIF(p.key_risk_factors::text, '[]'), s.key_risk_factors),
            impact_threshold   = COALESCE(NULLIF(p.impact_threshold, 0.05), s.impact_threshold),
            computed_at        = COALESCE(p.computed_at, s.computed_at)
        FROM scenarios s
        WHERE s.pathway_id = p.id
          AND p.computed_at IS NULL
    """)


def downgrade() -> None:
    op.drop_column("pathways", "computed_at")
    op.drop_column("pathways", "impact_threshold")
    op.drop_column("pathways", "key_risk_factors")
    op.drop_column("pathways", "risk_score")
    op.drop_column("pathways", "success_probability")
    op.drop_column("pathways", "assumptions")
