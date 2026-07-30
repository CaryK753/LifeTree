"""deterministic scenario to pathway backfill

Revision ID: n7g8h9i0j1k2
Revises: m6f7a8b9c0d1
Create Date: 2026-07-30
"""

from alembic import op

revision = "n7g8h9i0j1k2"
down_revision = "m6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A pathway may have multiple scenario sandboxes. The previous UPDATE ...
    # FROM migration could choose any matching row. Prefer the most recently
    # computed scenario, and never overwrite newer pathway-native results.
    op.execute(
        """
        WITH ranked_scenarios AS (
            SELECT
                s.*,
                ROW_NUMBER() OVER (
                    PARTITION BY s.pathway_id
                    ORDER BY
                        s.computed_at DESC NULLS LAST,
                        s.updated_at DESC NULLS LAST,
                        s.created_at DESC,
                        s.id DESC
                ) AS rank
            FROM scenarios s
            WHERE s.pathway_id IS NOT NULL
        )
        UPDATE pathways p
        SET
            assumptions = COALESCE(s.assumptions, '{}'::jsonb),
            success_probability = COALESCE(s.success_probability, '{}'::jsonb),
            risk_score = s.risk_score,
            key_risk_factors = COALESCE(s.key_risk_factors, '[]'::jsonb),
            impact_threshold = COALESCE(s.impact_threshold, 0.05),
            computed_at = s.computed_at
        FROM ranked_scenarios s
        WHERE s.rank = 1
          AND s.pathway_id = p.id
          AND (
              p.computed_at IS NULL
              OR (s.computed_at IS NOT NULL AND s.computed_at > p.computed_at)
          )
        """
    )


def downgrade() -> None:
    # This migration only corrects data chosen non-deterministically by the
    # preceding backfill; reverting values safely is not possible.
    pass
