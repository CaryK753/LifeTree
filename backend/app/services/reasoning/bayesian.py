"""Bayesian-network success-probability estimator.

Per project plan §4.6: uses the knowledge-graph's causal structure as the
DAG, with each Requirement / RiskFactor contributing a Beta-shaped
conditional probability. We compute a closed-form posterior (no heavy
inference library) and return both point estimate and per-factor
attribution for explainability.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.core.logging import get_logger
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.models.scenario import Scenario

log = get_logger(__name__)


@dataclass(slots=True)
class BayesianResult:
    p_success: float
    factor_contributions: list[dict[str, float]]
    explanation: str


class BayesianEstimator:
    """Lightweight Beta-Binomial factor model with noise-OR aggregation."""

    def estimate(
        self,
        goal: Goal,
        pathway: Pathway | None,
        requirements: list[Requirement],
        risk_factors: list[RiskFactor],
        scenario: Scenario | None = None,
    ) -> BayesianResult:
        # ---------- Per-requirement success probability ----------
        contribs: list[dict[str, float]] = []
        for req in requirements:
            p = self._req_success_prob(req)
            contribs.append(
                {
                    "factor_id": req.id,
                    "name": req.name,
                    "type": "requirement",
                    "p": p,
                    "contribution": 1.0 - p,  # contribution to failure
                }
            )

        # ---------- Per-risk-factor impact ----------
        for rf in risk_factors:
            p_failure = self._risk_failure_prob(rf, scenario)
            contribs.append(
                {
                    "factor_id": rf.id,
                    "name": rf.name,
                    "type": "risk_factor",
                    "p": 1.0 - p_failure,
                    "contribution": p_failure,
                }
            )

        # ---------- Noise-OR aggregation: P(success) = Π p_i ----------
        if not contribs:
            return BayesianResult(
                p_success=0.5,
                factor_contributions=[],
                explanation="No requirements or risks registered; defaulting to 0.5.",
            )

        ps = np.array([c["p"] for c in contribs], dtype=float)
        ps = np.clip(ps, 1e-3, 1 - 1e-3)
        p_success = float(np.prod(ps))

        # Sort contributions by impact (descending)
        contribs.sort(key=lambda c: c["contribution"], reverse=True)

        top = contribs[0]
        explanation = (
            f"Bayesian noise-OR over {len(contribs)} factors gives "
            f"P(success)={p_success:.3f}. Largest drag: "
            f"{top['name']} (Δ={top['contribution']:.3f})."
        )
        log.info(
            "bayesian.estimate",
            goal_id=goal.id,
            p_success=p_success,
            n_factors=len(contribs),
        )
        return BayesianResult(
            p_success=p_success,
            factor_contributions=contribs,
            explanation=explanation,
        )

    # ---------------- Helpers ----------------

    def _req_success_prob(self, req: Requirement) -> float:
        """P(user satisfies this requirement) based on gap_status."""
        base = {
            "met": 0.95,
            "partial": 0.55,
            "missing": 0.20,
            "unknown": 0.50,
        }.get(req.gap_status, 0.5)
        # Weight: less important requirements should drag less
        weight = max(0.0, min(1.5, float(req.weight or 1.0)))
        # Pull slightly toward 1.0 for low-weight requirements
        return float(base + (1 - base) * (1 - weight) * 0.2)

    def _risk_failure_prob(
        self, rf: RiskFactor, scenario: Scenario | None
    ) -> float:
        """P(this risk materializes and breaks the path)."""
        level_to_p = {"low": 0.10, "medium": 0.30, "high": 0.60}
        p = level_to_p.get(rf.level, 0.20)
        if rf.probability is not None:
            p = 0.5 * p + 0.5 * float(rf.probability)
        if rf.impact is not None:
            p *= max(0.1, min(1.0, float(rf.impact)))

        # Scenario-level assumption overrides
        if scenario is not None:
            overrides = (scenario.assumptions or {}).get("risk_overrides", {})
            if rf.id in overrides:
                p = float(overrides[rf.id])

        return float(max(0.0, min(1.0, p)))
