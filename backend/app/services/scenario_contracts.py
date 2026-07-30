"""Ownership and pathway-binding contracts for scenario APIs."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.models.goal import Goal, Pathway
from app.models.scenario import Scenario


def verify_goal_owner(goal_id: str, user: CurrentUser, db: Session) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    if goal.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this goal")
    return goal


def verify_scenario_owner(
    scenario_id: str,
    user: CurrentUser,
    db: Session,
) -> Scenario:
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(404, "Scenario not found")
    verify_goal_owner(scenario.goal_id, user, db)
    return scenario


def resolve_create_pathway_id(
    db: Session,
    *,
    goal_id: str,
    pathway_id: str | None,
) -> str:
    if pathway_id:
        pathway = db.get(Pathway, pathway_id)
        if (
            pathway is None
            or pathway.goal_id != goal_id
            or pathway.deleted_at is not None
        ):
            raise HTTPException(422, "Pathway does not belong to the scenario goal")
        return pathway.id

    pathways = list(
        db.scalars(
            select(Pathway).where(
                Pathway.goal_id == goal_id,
                Pathway.deleted_at.is_(None),
            )
        )
    )
    if len(pathways) != 1:
        raise HTTPException(
            422,
            "pathway_id is required unless the goal has exactly one pathway",
        )
    return pathways[0].id
