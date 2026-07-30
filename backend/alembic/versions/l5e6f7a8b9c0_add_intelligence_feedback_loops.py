"""add intelligence feedback loop persistence

Revision ID: l5e6f7a8b9c0
Revises: k4d5e6f7a8b9
Create Date: 2026-07-29 23:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "l5e6f7a8b9c0"
down_revision: str | None = "k4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_plugins",
        sa.Column("manifest", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("assertions", sa.Column("user_id", sa.String(36), nullable=True))
    op.add_column("assertions", sa.Column("predicate", sa.String(128), nullable=False, server_default="claims"))
    op.add_column("assertions", sa.Column("object_value", postgresql.JSONB(), nullable=True))
    op.add_column("assertions", sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assertions", sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assertions", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assertions", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column("assertions", sa.Column("source_excerpt", sa.Text(), nullable=True))
    op.add_column("assertions", sa.Column("resolved_by_user_id", sa.String(36), nullable=True))
    op.add_column("assertions", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_assertions_user_id", "assertions", "user_profiles",
        ["user_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_assertions_user_id", "assertions", ["user_id"])
    op.create_index("ix_assertions_content_hash", "assertions", ["content_hash"])
    op.create_index("ix_assertions_temporal", "assertions", ["subject", "predicate", "valid_from"])
    op.add_column("actions", sa.Column("recurrence_parent_id", sa.String(36), nullable=True))
    op.add_column("actions", sa.Column("occurrence_key", sa.String(128), nullable=True))
    op.add_column("actions", sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_actions_recurrence_parent", "actions", "actions",
        ["recurrence_parent_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_actions_recurrence_parent", "actions", ["recurrence_parent_id"])
    op.create_unique_constraint("uq_actions_occurrence_key", "actions", ["occurrence_key"])

    op.execute(sa.text(
        "DELETE FROM prediction_outcomes p USING prediction_outcomes newer "
        "WHERE p.goal_id = newer.goal_id AND "
        "(p.created_at < newer.created_at OR (p.created_at = newer.created_at AND p.id < newer.id))"
    ))
    op.create_unique_constraint(
        "uq_prediction_outcomes_goal", "prediction_outcomes", ["goal_id"]
    )

    op.create_table(
        "calibration_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("goal_type", sa.String(64), nullable=False, server_default="__global__"),
        sa.Column("region", sa.String(16), nullable=False, server_default="__global__"),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brier_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("previous_brier_score", sa.Float(), nullable=True),
        sa.Column("drift_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("drift_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("calibrated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reliability_curve", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("goal_type", "region", "window_end", name="uq_calibration_report_scope_window"),
    )
    op.create_index("ix_calibration_reports_scope", "calibration_reports", ["goal_type", "region"])

    op.create_table(
        "evolution_milestones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("scenario_id", sa.String(36), nullable=False),
        sa.Column("projection_key", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("impact", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="expected"),
        sa.Column("expected_event_id", sa.String(36), nullable=True),
        sa.Column("matched_event_id", sa.String(36), nullable=True),
        sa.Column("comparison_score", sa.Float(), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["expected_event_id"], ["events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["matched_event_id"], ["events.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("scenario_id", "projection_key", name="uq_evolution_projection_key"),
    )
    op.create_index("ix_evolution_milestones_user_id", "evolution_milestones", ["user_id"])
    op.create_index("ix_evolution_milestones_goal_id", "evolution_milestones", ["goal_id"])
    op.create_index("ix_evolution_milestones_scenario_id", "evolution_milestones", ["scenario_id"])
    op.create_index("ix_evolution_milestones_due", "evolution_milestones", ["status", "due_at"])

    _create_review_tables()

    op.create_table(
        "web_push_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_web_push_subscriptions_user_id", "web_push_subscriptions", ["user_id"])
    op.create_index("ix_web_push_user_enabled", "web_push_subscriptions", ["user_id", "enabled"])


def _create_review_tables() -> None:
    op.create_table(
        "risk_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(32), nullable=False, server_default="other"),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("urgency", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("cluster_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("affected_goals_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("impact_preview", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("adopted_risk_factor_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_risk_proposal_user_fingerprint"),
    )
    op.create_index("ix_risk_proposals_user_id", "risk_proposals", ["user_id"])
    op.create_index("ix_risk_proposals_user_status", "risk_proposals", ["user_id", "status"])

    op.create_table(
        "source_accuracy_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("evidence_key", sa.String(160), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("prior_alpha", sa.Float(), nullable=False),
        sa.Column("prior_beta", sa.Float(), nullable=False),
        sa.Column("posterior_alpha", sa.Float(), nullable=False),
        sa.Column("posterior_beta", sa.Float(), nullable=False),
        sa.Column("resulting_score", sa.Float(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["information_sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_id", "evidence_key", name="uq_source_accuracy_evidence"),
    )
    op.create_index("ix_source_accuracy_logs_user_id", "source_accuracy_logs", ["user_id"])
    op.create_index("ix_source_accuracy_logs_source_id", "source_accuracy_logs", ["source_id"])

    op.create_table(
        "conflict_resolutions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resolution_key", sa.String(200), nullable=False, unique=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("predicate", sa.String(32), nullable=False),
        sa.Column("winning_source_id", sa.String(36), nullable=False),
        sa.Column("winning_object_id", sa.String(36), nullable=False),
        sa.Column("losing_source_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_conflict_resolutions_user_id", "conflict_resolutions", ["user_id"])


def downgrade() -> None:
    op.drop_table("web_push_subscriptions")
    op.drop_table("conflict_resolutions")
    op.drop_table("source_accuracy_logs")
    op.drop_index("ix_risk_proposals_user_status", table_name="risk_proposals")
    op.drop_table("risk_proposals")
    op.drop_index("ix_evolution_milestones_due", table_name="evolution_milestones")
    op.drop_table("evolution_milestones")
    op.drop_table("calibration_reports")
    op.drop_constraint("uq_prediction_outcomes_goal", "prediction_outcomes", type_="unique")
    op.drop_constraint("uq_actions_occurrence_key", "actions", type_="unique")
    op.drop_index("ix_actions_recurrence_parent", table_name="actions")
    op.drop_constraint("fk_actions_recurrence_parent", "actions", type_="foreignkey")
    op.drop_column("actions", "reminder_sent_at")
    op.drop_column("actions", "occurrence_key")
    op.drop_column("actions", "recurrence_parent_id")
    op.drop_column("user_plugins", "manifest")
    op.drop_index("ix_assertions_temporal", table_name="assertions")
    op.drop_index("ix_assertions_content_hash", table_name="assertions")
    op.drop_index("ix_assertions_user_id", table_name="assertions")
    op.drop_constraint("fk_assertions_user_id", "assertions", type_="foreignkey")
    for column in (
        "resolved_at", "resolved_by_user_id", "source_excerpt", "content_hash",
        "observed_at", "valid_to", "valid_from", "object_value", "predicate", "user_id",
    ):
        op.drop_column("assertions", column)
