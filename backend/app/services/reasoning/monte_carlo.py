"""Monte Carlo simulation over the action/probability space.

Per project plan §4.6: runs N trials sampling from each factor's
distribution, returns percentile bands + key risk time-points + an
optimal-action sequence suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.models.scenario import Scenario
from app.services.reasoning.bayesian import BayesianEstimator
from app.services.reasoning.factor_model import MODEL_VERSION, aggregate_success

log = get_logger(__name__)


@dataclass(slots=True)
class MonteCarloResult:
    p_success: float
    p10: float
    p50: float
    p90: float
    iterations: int
    key_risk_times: list[dict[str, float]]
    optimal_action_sequence: list[dict[str, str]]
    sample_mean: float
    sample_std: float
    model_version: str = MODEL_VERSION


class MonteCarloSimulator:
    """Beta-distributed sampling over requirements and risk hazards."""

    def __init__(self, bayesian: BayesianEstimator | None = None) -> None:
        self.bayesian = bayesian or BayesianEstimator()

    def simulate(
        self,
        goal: Goal,
        pathway: Pathway | None,
        requirements: list[Requirement],
        risk_factors: list[RiskFactor],
        scenario: Scenario | None = None,
        iterations: int = 2000,
        seed: int | None = 42,
        evidence_scores: dict[str, float] | None = None,
        params: dict[str, Any] | None = None,
    ) -> MonteCarloResult:
        rng = np.random.default_rng(seed)
        evidence_scores = evidence_scores or {}
        if not requirements and not risk_factors:
            return MonteCarloResult(
                p_success=0.5,
                p10=0.1,
                p50=0.5,
                p90=0.9,
                iterations=iterations,
                key_risk_times=[],
                optimal_action_sequence=[],
                sample_mean=0.5,
                sample_std=0.0,
            )

        requirement_samples = np.empty((iterations, 0))
        requirement_weights = [float(req.weight or 1.0) for req in requirements]
        if requirements:
            requirement_samples = np.column_stack(
                [
                    rng.beta(
                        *self._p_to_beta(
                            self.bayesian._req_success_prob(req, params),
                            concentration=4.0 + 12.0 * evidence_scores.get(req.id, 0.0),
                        ),
                        size=iterations,
                    )
                    for req in requirements
                ]
            )

        risk_survival_samples = np.empty((iterations, 0))
        if risk_factors:
            risk_survival_samples = np.column_stack(
                [
                    rng.beta(
                        *self._p_to_beta(
                            1.0 - self.bayesian._risk_failure_prob(risk, scenario, params),
                            concentration=3.0 + 9.0 * evidence_scores.get(risk.id, 0.0),
                        ),
                        size=iterations,
                    )
                    for risk in risk_factors
                ]
            )

        success_per_trial = np.asarray(
            aggregate_success(
                requirement_samples,
                requirement_weights,
                risk_survival_samples,
                params,
                axis=1,
            )
        )
        p_success = float(np.mean(success_per_trial))
        p10, p50, p90 = (
            float(np.percentile(success_per_trial, 10)),
            float(np.percentile(success_per_trial, 50)),
            float(np.percentile(success_per_trial, 90)),
        )

        months = np.arange(1, 25)
        decay = np.exp(-0.02 * months)
        per_month = success_per_trial[:, None] * decay[None, :]
        risk_times = []
        for month_index, month in enumerate(months):
            values = per_month[:, month_index]
            if np.mean(values < p50) > 0.5:
                risk_times.append(
                    {"month": int(month), "p50": float(np.median(values))}
                )
            if len(risk_times) >= 5:
                break

        optimal_sequence = self._suggest_action_sequence(
            requirements, risk_factors
        )
        log.info(
            "monte_carlo.simulate",
            goal_id=goal.id,
            iterations=iterations,
            p_success=p_success,
            p50=p50,
            model_version=MODEL_VERSION,
        )
        return MonteCarloResult(
            p_success=p_success,
            p10=p10,
            p50=p50,
            p90=p90,
            iterations=iterations,
            key_risk_times=risk_times,
            optimal_action_sequence=optimal_sequence,
            sample_mean=p_success,
            sample_std=float(np.std(success_per_trial)),
        )

    # ---------------- Helpers ----------------

    @staticmethod
    def _p_to_beta(p: float, concentration: float = 8.0) -> tuple[float, float]:
        """Convert a probability into Beta(α, β) parameters with given concentration."""
        p = max(1e-3, min(1 - 1e-3, p))
        alpha = concentration * p
        beta = concentration * (1 - p)
        return (float(alpha), float(beta))

    def _suggest_action_sequence(
        self,
        requirements: list[Requirement],
        risk_factors: list[RiskFactor],
    ) -> list[dict[str, str]]:
        """Heuristic: address the highest-impact missing requirement first."""
        actions: list[dict[str, str]] = []
        sorted_reqs = sorted(
            requirements,
            key=lambda r: (
                0 if r.gap_status == "missing" else 1 if r.gap_status == "partial" else 2,
                -float(r.weight or 1.0),
            ),
        )
        for req in sorted_reqs[:5]:
            if req.gap_status == "met":
                continue
            actions.append(
                {
                    "requirement_id": req.id,
                    "name": req.name,
                    "action": f"Close gap on {req.name}: {req.gap_status} → met",
                }
            )
        for rf in risk_factors[:2]:
            if rf.level == "high":
                actions.append(
                    {
                        "risk_factor_id": rf.id,
                        "name": rf.name,
                        "action": f"Mitigate {rf.name} ({rf.type})",
                    }
                )
        return actions
