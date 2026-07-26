"""Goal / Pathway / Requirement CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import get_default_user
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


# ---------- Goals ----------

@router.post("", response_model=GoalRead, status_code=201)
def create_goal(payload: GoalCreate, db: Session = Depends(get_db)) -> Goal:
    data = payload.model_dump()
    pathways_data = data.pop("pathways", [])
    # Single-user mode: resolve user_id server-side if the client didn't send one.
    if not data.get("user_id"):
        data["user_id"] = get_default_user(db).id
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
    user_id: str | None = None, limit: int = 50, db: Session = Depends(get_db)
) -> list[Goal]:
    # Single-user mode: user_id filter is accepted for backward compat but ignored.
    stmt = select(Goal).order_by(Goal.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


@router.get("/{goal_id}", response_model=GoalRead)
def get_goal(goal_id: str, db: Session = Depends(get_db)) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    return goal


@router.patch("/{goal_id}", response_model=GoalRead)
def update_goal(
    goal_id: str, payload: GoalUpdate, db: Session = Depends(get_db)
) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(goal, k, v)
    db.commit()
    db.refresh(goal)
    graph.upsert_goal(goal)
    return goal


@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: str, db: Session = Depends(get_db)) -> None:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    db.delete(goal)
    db.commit()


# ---------- Pathways ----------

@router.post("/{goal_id}/pathways", response_model=PathwayRead, status_code=201)
def add_pathway(
    goal_id: str, payload: PathwayCreate, db: Session = Depends(get_db)
) -> Pathway:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
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
def list_pathways(goal_id: str, db: Session = Depends(get_db)) -> list[Pathway]:
    return list(
        db.scalars(
            select(Pathway)
            .where(Pathway.goal_id == goal_id)
            .order_by(Pathway.created_at.asc())
        )
    )


@router.patch("/pathways/{pathway_id}", response_model=PathwayRead)
def update_pathway(
    pathway_id: str, payload: PathwayUpdate, db: Session = Depends(get_db)
) -> Pathway:
    pathway = db.get(Pathway, pathway_id)
    if pathway is None:
        raise HTTPException(404, "Pathway not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(pathway, k, v)
    db.commit()
    db.refresh(pathway)
    graph.upsert_pathway(pathway)
    return pathway


@router.delete("/pathways/{pathway_id}", status_code=204)
def delete_pathway(pathway_id: str, db: Session = Depends(get_db)) -> None:
    pathway = db.get(Pathway, pathway_id)
    if pathway is None:
        raise HTTPException(404, "Pathway not found")
    db.delete(pathway)
    db.commit()


# ---------- Requirements ----------

@router.post("/pathways/{pathway_id}/requirements", response_model=RequirementRead, status_code=201)
def add_requirement(
    pathway_id: str, payload: RequirementCreate, db: Session = Depends(get_db)
) -> Requirement:
    pathway = db.get(Pathway, pathway_id)
    if pathway is None:
        raise HTTPException(404, "Pathway not found")
    req = Requirement(pathway_id=pathway_id, **payload.model_dump())
    db.add(req)
    db.commit()
    db.refresh(req)
    graph.upsert_requirement(req)
    return req


@router.get("/pathways/{pathway_id}/requirements", response_model=list[RequirementRead])
def list_requirements(pathway_id: str, db: Session = Depends(get_db)) -> list[Requirement]:
    return list(
        db.scalars(
            select(Requirement)
            .where(Requirement.pathway_id == pathway_id)
            .order_by(Requirement.weight.desc())
        )
    )


@router.patch("/requirements/{requirement_id}", response_model=RequirementRead)
def update_requirement(
    requirement_id: str, payload: RequirementUpdate, db: Session = Depends(get_db)
) -> Requirement:
    req = db.get(Requirement, requirement_id)
    if req is None:
        raise HTTPException(404, "Requirement not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(req, k, v)
    db.commit()
    db.refresh(req)
    graph.upsert_requirement(req)
    return req


@router.delete("/requirements/{requirement_id}", status_code=204)
def delete_requirement(requirement_id: str, db: Session = Depends(get_db)) -> None:
    req = db.get(Requirement, requirement_id)
    if req is None:
        raise HTTPException(404, "Requirement not found")
    db.delete(req)
    db.commit()
