"""Scenario CRUD + reasoning-run endpoints.

Multi-user isolation: every endpoint verifies that the caller owns the
goal associated with the scenario. In single-user mode CurrentUser falls
back to the default user, so behavior is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.goal import Goal, Pathway
from app.models.scenario import Scenario, ScenarioRun
from app.schemas.api import (
    EvolutionProjectionRead,
    ScenarioCreate,
    ScenarioRead,
    ScenarioRunRead,
    ScenarioUpdate,
)
from app.services.scenarios import ScenarioService

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _verify_goal_owner(goal_id: str, user: CurrentUser, db: Session) -> Goal:
    """Fetch a goal and verify the caller owns it (admin can read any)."""
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    if goal.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this goal")
    return goal


def _verify_scenario_owner(
    scenario_id: str, user: CurrentUser, db: Session
) -> Scenario:
    """Fetch a scenario and verify ownership via its parent goal."""
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(404, "Scenario not found")
    _verify_goal_owner(scenario.goal_id, user, db)
    return scenario


@router.post("", response_model=ScenarioRead, status_code=201)
def create_scenario(
    payload: ScenarioCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> ScenarioRead:
    _verify_goal_owner(payload.goal_id, user, db)
    if payload.pathway_id:
        pathway = db.get(Pathway, payload.pathway_id)
        if pathway is None or pathway.goal_id != payload.goal_id:
            raise HTTPException(422, "Pathway does not belong to the scenario goal")
    return ScenarioService(db).create(**payload.model_dump())


@router.get("", response_model=list[ScenarioRead])
def list_scenarios(
    goal_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> list[dict]:
    """List scenarios for a goal.

    Includes ``survival_curve`` / ``key_risk_times`` / ``median_time_months``
    from each scenario's latest reasoning run, so the frontend
    scenario-comparison overlay view can render every branch's probability
    curve in a single request (no N+1 follow-up calls).
    """
    _verify_goal_owner(goal_id, user, db)
    svc = ScenarioService(db)
    return [svc.to_read_with_curve(s) for s in svc.list_for_goal(goal_id)]


@router.post("/evolve-all")
def evolve_all_scenarios(
    goal_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    """Evolve every active pathway scenario for one owned goal."""
    from app.services.evolution import EvolutionService

    _verify_goal_owner(goal_id, user, db)
    scenarios = list(db.scalars(select(Scenario).where(
        Scenario.goal_id == goal_id,
        Scenario.status.in_(["active", "draft"]),
    )))
    results = []
    for scenario in scenarios:
        try:
            projection = EvolutionService(db).evolve(scenario, user)
            results.append({"scenario_id": scenario.id, "ok": True, "result": projection})
        except Exception as exc:  # noqa: BLE001
            results.append({"scenario_id": scenario.id, "ok": False, "error": str(exc)})
    return {"goal_id": goal_id, "count": len(results), "results": results}


@router.get("/evolution/calibration")
def evolution_calibration(
    user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    from app.services.evolution_feedback import EvolutionFeedbackService

    return EvolutionFeedbackService(db).calibration(user.id)


@router.get("/{scenario_id}", response_model=ScenarioRead)
def get_scenario(
    scenario_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    _verify_scenario_owner(scenario_id, user, db)
    return ScenarioService(db).to_read_with_curve(
        ScenarioService(db).get(scenario_id)
    )


@router.patch("/{scenario_id}", response_model=ScenarioRead)
def update_scenario(
    scenario_id: str,
    payload: ScenarioUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> ScenarioRead:
    scenario = _verify_scenario_owner(scenario_id, user, db)
    if payload.pathway_id:
        pathway = db.get(Pathway, payload.pathway_id)
        if pathway is None or pathway.goal_id != scenario.goal_id:
            raise HTTPException(422, "Pathway does not belong to the scenario goal")
    return ScenarioService(db).update(scenario_id, **payload.model_dump(exclude_unset=True))


@router.delete("/{scenario_id}", status_code=204)
def close_scenario(
    scenario_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> None:
    _verify_scenario_owner(scenario_id, user, db)
    ScenarioService(db).close(scenario_id)


@router.post("/{scenario_id}/run", response_model=ScenarioRunRead)
def run_reasoning(
    scenario_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> ScenarioRun:
    _verify_scenario_owner(scenario_id, user, db)
    return ScenarioService(db).run_reasoning(scenario_id)


@router.post("/{scenario_id}/evolve", response_model=EvolutionProjectionRead)
def evolve_scenario(
    scenario_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> EvolutionProjectionRead:
    """Trigger LLM-driven self-evolution for a scenario.

    Projects the next 24 months of events (milestones, risks, opportunities,
    decisions) by calling the chat-role LLM with a structured-output schema.
    The result is cached on ``scenario.meta["evolution"]`` so subsequent
    reads are instant.
    """
    from app.core.exceptions import LifeTreeError
    from app.services.evolution import EvolutionService

    scenario = _verify_scenario_owner(scenario_id, user, db)
    try:
        result = EvolutionService(db).evolve(scenario, user)
    except LifeTreeError:
        raise  # domain errors (e.g. LLMNotConfiguredError) have proper status codes
    except Exception as exc:
        raise HTTPException(500, f"Evolution failed: {exc}") from exc
    proj = result["projection"]
    return EvolutionProjectionRead(
        summary=proj["summary"],
        projected_events=proj["events"],
        trajectory=result["trajectory"],
        final_probability=proj["final_probability"],
        confidence=proj["confidence"],
        evolved_at=datetime.now(timezone.utc).isoformat(),
        horizon_months=result["horizon_months"],
        cached=False,
    )


@router.get("/{scenario_id}/evolve", response_model=EvolutionProjectionRead)
def get_evolution(
    scenario_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> EvolutionProjectionRead:
    """Return the cached evolution projection for a scenario.

    Returns 404 if the scenario has never been evolved.
    """
    scenario = _verify_scenario_owner(scenario_id, user, db)
    meta = dict(scenario.meta or {})
    cached = meta.get("evolution")
    if not cached:
        raise HTTPException(
            status_code=404,
            detail="No evolution projection found. POST /scenarios/{id}/evolve to generate one.",
        )
    return EvolutionProjectionRead(
        summary=cached.get("summary", ""),
        projected_events=cached.get("projected_events", []),
        trajectory=cached.get("trajectory", []),
        final_probability=cached.get("final_probability", 0.0),
        confidence=cached.get("confidence", 0.0),
        evolved_at=cached.get("evolved_at"),
        horizon_months=24,
        cached=True,
    )


@router.get("/{scenario_id}/runs", response_model=list[ScenarioRunRead])
def list_runs(
    scenario_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> list[ScenarioRun]:
    _verify_scenario_owner(scenario_id, user, db)
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
    user: CurrentUser,
    impact_threshold: float = 0.05,
    db: Session = Depends(get_db),
) -> ScenarioRead:
    parent = _verify_scenario_owner(scenario_id, user, db)
    return ScenarioService(db).spawn_branch(
        parent, name=name, assumptions=assumptions, impact_threshold=impact_threshold
    )


@router.post("/goals/{goal_id}/prune", response_model=int)
def prune_low_impact(
    goal_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> int:
    _verify_goal_owner(goal_id, user, db)
    return ScenarioService(db).prune_low_impact(goal_id)


@router.post("/{scenario_id}/merge", response_model=ScenarioRead)
def merge_into_parent(
    scenario_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> ScenarioRead:
    """Merge a child branch back into its parent.

    Carries the child's latest computed outputs (success_probability,
    risk_score, key_risk_factors) onto the parent and marks the child
    as ``merged``. Implements §4.3 of the project plan: "当存疑信息被
    证实或证伪时，分支自动合并".
    """
    _verify_scenario_owner(scenario_id, user, db)
    parent = ScenarioService(db).merge_into_parent(scenario_id)
    if parent is None:
        raise HTTPException(
            status_code=400,
            detail="Scenario has no parent — cannot merge",
        )
    return parent
