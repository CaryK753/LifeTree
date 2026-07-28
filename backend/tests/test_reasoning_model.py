from types import SimpleNamespace

import pytest

from app.core.legal import PRIVACY_VERSION, TERMS_VERSION, is_current_consent
from app.services.reasoning.bayesian import BayesianEstimator
from app.services.reasoning.monte_carlo import MonteCarloSimulator


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


def test_legal_consent_requires_current_versions() -> None:
    assert is_current_consent(True, TERMS_VERSION, PRIVACY_VERSION)
    assert not is_current_consent(False, TERMS_VERSION, PRIVACY_VERSION)
    assert not is_current_consent(True, "old", PRIVACY_VERSION)
