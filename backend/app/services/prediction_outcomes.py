"""Prediction-outcome reflow pipeline (缺口 G — P0 线A g2).

When a Goal transitions to a terminal status (achieved / abandoned /
failed), ``record_outcome`` snapshots the most recent completed
ScenarioRun's predicted P50/P10/P90 + factor contributions alongside
the realized outcome. The accumulated rows feed ``compute_brier_score``
for the admin calibration view, which in turn drives
``calibrate_model_params``.

Schema (see ``app.models.model_params.PredictionOutcome``):
    - predicted_*  lifted from ``run.result['success_probability']``
    - factor_snapshot  truncated to first 20 factor_contributions
    - actual_binary  1 if outcome == 'achieved' else 0 (Brier input)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.goal import Goal, Pathway
from app.models.model_params import PredictionOutcome
from app.models.scenario import Scenario, ScenarioRun

log = get_logger(__name__)

_GLOBAL = "__global__"

# Reliability-curve bins for the calibration view. The last bin is
# closed on the right so a p50 of exactly 1.0 is counted.
_BINS: list[tuple[float, float]] = [
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.0),
]

_FACTOR_SNAPSHOT_LIMIT = 20


class PredictionOutcomeService:
    """Records prediction-vs-actual rows and computes Brier calibration stats."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------- Public writes ----------------

    def record_outcome(
        self,
        goal_id: str,
        outcome: str,
        actual_date: date | None = None,
        notes: str | None = None,
    ) -> PredictionOutcome:
        """Snapshot the latest completed run for the goal + persist the outcome.

        Called from the Goal lifecycle hook when a goal transitions to a
        terminal state. If no prior ScenarioRun exists, a row is still
        written with ``predicted_*`` left NULL and a "no prior prediction"
        note so the realized outcome is not lost for future calibration.
        """
        goal = self.db.get(Goal, goal_id)
        goal_type = (getattr(goal, "scenario", None) or _GLOBAL) if goal else _GLOBAL
        run = self._latest_completed_run(goal_id)
        region = self._resolve_region(goal_id, run.scenario_id if run else None)
        row = self.db.scalar(
            select(PredictionOutcome).where(PredictionOutcome.goal_id == goal_id)
        ) or PredictionOutcome(goal_id=goal_id, actual_outcome=outcome)

        result = run.result if run and run.result else {}
        probability = result.get("success_probability", {})
        row.scenario_id = run.scenario_id if run else None
        row.run_id = run.id if run else None
        row.goal_type = goal_type
        row.region = region
        row.predicted_p50 = probability.get("p50")
        row.predicted_p10 = probability.get("p10")
        row.predicted_p90 = probability.get("p90")
        row.predicted_at = (
            run.completed_at.isoformat() if run and run.completed_at else None
        )
        row.model_version = result.get("model_version")
        row.factor_snapshot = self._truncate_factors(
            result.get("factor_contributions", [])
        )
        row.actual_outcome = outcome
        row.actual_date = actual_date
        row.actual_binary = 1 if outcome == "achieved" else 0
        row.notes = notes or ("no prior prediction" if run is None else None)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        log.info(
            "prediction_outcome.recorded",
            goal_id=goal_id,
            run_id=run.id if run else None,
            outcome=outcome,
            predicted_p50=row.predicted_p50,
        )
        return row

    # ---------------- Public reads ----------------

    def list_outcomes(
        self,
        goal_type: str | None = None,
        region: str | None = None,
        limit: int = 100,
    ) -> list[PredictionOutcome]:
        """Filtered list for the admin / calibration UI."""
        stmt = (
            select(PredictionOutcome)
            .order_by(PredictionOutcome.created_at.desc())
            .limit(limit)
        )
        if goal_type is not None:
            stmt = stmt.where(PredictionOutcome.goal_type == goal_type)
        if region is not None:
            stmt = stmt.where(PredictionOutcome.region == region)
        return list(self.db.scalars(stmt))

    def compute_brier_score(
        self,
        goal_type: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Brier score + reliability curve over the matching outcome rows.

        Brier = mean((predicted_p50 - actual_binary) ** 2). Rows with a
        NULL ``predicted_p50`` are skipped (no prior prediction).
        """
        rows = self.list_outcomes(goal_type=goal_type, region=region, limit=10000)

        scored = [
            r for r in rows if r.predicted_p50 is not None
        ]
        sample_size = len(scored)
        if sample_size == 0:
            return {
                "sample_size": 0,
                "brier_score": 0.0,
                "mean_predicted": 0.0,
                "mean_actual": 0.0,
                "reliability_curve": [
                    {"bin": i, "predicted_avg": 0.0, "actual_avg": 0.0, "count": 0}
                    for i in range(len(_BINS))
                ],
            }

        sq_errors = [
            (float(r.predicted_p50) - float(r.actual_binary)) ** 2 for r in scored
        ]
        brier = sum(sq_errors) / sample_size
        mean_predicted = sum(float(r.predicted_p50) for r in scored) / sample_size
        mean_actual = sum(float(r.actual_binary) for r in scored) / sample_size

        reliability_curve = self._reliability_curve(scored)

        return {
            "sample_size": sample_size,
            "brier_score": round(brier, 6),
            "mean_predicted": round(mean_predicted, 6),
            "mean_actual": round(mean_actual, 6),
            "reliability_curve": reliability_curve,
        }

    # ---------------- Internal ----------------

    def _latest_completed_run(self, goal_id: str) -> ScenarioRun | None:
        """Most recent completed ScenarioRun for the goal across all scenarios."""
        return self.db.scalar(
            select(ScenarioRun)
            .join(Scenario, ScenarioRun.scenario_id == Scenario.id)
            .where(Scenario.goal_id == goal_id, ScenarioRun.status == "completed")
            .order_by(
                ScenarioRun.completed_at.desc().nulls_last(),
                ScenarioRun.created_at.desc(),
            )
            .limit(1)
        )

    def _resolve_region(self, goal_id: str, scenario_id: str | None) -> str:
        """Resolve the canonical pathway region for the prediction run."""
        scenario = self.db.get(Scenario, scenario_id) if scenario_id else None
        if scenario and scenario.pathway_id:
            pathway = self.db.get(Pathway, scenario.pathway_id)
            if pathway and pathway.goal_id == goal_id:
                return pathway.region or _GLOBAL
        pathway = self.db.scalar(
            select(Pathway)
            .where(Pathway.goal_id == goal_id, Pathway.scenario_id == scenario_id)
            .order_by(Pathway.created_at.asc())
        )
        return getattr(pathway, "region", None) or _GLOBAL

    @staticmethod
    def _truncate_factors(factors: Any) -> list[dict[str, Any]]:
        """Keep factor_snapshot bounded — first 20 entries only."""
        if not isinstance(factors, list):
            return []
        return list(factors[:_FACTOR_SNAPSHOT_LIMIT])

    @staticmethod
    def _reliability_curve(
        rows: list[PredictionOutcome],
    ) -> list[dict[str, Any]]:
        """5-bin reliability curve: predicted_avg vs actual_avg per bin."""
        curve: list[dict[str, Any]] = []
        for i, (lo, hi) in enumerate(_BINS):
            in_bin = [
                r for r in rows
                if lo <= float(r.predicted_p50) < hi or (i == len(_BINS) - 1 and float(r.predicted_p50) == hi)
            ]
            count = len(in_bin)
            if count:
                predicted_avg = sum(float(r.predicted_p50) for r in in_bin) / count
                actual_avg = sum(float(r.actual_binary) for r in in_bin) / count
            else:
                predicted_avg = 0.0
                actual_avg = 0.0
            curve.append(
                {
                    "bin": i,
                    "predicted_avg": round(predicted_avg, 6),
                    "actual_avg": round(actual_avg, 6),
                    "count": count,
                }
            )
        return curve
