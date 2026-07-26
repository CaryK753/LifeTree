"""Scenario CRUD + reasoning-run endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.models.scenario import ScenarioRun
from app.schemas.api import (
    ScenarioCreate,
    ScenarioRead,
    ScenarioRunRead,
    ScenarioUpdate,
)
from app.services.scenarios import ScenarioService

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.post("", response_model=ScenarioRead, status_code=201)
def create_scenario(
    payload: ScenarioCreate, db: Session = Depends(get_db)
) -> ScenarioRead:
    return ScenarioService(db).create(**payload.model_dump())


@router.get("", response_model=list[ScenarioRead])
def list_scenarios(goal_id: str, db: Session = Depends(get_db)) -> list[ScenarioRead]:
    return ScenarioService(db).list_for_goal(goal_id)


@router.get("/{scenario_id}", response_model=ScenarioRead)
def get_scenario(scenario_id: str, db: Session = Depends(get_db)) -> ScenarioRead:
    return ScenarioService(db).get(scenario_id)


@router.patch("/{scenario_id}", response_model=ScenarioRead)
def update_scenario(
    scenario_id: str, payload: ScenarioUpdate, db: Session = Depends(get_db)
) -> ScenarioRead:
    return ScenarioService(db).update(scenario_id, **payload.model_dump(exclude_unset=True))


@router.delete("/{scenario_id}", status_code=204)
def close_scenario(scenario_id: str, db: Session = Depends(get_db)) -> None:
    ScenarioService(db).close(scenario_id)


@router.post("/{scenario_id}/run", response_model=ScenarioRunRead)
def run_reasoning(scenario_id: str, db: Session = Depends(get_db)) -> ScenarioRun:
    return ScenarioService(db).run_reasoning(scenario_id)


@router.get("/{scenario_id}/runs", response_model=list[ScenarioRunRead])
def list_runs(scenario_id: str, db: Session = Depends(get_db)) -> list[ScenarioRun]:
    return list(
        db.scalars(
            select(ScenarioRun)
            .where(ScenarioRun.scenario_id == scenario_id)
            .order_by(ScenarioRun.created_at.desc())
        )
    )


@router.post("/{scenario_id}/branch", response_model=ScenarioRead, status_code=201)
def spawn_branch(
    scenario_id: str,
    name: str,
    assumptions: dict,
    impact_threshold: float = 0.05,
    db: Session = Depends(get_db),
) -> ScenarioRead:
    parent = ScenarioService(db).get(scenario_id)
    return ScenarioService(db).spawn_branch(
        parent, name=name, assumptions=assumptions, impact_threshold=impact_threshold
    )


@router.post("/goals/{goal_id}/prune", response_model=int)
def prune_low_impact(goal_id: str, db: Session = Depends(get_db)) -> int:
    return ScenarioService(db).prune_low_impact(goal_id)
