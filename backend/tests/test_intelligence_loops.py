from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.model_params import PredictionOutcomeRead
from app.core.exceptions import ConflictError
from app.services.action_scheduler import ActionScheduler
from app.services.calibration_monitor import MIN_CALIBRATION_SAMPLES
from app.services.evolution_feedback import EvolutionFeedbackService
from app.services.notification import NotificationService
from app.services.plugin_sandbox import inspect_plugin
from app.services.risk_proposals import RiskProposalService
from app.services.source_reputation import SourceReputationService
from app.services.tree_evolution import TreeEvolutionService
from app.services.tree_evolution_contracts import BranchProposal, branch_identity_key


class _ReputationSession:
    def __init__(self):
        self.added = []

    def scalar(self, _statement):
        return None

    def add(self, value):
        self.added.append(value)


def test_monthly_recurrence_clamps_to_calendar_end() -> None:
    assert ActionScheduler._next_date(date(2028, 1, 31), "monthly") == date(2028, 2, 29)
    assert ActionScheduler._next_date(date(2027, 1, 31), "monthly") == date(2027, 2, 28)


def test_source_reputation_uses_bounded_beta_updates() -> None:
    db = _ReputationSession()
    source = SimpleNamespace(id="source-1", user_id="user-1", credibility_score=0.5, meta={})
    service = SourceReputationService(db, "user-1")

    first = service.record_verdict(source, evidence_key="decision-1", confirmed=True)
    second = service.record_verdict(source, evidence_key="decision-2", confirmed=False)

    assert first.resulting_score == pytest.approx(0.6)
    assert second.resulting_score == pytest.approx(0.5)
    assert 0.0 < source.credibility_score < 1.0
    assert source.meta["accuracy_observations"] == 2


def test_risk_proposal_fingerprint_suppresses_cosmetic_duplicates() -> None:
    first = RiskProposalService._fingerprint(
        {"name": "Visa policy tightening", "type": "policy", "region": "CA"}
    )
    second = RiskProposalService._fingerprint(
        {"name": "visa-policy tightening!", "type": "POLICY", "region": "ca"}
    )
    assert first == second


def test_evolution_counterfactual_requires_low_probability_material_risk() -> None:
    assert EvolutionFeedbackService._needs_counterfactual(
        {"type": "risk", "probability": 0.3, "impact": -0.4}
    )
    assert not EvolutionFeedbackService._needs_counterfactual(
        {"type": "risk", "probability": 0.8, "impact": -0.4}
    )
    assert not EvolutionFeedbackService._needs_counterfactual(
        {"type": "milestone", "probability": 0.2, "impact": -0.4}
    )


def test_tree_evolution_accepts_compact_single_branch_output() -> None:
    proposal = BranchProposal.model_validate(
        {"branches": [{"branch_name": "Regional alternative"}]}
    )

    branch = proposal.branches[0]
    assert branch.branch_description == ""
    assert branch.key_requirements == []
    assert branch.key_risks == []


def test_tree_evolution_normalizes_duplicate_branch_names() -> None:
    assert branch_identity_key("Canada Express-Entry") == branch_identity_key(
        " canada_express entry! "
    )


def test_predicted_branch_must_be_confirmed_before_evolution() -> None:
    service = TreeEvolutionService(SimpleNamespace())

    with pytest.raises(ConflictError):
        service.evolve_branch(
            SimpleNamespace(status="predicted"),
            SimpleNamespace(id="user-1"),
        )


def test_calibration_gate_remains_honest() -> None:
    assert MIN_CALIBRATION_SAMPLES == 50


def test_prediction_outcome_schema_accepts_factor_list() -> None:
    outcome = PredictionOutcomeRead(
        id="outcome-1",
        goal_id="goal-1",
        goal_type="career",
        region="CA",
        factor_snapshot=[{"factor": "policy", "contribution": -0.12}],
        actual_outcome="achieved",
        actual_binary=1,
    )

    assert outcome.factor_snapshot[0]["factor"] == "policy"


def test_notification_prefers_configured_push_after_critical_sms_rule() -> None:
    service = object.__new__(NotificationService)
    push_user = SimpleNamespace(notify_channels={"push": True, "email": True})
    sms_user = SimpleNamespace(notify_channels={"sms": True, "push": True})

    assert service._pick_channel(push_user, "warning") == "push"
    assert service._pick_channel(sms_user, "critical") == "sms"


def test_plugin_manifest_runs_in_isolated_process() -> None:
    plugin = Path(__file__).resolve().parents[1] / "plugins" / "sample_web_scraper.py"
    manifest = inspect_plugin(plugin)
    assert manifest["id"] == "sample_web_scraper"
