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
    """Explainable requirement-readiness and risk-survival estimator.

    Per project plan §11.2 缺口 G: all aggregation constants are sourced
    from a ``params`` snapshot (built by
    ``app.services.model_params.build_param_snapshot``) rather than
    hardcoded. When ``params`` is None the pre-externalization heuristics
    are used as defaults so existing callers keep working.
    """

    def estimate(
        self,
        goal: Goal,
        pathway: Pathway | None,
        requirements: list[Requirement],
        risk_factors: list[RiskFactor],
        scenario: Scenario | None = None,
        evidence_scores: dict[str, float] | None = None,
        params: dict[str, Any] | None = None,
    ) -> BayesianResult:
        evidence_scores = evidence_scores or {}
        contribs: list[dict[str, Any]] = []
        requirement_probs: list[float] = []
        requirement_weights: list[float] = []
        risk_survivals: list[float] = []

        for req in requirements:
            probability = self._req_success_prob(req, params)
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
            failure_probability = self._risk_failure_prob(risk, scenario, params)
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
                params,
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

    def _req_success_prob(
        self, req: Requirement, params: dict[str, Any] | None = None
    ) -> float:
        """P(user satisfies this requirement) based on gap_status.

        Base probabilities are sourced from ``params`` (keys
        ``requirement_base_prob.{met,partial,missing,unknown}``) so admins
        can tune per goal_type/region and so real outcomes can calibrate
        them. Defaults mirror the pre-externalization heuristics.
        """
        p = params or {}
        base = {
            "met": p.get("requirement_base_prob.met", 0.92),
            "partial": p.get("requirement_base_prob.partial", 0.60),
            "missing": p.get("requirement_base_prob.missing", 0.40),
            "unknown": p.get("requirement_base_prob.unknown", 0.50),
        }.get(req.gap_status, p.get("requirement_base_prob.unknown", 0.5))
        base = float(base)
        # Weight: high-weight requirements matter more, so a missing
        # high-weight one should pull success prob down more. We blend
        # the base prob toward its "failure complement" proportional to
        # weight: weight=0 → no change (unimportant), weight=1 → full
        # effect, weight>1 → capped at 1.0 (no inversion).
        weight = max(0.0, min(1.0, float(req.weight or 1.0)))
        # Pull base toward 1.0 for low-weight requirements (they drag
        # less), and toward base itself for high-weight ones.
        blend = float(p.get("requirement_weight_blend", 0.2))
        return float(base + (1.0 - base) * (1.0 - weight) * blend)

    def _risk_failure_prob(
        self,
        rf: RiskFactor,
        scenario: Scenario | None,
        params: dict[str, Any] | None = None,
    ) -> float:
        """P(this risk materializes and breaks the path).

        Level→probability mapping is sourced from ``params`` (keys
        ``risk_level_p.{low,medium,high}``); the level/explicit-probability
        blend uses ``risk_level_blend`` (default 0.5).
        """
        p = params or {}
        level_to_p = {
            "low": p.get("risk_level_p.low", 0.08),
            "medium": p.get("risk_level_p.medium", 0.20),
            "high": p.get("risk_level_p.high", 0.40),
        }
        prob = float(level_to_p.get(rf.level, p.get("risk_level_p.medium", 0.20)))
        if rf.probability is not None:
            blend = float(p.get("risk_level_blend", 0.5))
            prob = blend * prob + (1.0 - blend) * float(rf.probability)
        if rf.impact is not None:
            prob *= max(0.1, min(1.0, float(rf.impact)))

        # Scenario-level assumption overrides
        if scenario is not None:
            overrides = (scenario.assumptions or {}).get("risk_overrides", {})
            if rf.id in overrides:
                prob = float(overrides[rf.id])

        return float(max(0.0, min(1.0, prob)))
