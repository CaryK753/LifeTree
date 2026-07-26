"""ReasoningEngine: orchestrates Bayesian + Monte Carlo + survival + propagation.

The facade persists a ScenarioRun record per execution and returns the
composite result dict cached on the Scenario.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.goal import Pathway, Requirement, RiskFactor
from app.models.scenario import Scenario, ScenarioRun
from app.services.reasoning.bayesian import BayesianEstimator
from app.services.reasoning.monte_carlo import MonteCarloSimulator
from app.services.reasoning.risk_propagation import RiskPropagationEngine
from app.services.reasoning.survival import SurvivalEstimator

log = get_logger(__name__)


class ReasoningEngine:
    """Top-level facade invoked by API / Celery workers."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.bayesian = BayesianEstimator()
        self.monte_carlo = MonteCarloSimulator(self.bayesian)
        self.survival = SurvivalEstimator()
        self.risk_propagation = RiskPropagationEngine(db)

    # ---------------- Public API ----------------

    def run_full(self, scenario: Scenario) -> ScenarioRun:
        """Run the full pipeline for a scenario and persist a ScenarioRun."""
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        run = ScenarioRun(
            id=run_id,
            scenario_id=scenario.id,
            engine="full",
            status="running",
            started_at=started_at,
        )
        self.db.add(run)
        self.db.commit()

        try:
            pathway, requirements, risk_factors = self._load_context(scenario)
            goal = pathway.goal if pathway else None
            if goal is None:
                raise RuntimeError("scenario has no associated goal/pathway")

            # 1. Bayesian point estimate
            bayes = self.bayesian.estimate(
                goal, pathway, requirements, risk_factors, scenario
            )

            # 2. Monte Carlo distribution
            mc = self.monte_carlo.simulate(
                goal, pathway, requirements, risk_factors, scenario
            )

            # 3. Survival curve
            surv = self.survival.estimate(goal, mc.p50)

            # 4. Aggregate key risk factors
            key_risks = self._aggregate_key_risks(
                bayes.factor_contributions, risk_factors
            )

            result = {
                "success_probability": {
                    "p10": mc.p10,
                    "p50": mc.p50,
                    "p90": mc.p90,
                    "bayesian_point": bayes.p_success,
                    "p_by_target_date": surv.p_by_target_date,
                },
                "overall_risk": 1.0 - mc.p50,
                "key_risk_factors": key_risks,
                "factor_contributions": bayes.factor_contributions,
                "survival_curve": surv.curve,
                "median_time_months": surv.median_time_months,
                "key_risk_times": mc.key_risk_times,
                "optimal_action_sequence": mc.optimal_action_sequence,
                "explanation": bayes.explanation,
                "iterations": mc.iterations,
            }

            run.status = "completed"
            run.result = result
            run.iterations = mc.iterations
            run.completed_at = datetime.now(timezone.utc)
            run.duration_ms = int((time.perf_counter() - t0) * 1000)
            self.db.add(run)
            self.db.commit()

            log.info(
                "reasoning.run_completed",
                scenario_id=scenario.id,
                run_id=run.id,
                p50=mc.p50,
                ms=run.duration_ms,
            )
            return run

        except Exception as exc:  # noqa: BLE001
            log.error("reasoning.run_failed", scenario_id=scenario.id, error=str(exc))
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            run.duration_ms = int((time.perf_counter() - t0) * 1000)
            self.db.add(run)
            self.db.commit()
            return run

    # ---------------- Helpers ----------------

    def _load_context(
        self, scenario: Scenario
    ) -> tuple[Pathway | None, list[Requirement], list[RiskFactor]]:
        # Find the primary pathway linked to this scenario
        pathway = self.db.scalar(
            select(Pathway).where(Pathway.scenario_id == scenario.id)
        )
        if pathway is None:
            # Fall back to the goal's first pathway
            pathway = self.db.scalar(
                select(Pathway)
                .where(Pathway.goal_id == scenario.goal_id)
                .order_by(Pathway.created_at.asc())
            )

        requirements: list[Requirement] = []
        if pathway is not None:
            requirements = list(
                self.db.scalars(
                    select(Requirement)
                    .where(Requirement.pathway_id == pathway.id)
                    .order_by(Requirement.weight.desc())
                )
            )

        risk_factors = list(
            self.db.scalars(select(RiskFactor).order_by(RiskFactor.level.desc()))
        )

        return pathway, requirements, risk_factors

    @staticmethod
    def _aggregate_key_risks(
        contributions: list[dict], risk_factors: list[RiskFactor]
    ) -> list[dict]:
        risk_by_id = {rf.id: rf for rf in risk_factors}
        out: list[dict] = []
        for c in contributions:
            rf = risk_by_id.get(c.get("factor_id"))
            if rf is None or c.get("type") != "risk_factor":
                continue
            out.append(
                {
                    "factor_id": rf.id,
                    "name": rf.name,
                    "type": rf.type,
                    "level": rf.level,
                    "contribution": c.get("contribution", 0.0),
                }
            )
        return out[:5]
