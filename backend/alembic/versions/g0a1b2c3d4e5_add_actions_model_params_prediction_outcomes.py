"""add actions, model_params, prediction_outcomes tables

Revision ID: g0a1b2c3d4e5
Revises: a6b8d0f2c4e6
Create Date: 2026-07-29 22:00:00.000000

Implements project plan §11.2 缺口 C (Action 实体) + 缺口 G (模型参数外置化
+ 预测结果回流管道). Three new tables:

- ``actions``: first-class Action entities that the reasoning engine,
  agent and UI create/track/complete. Replaces the free-text
  ``optimal_action_sequence`` list. ROI = expected_prob_lift / cost.
- ``model_params``: externalizes all hardcoded reasoning-engine constants
  (base probabilities, risk-level mappings, correlation alpha, weight
  blend factors) so admins can tune per goal_type/region and so real
  outcome data can later calibrate them. Seeded with the current default
  values so behavior is unchanged on upgrade.
- ``prediction_outcomes``: prediction-vs-actual records written when a
  Goal reaches a terminal state, used by ``calibrate_model_params`` to
  compute Brier scores and fit parameters.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g0a1b2c3d4e5"
down_revision: str | None = "a6b8d0f2c4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Default heuristic parameters seeded into model_params. These mirror the
# hardcoded constants in bayesian.py / factor_model.py / survival.py at
# the time of this migration, so behavior is unchanged on upgrade. Admins
# can tune via the /admin/model-params UI; calibrate_model_params can
# later flip ``calibrated`` to true once real outcomes are collected.
_DEFAULT_PARAMS: list[tuple[str, str, str, str, str]] = [
    # (key, value, value_type, notes, scope_default)
    # Requirement base probabilities (bayesian._req_success_prob)
    ("requirement_base_prob.met", "0.92", "float", "P(user meets a 'met' requirement)", "0.92"),
    ("requirement_base_prob.partial", "0.60", "float", "P(user meets a 'partial' requirement)", "0.60"),
    ("requirement_base_prob.missing", "0.40", "float", "P(user meets a 'missing' requirement)", "0.40"),
    ("requirement_base_prob.unknown", "0.50", "float", "P(user meets an 'unknown' requirement)", "0.50"),
    # Weight blend factor (bayesian._req_success_prob)
    ("requirement_weight_blend", "0.2", "float", "Blend factor pulling base prob toward 1.0 for low-weight reqs", "0.2"),
    # Risk level → failure probability (bayesian._risk_failure_prob)
    ("risk_level_p.low", "0.08", "float", "P(low-level risk materializes)", "0.08"),
    ("risk_level_p.medium", "0.20", "float", "P(medium-level risk materializes)", "0.20"),
    ("risk_level_p.high", "0.40", "float", "P(high-level risk materializes)", "0.40"),
    # Risk probability/impact blend (bayesian._risk_failure_prob)
    ("risk_level_blend", "0.5", "float", "Blend between level-based p and explicit rf.probability", "0.5"),
    # Correlated risk survival blend (factor_model.correlated_risk_survival)
    ("correlation_alpha", "0.3", "float", "Independence weight in copula blend (0=fully correlated, 1=fully independent)", "0.3"),
    # Survival estimator (survival.SurvivalEstimator)
    ("survival_horizon_months", "36", "int", "Survival curve horizon in months", "36"),
    ("survival_shape_offset", "1.0", "float", "Weibull shape offset (shape = offset + (1 - p_success))", "1.0"),
    ("survival_scale_offset", "0.5", "float", "Weibull scale offset (scale = max(1, horizon * (1 - p + offset)))", "0.5"),
]


def upgrade() -> None:
    # ---------- actions ----------
    op.create_table(
        "actions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("scenario_id", sa.String(36), nullable=True),
        sa.Column("pathway_id", sa.String(36), nullable=True),
        sa.Column("requirement_id", sa.String(36), nullable=True),
        sa.Column("risk_factor_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("stage", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("due_at", sa.Date(), nullable=True),
        sa.Column("recurrence", sa.String(16), nullable=False, server_default=""),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("expected_prob_lift", sa.Float(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.String(64), nullable=True),
        sa.Column("actual_cost", sa.Float(), nullable=True),
        sa.Column("actual_prob_lift", sa.Float(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("source_run_id", sa.String(36), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["risk_factor_id"], ["risk_factors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_actions_user_status", "actions", ["user_id", "status"])
    op.create_index("ix_actions_goal", "actions", ["goal_id"])
    op.create_index("ix_actions_due", "actions", ["due_at"])
    op.create_index("ix_actions_scenario", "actions", ["scenario_id"])
    op.create_index("ix_actions_pathway", "actions", ["pathway_id"])
    op.create_index("ix_actions_requirement", "actions", ["requirement_id"])
    op.create_index("ix_actions_risk_factor", "actions", ["risk_factor_id"])
    op.create_index("ix_actions_stage", "actions", ["stage"])

    # ---------- model_params ----------
    op.create_table(
        "model_params",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("goal_type", sa.String(64), nullable=False, server_default="__global__"),
        sa.Column("region", sa.String(16), nullable=False, server_default="__global__"),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(16), nullable=False, server_default="float"),
        sa.Column("calibrated", sa.String(5), nullable=False, server_default="false"),
        sa.Column("calibration_sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_calibrated_at", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("goal_type", "region", "key", name="uq_model_params_scope_key"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_params_goal_type", "model_params", ["goal_type"])
    op.create_index("ix_model_params_region", "model_params", ["region"])

    # Seed default heuristic parameters (all uncalibrated). Using the
    # __global__ scope so they apply to every goal_type / region unless a
    # more specific row exists.
    now = datetime.now(timezone.utc)
    seed_rows = []
    for key, value, vtype, notes, _ in _DEFAULT_PARAMS:
        import uuid as _uuid
        seed_rows.append({
            "id": _uuid.uuid4().hex,
            "goal_type": "__global__",
            "region": "__global__",
            "key": key,
            "value": value,
            "value_type": vtype,
            "calibrated": "false",
            "calibration_sample_size": 0,
            "last_calibrated_at": None,
            "notes": notes,
            "created_at": now,
            "updated_at": now,
        })
    op.bulk_insert(sa.table(
        "model_params",
        sa.column("id", sa.String),
        sa.column("goal_type", sa.String),
        sa.column("region", sa.String),
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
        sa.column("calibrated", sa.String),
        sa.column("calibration_sample_size", sa.Integer),
        sa.column("last_calibrated_at", sa.String),
        sa.column("notes", sa.Text),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    ), seed_rows)

    # ---------- prediction_outcomes ----------
    op.create_table(
        "prediction_outcomes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("scenario_id", sa.String(36), nullable=True),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("goal_type", sa.String(64), nullable=False, server_default="__global__"),
        sa.Column("region", sa.String(16), nullable=False, server_default="__global__"),
        sa.Column("predicted_p50", sa.Float(), nullable=True),
        sa.Column("predicted_p10", sa.Float(), nullable=True),
        sa.Column("predicted_p90", sa.Float(), nullable=True),
        sa.Column("predicted_at", sa.String(64), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("factor_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("actual_outcome", sa.String(16), nullable=False),
        sa.Column("actual_date", sa.Date(), nullable=True),
        sa.Column("actual_binary", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prediction_outcomes_goal", "prediction_outcomes", ["goal_id"])
    op.create_index("ix_prediction_outcomes_scope", "prediction_outcomes", ["goal_type", "region"])
    op.create_index("ix_prediction_outcomes_scenario", "prediction_outcomes", ["scenario_id"])
    op.create_index("ix_prediction_outcomes_run", "prediction_outcomes", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_prediction_outcomes_run", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_scenario", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_scope", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_goal", table_name="prediction_outcomes")
    op.drop_table("prediction_outcomes")

    op.drop_index("ix_model_params_region", table_name="model_params")
    op.drop_index("ix_model_params_goal_type", table_name="model_params")
    op.drop_table("model_params")

    op.drop_index("ix_actions_stage", table_name="actions")
    op.drop_index("ix_actions_risk_factor", table_name="actions")
    op.drop_index("ix_actions_requirement", table_name="actions")
    op.drop_index("ix_actions_pathway", table_name="actions")
    op.drop_index("ix_actions_scenario", table_name="actions")
    op.drop_index("ix_actions_due", table_name="actions")
    op.drop_index("ix_actions_goal", table_name="actions")
    op.drop_index("ix_actions_user_status", table_name="actions")
    op.drop_table("actions")
