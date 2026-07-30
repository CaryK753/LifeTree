"""Ownership, linkage, and state invariants for actions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.action import Action
from app.models.goal import (
    Goal,
    Pathway,
    Requirement,
    RiskFactor,
    pathway_requirements,
    pathway_risk_factors,
)
from app.models.scenario import Scenario


def get_user_action(db: Session, action_id: str, user_id: str) -> Action:
    """Return an action only when it belongs to the requesting user."""
    action = db.get(Action, action_id)
    if action is None or action.user_id != user_id:
        raise NotFoundError("Action not found")
    return action


def validate_action_links(
    db: Session,
    *,
    user_id: str,
    goal_id: str,
    scenario_id: str | None = None,
    pathway_id: str | None = None,
    requirement_id: str | None = None,
    risk_factor_id: str | None = None,
) -> Goal:
    """Ensure every optional action link belongs to the same user goal."""
    goal = db.get(Goal, goal_id)
    if goal is None or goal.user_id != user_id:
        raise NotFoundError("Goal not found")

    if scenario_id:
        scenario = db.get(Scenario, scenario_id)
        if scenario is None or scenario.goal_id != goal_id:
            raise ValidationFailedError("Scenario does not belong to the action goal")

    if pathway_id:
        pathway = db.get(Pathway, pathway_id)
        if pathway is None or pathway.goal_id != goal_id:
            raise ValidationFailedError("Pathway does not belong to the action goal")

    if requirement_id and not _requirement_belongs_to_goal(db, requirement_id, goal_id):
        raise ValidationFailedError("Requirement does not belong to the action goal")

    if risk_factor_id and not _risk_factor_belongs_to_goal(db, risk_factor_id, goal_id):
        raise ValidationFailedError("Risk factor is not linked to the action goal")

    return goal


def apply_action_updates(
    db: Session,
    action: Action,
    updates: dict[str, Any],
) -> None:
    """Validate links, apply fields, and keep completion state consistent."""
    link_fields = (
        "scenario_id",
        "pathway_id",
        "requirement_id",
        "risk_factor_id",
    )
    validate_action_links(
        db,
        user_id=action.user_id,
        goal_id=action.goal_id,
        **{field: updates.get(field, getattr(action, field)) for field in link_fields},
    )

    status = updates.pop("status", None)
    for key, value in updates.items():
        setattr(action, key, value)
    if status is not None:
        set_action_status(db, action, status)


def set_action_status(db: Session, action: Action, status: str) -> None:
    """Apply a status transition and its requirement write-back."""
    if (
        status == "completed"
        and action.requirement_id
        and not _requirement_belongs_to_goal(db, action.requirement_id, action.goal_id)
    ):
        raise ValidationFailedError("Requirement does not belong to the action goal")

    action.status = status
    if status == "completed":
        action.completed_at = datetime.now(timezone.utc).isoformat()
        if action.requirement_id:
            requirement = db.get(Requirement, action.requirement_id)
            if requirement is not None:
                requirement.gap_status = "met"
                db.add(requirement)
    else:
        action.completed_at = None


def _requirement_belongs_to_goal(
    db: Session, requirement_id: str, goal_id: str
) -> bool:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        return False
    if requirement.pathway_id:
        pathway = db.get(Pathway, requirement.pathway_id)
        if pathway is not None and pathway.goal_id == goal_id:
            return True
    linked_id = db.scalar(
        select(Requirement.id)
        .join(
            pathway_requirements,
            pathway_requirements.c.requirement_id == Requirement.id,
        )
        .join(Pathway, Pathway.id == pathway_requirements.c.pathway_id)
        .where(Requirement.id == requirement_id, Pathway.goal_id == goal_id)
        .limit(1)
    )
    return linked_id is not None


def _risk_factor_belongs_to_goal(
    db: Session, risk_factor_id: str, goal_id: str
) -> bool:
    linked_id = db.scalar(
        select(RiskFactor.id)
        .join(
            pathway_risk_factors,
            pathway_risk_factors.c.risk_factor_id == RiskFactor.id,
        )
        .join(Pathway, Pathway.id == pathway_risk_factors.c.pathway_id)
        .join(Goal, Goal.id == Pathway.goal_id)
        .where(
            RiskFactor.id == risk_factor_id,
            RiskFactor.deleted_at.is_(None),
            Pathway.goal_id == goal_id,
            (RiskFactor.user_id.is_(None)) | (RiskFactor.user_id == Goal.user_id),
        )
        .limit(1)
    )
    return linked_id is not None


__all__ = [
    "apply_action_updates",
    "get_user_action",
    "set_action_status",
    "validate_action_links",
]
