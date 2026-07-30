"""ReasoningEngine: orchestrates Bayesian + Monte Carlo + survival + propagation.

The facade persists a ScenarioRun record per execution and returns the
composite result dict cached on the Scenario.

Per project plan §11.2 缺口 G: the engine builds a parameter snapshot
via ``ModelParamStore.build_param_snapshot`` at the start of each run and
threads it through the Bayesian / Monte Carlo / survival estimators so
no aggregation constant is hardcoded. The result dict carries
``calibration_status`` so the frontend can render the '未校准' badge
while parameters remain heuristic.
Per §11.2 缺口 C: the engine also persists structured ``Action`` rows
derived from ``optimal_action_sequence`` so the /actions page and the
LangGraph agent can track / complete them.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.event import Event, InformationSource, Relationship
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.models.scenario import Scenario, ScenarioRun
from app.services.model_params import build_param_snapshot
from app.services.reasoning.action_persistence import persist_recommended_actions
from app.services.reasoning.bayesian import BayesianEstimator
from app.services.reasoning.evidence import build_decision_evidence
from app.services.reasoning.factor_model import MODEL_VERSION, aggregate_risk_exposure
from app.services.reasoning.monte_carlo import MonteCarloSimulator
from app.services.reasoning.risk_propagation import RiskPropagationEngine
from app.services.reasoning.survival import SurvivalEstimator
from app.services.risk_scope import risk_scope_clause
from app.services.scenario_pathway import resolve_scenario_pathway

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

            # §11.2 缺口 G: build the param snapshot once per run and
            # thread it through every estimator. Scope by goal.scenario
            # tag (goal_type) and pathway.region so per-domain tuning +
            # calibration take effect.
            goal_type = getattr(goal, "scenario", None) or "__global__"
            region = getattr(pathway, "region", None) or "__global__"
            params = build_param_snapshot(
                self.db, goal_type=goal_type, region=region
            )

            evidence = build_decision_evidence(
                self.db,
                {factor.id for factor in [*requirements, *risk_factors]},
            )

            # 1. Bayesian point estimate
            bayes = self.bayesian.estimate(
                goal,
                pathway,
                requirements,
                risk_factors,
                scenario,
                evidence_scores=evidence.scores,
                params=params,
            )

            # 2. Monte Carlo distribution
            mc = self.monte_carlo.simulate(
                goal,
                pathway,
                requirements,
                risk_factors,
                scenario,
                evidence_scores=evidence.scores,
                params=params,
            )

            probability_bias = float(params.get("calibration_probability_bias", 0.0))
            adjusted = {
                "p10": max(0.0, min(1.0, mc.p10 + probability_bias)),
                "p50": max(0.0, min(1.0, mc.p50 + probability_bias)),
                "p90": max(0.0, min(1.0, mc.p90 + probability_bias)),
                "bayesian": max(0.0, min(1.0, bayes.p_success + probability_bias)),
            }

            # 3. Survival curve
            surv = self.survival.estimate(goal, adjusted["p50"], params=params)

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
            for contribution in enriched_contribs:
                paths = evidence.paths_by_factor.get(
                    contribution.get("factor_id", ""), []
                )
                contribution["graph_paths"] = paths
                contribution["evidence_count"] = len(paths)
                contribution["why_it_matters"] = (
                    "This factor is connected to source-backed ontology edges."
                    if paths
                    else "No source-backed ontology edge is recorded yet."
                )

            # Compute Risk Controllability Grade to avoid raw win-rate anxiety
            p50 = adjusted["p50"]
            if p50 >= 0.75:
                grade, label = "robust", "稳健"
            elif p50 >= 0.45:
                grade, label = "moderate_risk", "中度风险"
            else:
                grade, label = "vulnerable", "高风险脆弱"

            # §11.2 缺口 C: persist structured Action rows from the
            # optimal_action_sequence so the /actions page + agent can
            # track them. We keep the text list in the result for
            # backward compat / display, but the Action rows are the
            # source of truth going forward.
            action_rows = persist_recommended_actions(
                self.db,
                goal=goal,
                pathway=pathway,
                scenario=scenario,
                run_id=run_id,
                recommendations=mc.optimal_action_sequence,
                requirements=requirements,
            )

            risk_exposure = aggregate_risk_exposure(
                [
                    float(contribution["p"])
                    for contribution in bayes.factor_contributions
                    if contribution.get("type") == "risk_factor"
                ],
                params,
            )

            # Calibration metadata (缺口 G) — surfaces in the UI badge.
            calibrated = bool(params.get("__calibrated__", False))
            sample_size = int(params.get("__calibration_sample_size__", 0))

            result = {
                "success_probability": {
                    "p10": adjusted["p10"],
                    "p50": adjusted["p50"],
                    "p90": adjusted["p90"],
                    "bayesian_point": adjusted["bayesian"],
                    "p_by_target_date": surv.p_by_target_date,
                },
                "overall_risk": risk_exposure,
                "controllability_grade": grade,
                "controllability_label": label,
                "key_risk_factors": key_risks,
                "factor_contributions": enriched_contribs,
                "survival_curve": surv.curve,
                "median_time_months": surv.median_time_months,
                "key_risk_times": mc.key_risk_times,
                "optimal_action_sequence": mc.optimal_action_sequence,
                "action_ids": [a.id for a in action_rows],
                "explanation": bayes.explanation,
                "iterations": mc.iterations,
                "model_version": MODEL_VERSION,
                "calibration_status": {
                    "calibrated": calibrated,
                    "sample_size": sample_size,
                    "goal_type": goal_type,
                    "region": region,
                    # Honest framing until real outcomes are collected.
                    "label": "已校准" if calibrated else "未校准（启发式估计）",
                },
                "assumptions": [
                    "Requirements are jointly needed and use weighted geometric readiness.",
                    "Risk hazards are partially correlated rather than fully independent.",
                    "Evidence quality controls uncertainty, not the direction of an estimate.",
                    "Outputs compare scenarios and are not calibrated guarantees.",
                    "Aggregation parameters are sourced from model_params; "
                    "they are heuristic until calibrated from real outcomes.",
                ],
                "evidence_summary": evidence.summary,
                "graph_paths": [
                    path
                    for paths in evidence.paths_by_factor.values()
                    for path in paths
                ],
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
                calibrated=calibrated,
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
        goal = self.db.get(Goal, scenario.goal_id)
        if goal is None:
            return None, [], []
        pathway = resolve_scenario_pathway(self.db, scenario)

        requirements: list[Requirement] = []
        risk_factors: list[RiskFactor] = []

        if pathway is not None:
            # §11.3: Load requirements from the pathway_requirements M2M table.
            # Fall back to legacy pathway_id column if no M2M rows exist (e.g.
            # pre-migration data).
            from app.models.goal import pathway_requirements, pathway_risk_factors

            req_stmt = (
                select(Requirement)
                .join(pathway_requirements, pathway_requirements.c.requirement_id == Requirement.id)
                .where(pathway_requirements.c.pathway_id == pathway.id)
                .order_by(Requirement.weight.desc())
            )
            requirements = list(self.db.scalars(req_stmt))

            # Legacy fallback: if no M2M rows, use pathway_id column
            if not requirements and pathway is not None:
                requirements = list(
                    self.db.scalars(
                        select(Requirement)
                        .where(Requirement.pathway_id == pathway.id)
                        .order_by(Requirement.weight.desc())
                    )
                )

            # §11.3 bug fix: Load risk factors from the pathway_risk_factors
            # M2M table. Previously risk factors were loaded globally by region
            # with limit(5), causing every branch in the same region to show
            # the same key_risk_factors. Now each pathway has its own set.
            rf_stmt = (
                select(RiskFactor)
                .join(pathway_risk_factors, pathway_risk_factors.c.risk_factor_id == RiskFactor.id)
                .where(
                    pathway_risk_factors.c.pathway_id == pathway.id,
                    RiskFactor.deleted_at.is_(None),
                    risk_scope_clause(goal.user_id),
                )
                .order_by(RiskFactor.level.desc())
            )
            risk_factors = list(self.db.scalars(rf_stmt))

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
