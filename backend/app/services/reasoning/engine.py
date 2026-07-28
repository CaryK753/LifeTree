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
from app.models.event import Event, InformationSource, Relationship
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

            # §5.3 信源溯源下钻 — attach the most credible source for each
            # factor so the UI can offer one-click drill-down to the original
            # document / news page behind any deduction.
            enriched_contribs = self._enrich_with_sources(
                bayes.factor_contributions, risk_factors, requirements
            )

            # Compute Risk Controllability Grade to avoid raw win-rate anxiety
            p50 = mc.p50
            if p50 >= 0.75:
                grade, label = "robust", "稳健"
            elif p50 >= 0.45:
                grade, label = "moderate_risk", "中度风险"
            else:
                grade, label = "vulnerable", "高风险脆弱"

            result = {
                "success_probability": {
                    "p10": mc.p10,
                    "p50": mc.p50,
                    "p90": mc.p90,
                    "bayesian_point": bayes.p_success,
                    "p_by_target_date": surv.p_by_target_date,
                },
                "overall_risk": 1.0 - mc.p50,
                "controllability_grade": grade,
                "controllability_label": label,
                "key_risk_factors": key_risks,
                "factor_contributions": enriched_contribs,
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

    # ---------------- Source attribution (§5.3 信源溯源下钻) ----------------

    # Credibility rank: higher = more trustworthy. Used to pick the best
    # source when a factor has multiple supporting documents.
    _CRED_RANK = {
        "high": 5,
        "user_marked_reliable": 4,
        "official": 4,
        "medium": 3,
        "news": 3,
        "pending": 2,
        "low": 1,
        "user_marked_questionable": 0,
    }

    def _enrich_with_sources(
        self,
        contributions: list[dict],
        risk_factors: list[RiskFactor],
        requirements: list[Requirement],
    ) -> list[dict]:
        """Attach source_title / source_url / source_kind to each factor.

        Resolution path (per project plan §5.3): for every factor, look up
        the ``Relationship`` rows that reference it (either as subject or
        object) and follow their ``source_id`` to ``InformationSource``.
        Falls back to ``Event`` rows whose ``subject`` matches the factor
        name — useful when the structuring pipeline didn't emit a
        Relationship but did emit Events.

        The single most-credible source wins (so the drill-down UI shows one
        authoritative document instead of a confusing list).
        """
        out: list[dict] = []
        for c in contributions:
            enriched = dict(c)
            try:
                src = self._best_source_for_factor(c, risk_factors, requirements)
                if src is not None:
                    enriched["source_title"] = src.title
                    enriched["source_url"] = src.url
                    enriched["source_kind"] = src.kind
                    enriched["source_credibility"] = src.credibility
            except Exception:  # noqa: BLE001
                # Source enrichment must never break the reasoning run.
                log.warning("source_enrichment_failed", factor=c.get("name"))
            out.append(enriched)
        return out

    def _best_source_for_factor(
        self,
        contribution: dict,
        risk_factors: list[RiskFactor],
        requirements: list[Requirement],
    ) -> InformationSource | None:
        factor_id = contribution.get("factor_id")
        factor_type = contribution.get("type")
        factor_name = contribution.get("name") or ""

        source_ids: set[str] = set()

        # 1) Relationships referencing this factor by id (polymorphic).
        if factor_id:
            rels = list(
                self.db.scalars(
                    select(Relationship).where(
                        ((Relationship.subject_type == factor_type)
                         & (Relationship.subject_id == factor_id))
                        | ((Relationship.object_type == factor_type)
                           & (Relationship.object_id == factor_id))
                    )
                )
            )
            for r in rels:
                if r.source_id:
                    source_ids.add(r.source_id)

        # 2) Events whose subject matches the factor name (fallback when no
        #    explicit Relationship exists — the structuring pipeline often
        #    emits Events keyed by name rather than id).
        if not source_ids and factor_name:
            evs = list(
                self.db.scalars(
                    select(Event)
                    .where(Event.subject.ilike(f"%{factor_name}%"))
                    .limit(20)
                )
            )
            for e in evs:
                if e.source_id:
                    source_ids.add(e.source_id)

        if not source_ids:
            return None

        # Pick the most credible source (ties broken by recency).
        candidates = list(
            self.db.scalars(
                select(InformationSource).where(
                    InformationSource.id.in_(source_ids)
                )
            )
        )
        if not candidates:
            return None
        candidates.sort(
            key=lambda s: (
                self._CRED_RANK.get(s.credibility, 0),
                s.updated_at or s.created_at,
            ),
            reverse=True,
        )
        return candidates[0]
