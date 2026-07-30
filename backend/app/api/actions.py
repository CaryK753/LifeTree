"""Action CRUD + ROI endpoints (P0-线B a2/a3).

Actions are user-actionable tasks derived from the reasoning engine or
created manually via the agent / UI. Completing an action can write back
to its linked Requirement (gap_status → met) so the scenario probability
recompute picks it up.

Multi-user isolation: every endpoint resolves the authenticated user via
``CurrentUser`` and verifies ownership via the action's parent goal.
Admins can read (but not mutate) other users' actions for the admin
user-management view.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.action import Action
from app.models.goal import Goal
from app.schemas.api import (
    ActionCreate,
    ActionRead,
    ActionROISort,
    ActionUpdate,
)
from app.services.action_integrity import (
    apply_action_updates,
    get_user_action,
    set_action_status,
    validate_action_links,
)
from app.services.action_scheduler import ActionScheduler

router = APIRouter(prefix="/actions", tags=["actions"])


# ---------- Ownership helpers ----------


def _get_owned_action(action_id: str, user: CurrentUser, db: Session) -> Action:
    """Fetch an action and verify ownership via its parent goal.

    Admins can read any action (for the admin user-management view) but
    cannot mutate actions they don't own — mutations require ownership.
    """
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(404, "Action not found")
    goal = db.get(Goal, action.goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    if goal.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this action")
    return action


def _roi_value(action: Action) -> float:
    """Compute ROI for sorting (expected_prob_lift / max(cost, 0.01))."""
    return (action.expected_prob_lift or 0.0) / max(action.cost or 0.0, 0.01)


# ---------- CRUD ----------


@router.post("", response_model=ActionRead, status_code=201)
def create_action(
    payload: ActionCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> Action:
    validate_action_links(
        db,
        user_id=user.id,
        goal_id=payload.goal_id,
        scenario_id=payload.scenario_id,
        pathway_id=payload.pathway_id,
        requirement_id=payload.requirement_id,
        risk_factor_id=payload.risk_factor_id,
    )
    # Always associate the new action with the authenticated user, ignoring
    # any client-supplied user_id to prevent cross-user pollution.
    data = payload.model_dump()
    data["user_id"] = user.id
    action = Action(**data)
    db.add(action)
    db.commit()
    db.refresh(action)
    ActionScheduler(db).refresh_completion_metrics(user.id)
    return action


@router.get("", response_model=list[ActionRead])
def list_actions(
    user: CurrentUser,
    goal_id: str | None = None,
    status: str | None = None,
    stage: str | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
    include_deleted: bool = False,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Action]:
    """List the authenticated user's actions, optionally filtered.

    Soft-deleted rows are excluded by default; pass ``include_deleted=true``
    to include them (admin/debug use).
    """
    stmt = select(Action).where(Action.user_id == user.id)
    if not include_deleted:
        stmt = stmt.where(Action.deleted_at.is_(None))
    if goal_id:
        stmt = stmt.where(Action.goal_id == goal_id)
    if status:
        stmt = stmt.where(Action.status == status)
    if stage:
        stmt = stmt.where(Action.stage == stage)
    if due_before:
        stmt = stmt.where(Action.due_at <= due_before)
    if due_after:
        stmt = stmt.where(Action.due_at >= due_after)
    stmt = stmt.order_by(Action.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


# ---------- Static routes (must come before /{action_id}) ----------


@router.get("/today", response_model=list[ActionRead])
def list_today_actions(
    user: CurrentUser,
    goal_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[Action]:
    """List actions due today OR overdue OR daily-recurring.

    Only ``pending`` / ``in_progress`` actions are returned. Sorted by
    ROI descending so the highest-leverage action surfaces first.
    """
    ActionScheduler(db).materialize_for_user(user.id)
    today = date.today()
    stmt = (
        select(Action)
        .where(
            Action.user_id == user.id,
            Action.deleted_at.is_(None),
            Action.status.in_(["pending", "in_progress"]),
            or_(
                Action.due_at == today,
                Action.due_at < today,
                Action.recurrence == "daily",
            ),
        )
        .order_by(Action.created_at.desc())
    )
    if goal_id:
        stmt = stmt.where(Action.goal_id == goal_id)
    actions = list(db.scalars(stmt))
    actions.sort(key=_roi_value, reverse=True)
    return actions


@router.get("/roi", response_model=ActionROISort)
def list_roi_actions(
    user: CurrentUser,
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """List pending/in_progress actions sorted by ROI desc (top N).

    Exposes the engine's ROI sort (P0-线B a3) so the dashboard's
    "highest-leverage actions" panel can render in one call.
    """
    stmt = select(Action).where(
        Action.user_id == user.id,
        Action.deleted_at.is_(None),
        Action.status.in_(["pending", "in_progress"]),
    )
    actions = list(db.scalars(stmt))
    actions.sort(key=_roi_value, reverse=True)
    top = actions[:limit]
    return {"actions": top, "count": len(top)}


@router.get("/calendar.ics", response_class=Response)
def export_action_calendar(
    user: CurrentUser, db: Session = Depends(get_db)
) -> Response:
    """Export scheduled actions as a standards-compatible ICS calendar."""
    ActionScheduler(db).materialize_for_user(user.id)
    return Response(
        ActionScheduler(db).export_ics(user.id),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="lifetree-actions.ics"'},
    )


@router.get("/metrics")
def action_metrics(user: CurrentUser, db: Session = Depends(get_db)) -> dict:
    return ActionScheduler(db).refresh_completion_metrics(user.id)


# ---------- Dynamic-id routes ----------


@router.get("/{action_id}", response_model=ActionRead)
def get_action(
    action_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> Action:
    return _get_owned_action(action_id, user, db)


@router.patch("/{action_id}", response_model=ActionRead)
def update_action(
    action_id: str,
    payload: ActionUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Action:
    action = get_user_action(db, action_id, user.id)
    # Prevent user_id / goal_id reassignment (would break ownership invariants).
    updates = payload.model_dump(exclude_unset=True)
    updates.pop("user_id", None)
    updates.pop("goal_id", None)
    apply_action_updates(db, action, updates)
    db.commit()
    db.refresh(action)
    ActionScheduler(db).refresh_completion_metrics(user.id)
    return action


@router.post("/{action_id}/complete", response_model=ActionRead)
def complete_action(
    action_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> Action:
    """Mark an action completed and write back to its linked Requirement.

    Sets ``status=completed`` and ``completed_at=now`` (ISO string). If
    ``requirement_id`` is set, that Requirement's ``gap_status`` is
    updated to ``"met"`` so the next scenario probability recompute
    reflects the closure.
    """
    action = get_user_action(db, action_id, user.id)
    validate_action_links(
        db,
        user_id=user.id,
        goal_id=action.goal_id,
        scenario_id=action.scenario_id,
        pathway_id=action.pathway_id,
        requirement_id=action.requirement_id,
        risk_factor_id=action.risk_factor_id,
    )
    set_action_status(db, action, "completed")
    db.add(action)
    db.commit()
    db.refresh(action)
    ActionScheduler(db).refresh_completion_metrics(user.id)
    return action


@router.delete("/{action_id}", status_code=204)
def delete_action(
    action_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> None:
    """Soft-delete an action (sets ``deleted_at``; row stays in DB)."""
    action = get_user_action(db, action_id, user.id)
    action.deleted_at = datetime.now(timezone.utc)
    db.add(action)
    db.commit()
