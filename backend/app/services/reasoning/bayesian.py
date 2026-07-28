"""Bayesian-network success-probability estimator.

Per project plan §4.6: uses the knowledge-graph's causal structure as the
DAG, with each Requirement / RiskFactor contributing a Beta-shaped
conditional probability. We compute a closed-form posterior (no heavy
inference library) and return both point estimate and per-factor
attribution for explainability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.models.scenario import Scenario
from app.services.reasoning.factor_model import MODEL_VERSION, aggregate_success

log = get_logger(__name__)


@dataclass(slots=True)
class BayesianResult:
    p_success: float
    factor_contributions: list[dict[str, Any]]
    explanation: str
    evidence_quality: float
    model_version: str = MODEL_VERSION


class BayesianEstimator:
    """Explainable requirement-readiness and risk-survival estimator."""

    def estimate(
        self,
        goal: Goal,
        pathway: Pathway | None,
        requirements: list[Requirement],
        risk_factors: list[RiskFactor],
        scenario: Scenario | None = None,
        evidence_scores: dict[str, float] | None = None,
    ) -> BayesianResult:
        evidence_scores = evidence_scores or {}
        contribs: list[dict[str, Any]] = []
        requirement_probs: list[float] = []
        requirement_weights: list[float] = []
        risk_survivals: list[float] = []

        for req in requirements:
            probability = self._req_success_prob(req)
            weight = max(0.05, min(2.0, float(req.weight or 1.0)))
            requirement_probs.append(probability)
            requirement_weights.append(weight)
            contribs.append(
                {
                    "factor_id": req.id,
                    "name": req.name,
                    "type": "requirement",
                    "p": probability,
                    "contribution": (1.0 - probability) * weight,
                    "evidence_quality": evidence_scores.get(req.id, 0.0),
                }
            )

        for risk in risk_factors:
            failure_probability = self._risk_failure_prob(risk, scenario)
            risk_survivals.append(1.0 - failure_probability)
            contribs.append(
                {
                    "factor_id": risk.id,
                    "name": risk.name,
                    "type": "risk_factor",
                    "p": 1.0 - failure_probability,
                    "contribution": failure_probability,
                    "evidence_quality": evidence_scores.get(risk.id, 0.0),
                }
            )

        if not contribs:
            return BayesianResult(
                p_success=0.5,
                factor_contributions=[],
                explanation="No structured factors are available; using an uninformative 0.5 prior.",
                evidence_quality=0.0,
            )

        p_success = float(
            aggregate_success(
                np.asarray(requirement_probs, dtype=float),
                requirement_weights,
                np.asarray(risk_survivals, dtype=float),
            )
        )
        contribs.sort(key=lambda item: item["contribution"], reverse=True)
        evidence_quality = float(
            np.mean([item["evidence_quality"] for item in contribs])
        )
        top = contribs[0]
        explanation = (
            f"{MODEL_VERSION} combines {len(requirements)} jointly-needed "
            f"requirements with {len(risk_factors)} risk hazards. "
            f"P(success)={p_success:.3f}; largest modeled drag: "
            f"{top['name']} ({top['contribution']:.3f})."
        )
        log.info(
            "bayesian.estimate",
            goal_id=goal.id,
            p_success=p_success,
            n_factors=len(contribs),
            model_version=MODEL_VERSION,
        )
        return BayesianResult(
            p_success=p_success,
            factor_contributions=contribs,
            explanation=explanation,
            evidence_quality=evidence_quality,
        )

    # ---------------- Helpers ----------------

    def _req_success_prob(self, req: Requirement) -> float:
        """P(user satisfies this requirement) based on gap_status.

        "missing" means the user hasn't demonstrated it yet — uncertain,
        not unlikely. The base reflects "could go either way if the user
        works toward it", not a 20% coin flip.
        """
        base = {
            "met": 0.92,
            "partial": 0.60,
            "missing": 0.40,
            "unknown": 0.50,
        }.get(req.gap_status, 0.5)
        # Weight: high-weight requirements matter more, so a missing
        # high-weight one should pull success prob down more. We blend
        # the base prob toward its "failure complement" proportional to
        # weight: weight=0 → no change (unimportant), weight=1 → full
        # effect, weight>1 → capped at 1.0 (no inversion).
        weight = max(0.0, min(1.0, float(req.weight or 1.0)))
        # Pull base toward 1.0 for low-weight requirements (they drag
        # less), and toward base itself for high-weight ones.
        return float(base + (1.0 - base) * (1.0 - weight) * 0.2)

    def _risk_failure_prob(
        self, rf: RiskFactor, scenario: Scenario | None
    ) -> float:
        """P(this risk materializes and breaks the path)."""
        level_to_p = {"low": 0.08, "medium": 0.20, "high": 0.40}
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
