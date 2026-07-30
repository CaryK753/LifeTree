from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.scenarios import create_scenario, evolve_scenario
from app.models.goal import Pathway
from app.schemas.api import ScenarioCreate
from app.services.scenarios import ScenarioService


class _ScenarioCreateSession:
    def __init__(self, pathways):
        self.pathways = pathways

    def get(self, model, object_id):
        if model is Pathway:
            return next((item for item in self.pathways if item.id == object_id), None)
        return None

    def scalars(self, _statement):
        return iter(self.pathways)


def _pathway(pathway_id: str):
    return SimpleNamespace(
        id=pathway_id,
        goal_id="goal-1",
        deleted_at=None,
    )


def _user():
    return SimpleNamespace(id="user-1", role="user")


def _patch_goal_owner(monkeypatch):
    monkeypatch.setattr(
        "app.api.scenarios.verify_goal_owner",
        lambda goal_id, user, db: SimpleNamespace(id=goal_id, user_id=user.id),
    )


def test_create_scenario_auto_binds_only_pathway(monkeypatch) -> None:
    _patch_goal_owner(monkeypatch)
    captured = {}

    def create(_service, **fields):
        captured.update(fields)
        return SimpleNamespace(**fields)

    monkeypatch.setattr(ScenarioService, "create", create)
    payload = ScenarioCreate(goal_id="goal-1", name="Higher score")

    create_scenario(payload, _user(), _ScenarioCreateSession([_pathway("path-1")]))

    assert captured["pathway_id"] == "path-1"


def test_create_scenario_requires_pathway_when_goal_has_multiple(monkeypatch) -> None:
    _patch_goal_owner(monkeypatch)
    payload = ScenarioCreate(goal_id="goal-1", name="Higher score")
    db = _ScenarioCreateSession([_pathway("path-1"), _pathway("path-2")])

    with pytest.raises(HTTPException) as error:
        create_scenario(payload, _user(), db)

    assert error.value.status_code == 422
    assert "pathway_id is required" in error.value.detail


def test_evolution_uses_selected_scenario(monkeypatch) -> None:
    scenario = SimpleNamespace(
        id="scenario-1",
        goal_id="goal-1",
        pathway_id="path-1",
    )
    pathway = _pathway("path-1")
    captured = {}
    db = _ScenarioCreateSession([pathway])
    monkeypatch.setattr(
        "app.api.scenarios.verify_scenario_owner",
        lambda scenario_id, user, session: scenario,
    )

    def evolve(_service, selected_pathway, user, selected_scenario=None):
        captured["scenario"] = selected_scenario
        return {
            "projection": {
                "summary": "projection",
                "events": [],
                "final_probability": 0.5,
                "confidence": 0.8,
            },
            "trajectory": [],
            "horizon_months": 24,
        }

    monkeypatch.setattr("app.services.evolution.EvolutionService.evolve", evolve)

    evolve_scenario("scenario-1", _user(), db)

    assert captured["scenario"] is scenario
