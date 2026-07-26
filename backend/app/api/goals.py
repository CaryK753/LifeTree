"""Goal / Pathway / Requirement CRUD endpoints.

Multi-user isolation: every endpoint resolves the authenticated user via
``CurrentUser`` and filters data by ``user.id``. In single-user mode the
``CurrentUser`` dependency falls back to the default user, so behavior is
unchanged. Admins can read (but not mutate) other users' goals for the
admin user-management view.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.goal import Goal, Pathway, Requirement
from app.schemas.entities import (
    GoalCreate,
    GoalRead,
    GoalUpdate,
    PathwayCreate,
    PathwayRead,
    PathwayUpdate,
    RequirementCreate,
    RequirementRead,
    RequirementUpdate,
)
from app.services.graph import GraphService

router = APIRouter(prefix="/goals", tags=["goals"])
graph = GraphService()


# ---------- Ownership helpers ----------


def _get_owned_goal(goal_id: str, user: CurrentUser, db: Session) -> Goal:
    """Fetch a goal and verify the caller owns it.

    Admins can read any goal (for the admin user-management view) but
    cannot mutate goals they don't own — mutations require ownership.
    """
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    if goal.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this goal")
    return goal


def _get_owned_pathway(pathway_id: str, user: CurrentUser, db: Session) -> Pathway:
    """Fetch a pathway and verify ownership via its parent goal."""
    pathway = db.get(Pathway, pathway_id)
    if pathway is None:
        raise HTTPException(404, "Pathway not found")
    goal = db.get(Goal, pathway.goal_id)
    if goal is None or (goal.user_id != user.id and user.role != "admin"):
        raise HTTPException(403, "You do not have access to this pathway")
    return pathway


def _get_owned_requirement(requirement_id: str, user: CurrentUser, db: Session) -> Requirement:
    """Fetch a requirement and verify ownership via its parent pathway→goal."""
    req = db.get(Requirement, requirement_id)
    if req is None:
        raise HTTPException(404, "Requirement not found")
    pathway = db.get(Pathway, req.pathway_id)
    if pathway is None:
        raise HTTPException(404, "Pathway not found")
    goal = db.get(Goal, pathway.goal_id)
    if goal is None or (goal.user_id != user.id and user.role != "admin"):
        raise HTTPException(403, "You do not have access to this requirement")
    return req


# ---------- Goals ----------

@router.post("", response_model=GoalRead, status_code=201)
def create_goal(
    payload: GoalCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> Goal:
    data = payload.model_dump()
    pathways_data = data.pop("pathways", [])
    # Always associate the new goal with the authenticated user, ignoring
    # any client-supplied user_id to prevent cross-user pollution.
    data["user_id"] = user.id
    goal = Goal(**data)
    db.add(goal)
    db.flush()
    for p in pathways_data:
        reqs = p.pop("requirements", [])
        pathway = Pathway(goal_id=goal.id, **p)
        db.add(pathway)
        db.flush()
        for r in reqs:
            db.add(Requirement(pathway_id=pathway.id, **r))
    db.commit()
    db.refresh(goal)
    graph.upsert_goal(goal)
    return goal


@router.get("", response_model=list[GoalRead])
def list_goals(
    user: CurrentUser,
    user_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[Goal]:
    # Admins can optionally filter by a specific user_id (admin user-management
    # view). Non-admins always see only their own goals; a client-supplied
    # user_id is ignored to prevent cross-user enumeration.
    target_id = user.id
    if user_id and user.role == "admin":
        target_id = user_id
    stmt = (
        select(Goal)
        .where(Goal.user_id == target_id)
        .order_by(Goal.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


@router.get("/{goal_id}", response_model=GoalRead)
def get_goal(goal_id: str, user: CurrentUser, db: Session = Depends(get_db)) -> Goal:
    return _get_owned_goal(goal_id, user, db)


@router.patch("/{goal_id}", response_model=GoalRead)
def update_goal(
    goal_id: str, payload: GoalUpdate, user: CurrentUser, db: Session = Depends(get_db)
) -> Goal:
    goal = _get_owned_goal(goal_id, user, db)
    # Prevent user_id reassignment (would transfer ownership to another user).
    updates = payload.model_dump(exclude_unset=True)
    updates.pop("user_id", None)
    for k, v in updates.items():
        setattr(goal, k, v)
    db.commit()
    db.refresh(goal)
    graph.upsert_goal(goal)
    return goal


@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: str, user: CurrentUser, db: Session = Depends(get_db)) -> None:
    goal = _get_owned_goal(goal_id, user, db)
    db.delete(goal)
    db.commit()


# ---------- Pathways ----------

@router.post("/{goal_id}/pathways", response_model=PathwayRead, status_code=201)
def add_pathway(
    goal_id: str, payload: PathwayCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> Pathway:
    _get_owned_goal(goal_id, user, db)
    data = payload.model_dump()
    reqs = data.pop("requirements", [])
    pathway = Pathway(goal_id=goal_id, **data)
    db.add(pathway)
    db.flush()
    for r in reqs:
        db.add(Requirement(pathway_id=pathway.id, **r))
    db.commit()
    db.refresh(pathway)
    graph.upsert_pathway(pathway)
    return pathway


@router.get("/{goal_id}/pathways", response_model=list[PathwayRead])
def list_pathways(
    goal_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> list[Pathway]:
    _get_owned_goal(goal_id, user, db)
    return list(
        db.scalars(
            select(Pathway)
            .where(Pathway.goal_id == goal_id)
            .order_by(Pathway.created_at.asc())
        )
    )


@router.patch("/pathways/{pathway_id}", response_model=PathwayRead)
def update_pathway(
    pathway_id: str, payload: PathwayUpdate, user: CurrentUser, db: Session = Depends(get_db)
) -> Pathway:
    pathway = _get_owned_pathway(pathway_id, user, db)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(pathway, k, v)
    db.commit()
    db.refresh(pathway)
    graph.upsert_pathway(pathway)
    return pathway


@router.delete("/pathways/{pathway_id}", status_code=204)
def delete_pathway(pathway_id: str, user: CurrentUser, db: Session = Depends(get_db)) -> None:
    pathway = _get_owned_pathway(pathway_id, user, db)
    db.delete(pathway)
    db.commit()


# ---------- Requirements ----------

@router.post("/pathways/{pathway_id}/requirements", response_model=RequirementRead, status_code=201)
def add_requirement(
    pathway_id: str, payload: RequirementCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> Requirement:
    _get_owned_pathway(pathway_id, user, db)
    req = Requirement(pathway_id=pathway_id, **payload.model_dump())
    db.add(req)
    db.commit()
    db.refresh(req)
    graph.upsert_requirement(req)
    return req


@router.get("/pathways/{pathway_id}/requirements", response_model=list[RequirementRead])
def list_requirements(
    pathway_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> list[Requirement]:
    _get_owned_pathway(pathway_id, user, db)
    return list(
        db.scalars(
            select(Requirement)
            .where(Requirement.pathway_id == pathway_id)
            .order_by(Requirement.weight.desc())
        )
    )


@router.patch("/requirements/{requirement_id}", response_model=RequirementRead)
def update_requirement(
    requirement_id: str, payload: RequirementUpdate, user: CurrentUser, db: Session = Depends(get_db)
) -> Requirement:
    req = _get_owned_requirement(requirement_id, user, db)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(req, k, v)
    db.commit()
    db.refresh(req)
    graph.upsert_requirement(req)
    return req


@router.delete("/requirements/{requirement_id}", status_code=204)
def delete_requirement(requirement_id: str, user: CurrentUser, db: Session = Depends(get_db)) -> None:
    req = _get_owned_requirement(requirement_id, user, db)
    db.delete(req)
    db.commit()
