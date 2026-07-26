"""Scenario branch management.

Per project plan §4.3: when conflicting assertions or user "what-if"
queries arise, spawn a Scenario branch with independent assumptions.
Branches are pruned by impact_threshold; dormant branches go to sleep.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.scenario import Scenario, ScenarioRun, ScenarioStatus
from app.services.graph import GraphService
from app.services.reasoning import ReasoningEngine

log = get_logger(__name__)


class ScenarioService:
    """CRUD + lifecycle for scenario branches."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.graph = GraphService()
        self.reasoning = ReasoningEngine(db)

    # ---------------- CRUD ----------------

    def create(self, **kwargs) -> Scenario:
        scenario = Scenario(id=str(uuid.uuid4()), **kwargs)
        self.db.add(scenario)
        self.db.commit()
        self.graph.upsert_scenario(scenario)
        log.info("scenario.created", id=scenario.id, goal_id=scenario.goal_id)
        return scenario

    def get(self, scenario_id: str) -> Scenario:
        scenario = self.db.get(Scenario, scenario_id)
        if scenario is None:
            raise NotFoundError(f"Scenario {scenario_id} not found")
        return scenario

    def list_for_goal(self, goal_id: str) -> list[Scenario]:
        return list(
            self.db.scalars(
                select(Scenario)
                .where(Scenario.goal_id == goal_id)
                .order_by(Scenario.created_at.desc())
            )
        )

    def update(self, scenario_id: str, **fields) -> Scenario:
        scenario = self.get(scenario_id)
        for k, v in fields.items():
            if v is not None and hasattr(scenario, k):
                setattr(scenario, k, v)
        self.db.commit()
        return scenario

    # ---------------- Lifecycle ----------------

    def spawn_branch(
        self,
        parent: Scenario,
        *,
        name: str,
        assumptions: dict,
        impact_threshold: float = 0.05,
    ) -> Scenario:
        """Create a child branch off an existing scenario."""
        branch = Scenario(
            id=str(uuid.uuid4()),
            goal_id=parent.goal_id,
            name=name,
            status=ScenarioStatus.DRAFT.value,
            parent_scenario_id=parent.id,
            assumptions=assumptions,
            impact_threshold=impact_threshold,
        )
        self.db.add(branch)
        self.db.commit()
        self.graph.upsert_scenario(branch)
        log.info("scenario.branch_spawned", parent=parent.id, child=branch.id)
        return branch

    def close(self, scenario_id: str, reason: str = "closed") -> Scenario:
        return self.update(scenario_id, status=ScenarioStatus.CLOSED.value, meta={"close_reason": reason})

    def merge_into_parent(self, scenario_id: str) -> Scenario | None:
        scenario = self.get(scenario_id)
        if scenario.parent_scenario_id is None:
            return None
        parent = self.get(scenario.parent_scenario_id)
        # Carry computed outputs up
        parent.success_probability = scenario.success_probability
        parent.risk_score = scenario.risk_score
        parent.key_risk_factors = scenario.key_risk_factors
        parent.computed_at = datetime.now(timezone.utc)
        scenario.status = ScenarioStatus.MERGED.value
        self.db.commit()
        return parent

    # ---------------- Computation ----------------

    def run_reasoning(self, scenario_id: str) -> ScenarioRun:
        """Trigger the reasoning engine and cache results on the scenario."""
        scenario = self.get(scenario_id)
        run = self.reasoning.run_full(scenario)
        # Cache key outputs back onto the scenario
        scenario.success_probability = run.result.get("success_probability", {})
        scenario.risk_score = run.result.get("overall_risk")
        scenario.key_risk_factors = run.result.get("key_risk_factors", [])
        scenario.computed_at = datetime.now(timezone.utc)
        if scenario.status == ScenarioStatus.DRAFT.value:
            scenario.status = ScenarioStatus.ACTIVE.value
        self.db.commit()
        return run

    def prune_low_impact(self, goal_id: str) -> int:
        """Move low-impact dormant scenarios to closed; return count closed."""
        scenarios = self.list_for_goal(goal_id)
        closed = 0
        for s in scenarios:
            if (
                s.status == ScenarioStatus.DORMANT.value
                and (s.risk_score or 0.0) < s.impact_threshold
            ):
                s.status = ScenarioStatus.CLOSED.value
                closed += 1
        if closed:
            self.db.commit()
        return closed
