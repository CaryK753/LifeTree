"""Data-driven model parameter tables.

Per project plan §11.2 缺口 G: the reasoning engine previously hardcoded
all aggregation constants (base probabilities, correlation weights, risk
level mappings) as magic numbers inside ``bayesian.py`` / ``factor_model.py``
/ ``survival.py``. These tables externalize them so admins can tune per
goal_type / region, and so real-outcome data can later calibrate them via
maximum-likelihood / Bayesian update.

Tables:
    - ``model_params``        — versioned key/value parameter store, scoped
                                by goal_type + region. ``calibrated`` flag
                                distinguishes heuristic defaults from
                                data-fitted values.
    - ``prediction_outcomes`` — one row per ScenarioRun whose goal has
                                reached a terminal state (achieved /
                                abandoned). Stores the predicted P50 +
                                factor snapshot alongside the actual
                                outcome, so ``calibrate_model_params``
                                can compute Brier scores and fit params.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import TimestampMixin, UUIDPkMixin


class ModelParam(TimestampMixin, Base):
    """A single tunable parameter for the reasoning engine.

    The (goal_type, region, key) triple is unique — lookups resolve the
    most specific match first (goal_type+region), then goal_type+global,
    then the ``__global__`` default row.

    ``calibrated=False`` marks heuristic defaults; once
    ``calibrate_model_params`` fits a value from real outcomes it flips
    the flag and bumps ``calibration_sample_size``.
    """

    __tablename__ = "model_params"
    __table_args__ = (
        UniqueConstraint(
            "goal_type", "region", "key", name="uq_model_params_scope_key"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: __import__("uuid").uuid4().hex
    )
    # Scope: use "__global__" for the unscoped default; otherwise a goal_type
    # tag like "immigration" / "study_abroad" / "career".
    goal_type: Mapped[str] = mapped_column(String(64), default="__global__", index=True)
    # region: "__global__" or an ISO-3166 alpha-2 code (CA / US / GB …).
    region: Mapped[str] = mapped_column(String(16), default="__global__", index=True)
    # Parameter key, e.g. "requirement_base_prob.met" / "risk_level_p.high"
    # / "correlation_alpha" / "weight_blend_factor".
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Stored as text to preserve float/int/bool/dict uniformly; callers
    # parse via the typed accessor in ``ModelParamStore``.
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), default="float")
    # float | int | bool | json

    calibrated: Mapped[bool] = mapped_column(
        String(5), default="false", server_default="false"
    )
    # SQLite-friendly bool storage (true/false strings); the service layer
    # coerces. Using String avoids dialect-specific Boolean quirks.
    calibration_sample_size: Mapped[int] = mapped_column(Integer, default=0)
    last_calibrated_at: Mapped[datetime | None] = mapped_column(
        String(64), nullable=True
    )
    # Stored as ISO string for cross-dialect safety; service coerces.

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ModelParam {self.goal_type}:{self.region}:{self.key}>"


class PredictionOutcome(UUIDPkMixin, TimestampMixin, Base):
    """A prediction-vs-actual record for model calibration.

    Written when a Goal reaches a terminal status (achieved / abandoned).
    The ``predicted`` snapshot is lifted from the most recent ScenarioRun
    before the terminal transition; ``actual`` records the realized result.
    """

    __tablename__ = "prediction_outcomes"
    __table_args__ = (
        UniqueConstraint("goal_id", name="uq_prediction_outcomes_goal"),
    )

    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="CASCADE")
    )
    scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    goal_type: Mapped[str] = mapped_column(String(64), default="__global__")
    region: Mapped[str] = mapped_column(String(16), default="__global__")

    # Predicted snapshot
    predicted_p50: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_p10: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_at: Mapped[datetime | None] = mapped_column(String(64), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    factor_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # Actual outcome
    actual_outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    # 'achieved' | 'failed' | 'abandoned'
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Binary 0/1 for Brier-score computation (achieved=1, else 0).
    actual_binary: Mapped[int] = mapped_column(Integer, default=0)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


Index("ix_prediction_outcomes_goal", PredictionOutcome.goal_id)
Index("ix_prediction_outcomes_scope", PredictionOutcome.goal_type, PredictionOutcome.region)
Index("ix_prediction_outcomes_scenario", PredictionOutcome.scenario_id)
Index("ix_prediction_outcomes_run", PredictionOutcome.run_id)
