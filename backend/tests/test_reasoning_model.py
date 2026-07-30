from types import SimpleNamespace

import pytest

from app.core.legal import PRIVACY_VERSION, TERMS_VERSION, is_current_consent
from app.services.reasoning.bayesian import BayesianEstimator
from app.services.reasoning.factor_model import aggregate_risk_exposure
from app.services.reasoning.monte_carlo import MonteCarloSimulator
from app.services.scenario_pathway import resolve_scenario_pathway


def requirement(
    factor_id: str,
    status: str = "partial",
    weight: float = 1.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=factor_id,
        name=f"Requirement {factor_id}",
        gap_status=status,
        weight=weight,
    )


def risk(factor_id: str, level: str = "high") -> SimpleNamespace:
    return SimpleNamespace(
        id=factor_id,
        name=f"Risk {factor_id}",
        level=level,
        probability=None,
        impact=None,
        type="policy",
    )


class _PathwaySession:
    def __init__(self, pathways, *, legacy=None):
        self.pathways = pathways
        self.legacy = legacy

    def get(self, model, object_id):
        if model.__name__ == "Pathway":
            return next((p for p in self.pathways if p.id == object_id), None)
        return None

    def scalar(self, _statement):
        return self.legacy

    def scalars(self, _statement):
        return iter(self.pathways)


def scenario(**overrides) -> SimpleNamespace:
    values = {
        "id": "scenario-1",
        "goal_id": "goal-1",
        "pathway_id": None,
        "parent_scenario_id": None,
        "name": "Scenario",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def pathway(pathway_id: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=pathway_id,
        goal_id="goal-1",
        name=name,
        created_at=None,
    )


def test_scenario_pathway_prefers_explicit_link() -> None:
    linked = pathway("path-2", "Blue Card")
    db = _PathwaySession([pathway("path-1", "EE"), linked])

    assert (
        resolve_scenario_pathway(db, scenario(pathway_id="path-2")) is linked
    )


def test_scenario_pathway_recovers_unique_name_match() -> None:
    matched = pathway("path-2", "Blue Card")
    db = _PathwaySession([pathway("path-1", "EE"), matched])

    assert resolve_scenario_pathway(db, scenario(name=" blue-card ")) is matched


def test_ambiguous_scenario_does_not_fall_back_to_first_pathway() -> None:
    db = _PathwaySession([pathway("path-1", "EE"), pathway("path-2", "Blue Card")])

    assert resolve_scenario_pathway(db, scenario(name="What if")) is None


def test_duplicate_requirement_does_not_improve_success() -> None:
    estimator = BayesianEstimator()
    goal = SimpleNamespace(id="goal")
    one = estimator.estimate(goal, None, [requirement("a")], [])
    duplicated = estimator.estimate(
        goal,
        None,
        [requirement("a"), requirement("b")],
        [],
    )

    assert duplicated.p_success <= one.p_success


def test_missing_requirement_and_high_risk_reduce_success() -> None:
    estimator = BayesianEstimator()
    goal = SimpleNamespace(id="goal")
    met = estimator.estimate(goal, None, [requirement("a", "met")], [])
    missing = estimator.estimate(
        goal, None, [requirement("a", "missing", weight=2.0)], []
    )
    with_risk = estimator.estimate(
        goal, None, [requirement("a", "met")], [risk("r")]
    )

    assert missing.p_success < met.p_success
    assert with_risk.p_success < met.p_success


def test_evidence_quality_narrows_monte_carlo_interval() -> None:
    simulator = MonteCarloSimulator()
    goal = SimpleNamespace(id="goal")
    factors = [requirement("a")]
    low_evidence = simulator.simulate(
        goal, None, factors, [], iterations=5000, seed=7, evidence_scores={"a": 0.0}
    )
    high_evidence = simulator.simulate(
        goal, None, factors, [], iterations=5000, seed=7, evidence_scores={"a": 1.0}
    )

    assert high_evidence.p90 - high_evidence.p10 < low_evidence.p90 - low_evidence.p10
    repeated = simulator.simulate(
        goal, None, factors, [], iterations=5000, seed=7, evidence_scores={"a": 1.0}
    )
    assert repeated.p50 == pytest.approx(high_evidence.p50)


def test_monte_carlo_uses_parameter_snapshot() -> None:
    simulator = MonteCarloSimulator()
    goal = SimpleNamespace(id="goal")
    factors = [requirement("a", "unknown")]

    pessimistic = simulator.simulate(
        goal,
        None,
        factors,
        [],
        iterations=5000,
        seed=11,
        params={"requirement_base_prob.unknown": 0.25},
    )
    optimistic = simulator.simulate(
        goal,
        None,
        factors,
        [],
        iterations=5000,
        seed=11,
        params={"requirement_base_prob.unknown": 0.75},
    )

    assert optimistic.p50 > pessimistic.p50


def test_risk_exposure_is_not_success_probability_complement() -> None:
    risk_score = aggregate_risk_exposure([0.8], {})

    assert risk_score == pytest.approx(0.2)
    assert risk_score != pytest.approx(1.0 - 0.32)


def test_explicit_branch_risk_changes_probability_and_risk_score() -> None:
    simulator = MonteCarloSimulator()
    goal = SimpleNamespace(id="goal")
    base_requirement = [requirement("a", "partial")]
    low_risk = risk("low", "low")
    low_risk.probability = 0.1
    low_risk.impact = 0.2
    high_risk = risk("high", "high")
    high_risk.probability = 0.8
    high_risk.impact = 0.9

    low = simulator.simulate(
        goal, None, base_requirement, [low_risk], iterations=5000, seed=17
    )
    high = simulator.simulate(
        goal, None, base_requirement, [high_risk], iterations=5000, seed=17
    )
    estimator = BayesianEstimator()
    low_survival = 1.0 - estimator._risk_failure_prob(low_risk, None)
    high_survival = 1.0 - estimator._risk_failure_prob(high_risk, None)

    assert low.p50 > high.p50
    assert aggregate_risk_exposure([low_survival]) < aggregate_risk_exposure(
        [high_survival]
    )


def test_legal_consent_requires_current_versions() -> None:
    assert is_current_consent(True, TERMS_VERSION, PRIVACY_VERSION)
    assert not is_current_consent(False, TERMS_VERSION, PRIVACY_VERSION)
    assert not is_current_consent(True, "old", PRIVACY_VERSION)
