"""Built-in advisor tools for reading and updating the action calendar."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.exceptions import LifeTreeError
from app.db.postgres import SessionLocal
from app.models.action import Action
from app.services.action_integrity import set_action_status, validate_action_links


class ListActionCalendarInput(BaseModel):
    start_date: str | None = Field(None, description="Start date (YYYY-MM-DD); defaults to today")
    end_date: str | None = Field(
        None, description="End date (YYYY-MM-DD); defaults to 30 days after start"
    )
    goal_id: str | None = Field(None, description="Optional goal filter")
    include_completed: bool = Field(False, description="Include completed/skipped actions")


class UpdateActionCalendarInput(BaseModel):
    action_id: str = Field(..., description="Action ID to update")
    due_at: str | None = Field(None, description="New due date (YYYY-MM-DD)")
    clear_due_date: bool = Field(False, description="Remove the action from its scheduled date")
    recurrence: Literal["", "daily", "weekly", "monthly"] | None = None
    status: Literal[
        "pending", "in_progress", "completed", "skipped", "deferred"
    ] | None = None


def _parse_date(value: str | None, fallback: date) -> date:
    if value is None:
        return fallback
    return date.fromisoformat(value)


def _serialize_action(action: Action) -> dict[str, Any]:
    return {
        "id": action.id,
        "goal_id": action.goal_id,
        "title": action.title,
        "due_at": action.due_at.isoformat() if action.due_at else None,
        "recurrence": action.recurrence,
        "status": action.status,
        "stage": action.stage,
    }


def build_action_calendar_tools(
    *, user_id: str, goal_id_context: str | None
) -> list[StructuredTool]:
    @tool("list_action_calendar", args_schema=ListActionCalendarInput)
    def list_action_calendar(
        start_date: str | None = None,
        end_date: str | None = None,
        goal_id: str | None = None,
        include_completed: bool = False,
    ) -> dict[str, Any]:
        """List scheduled actions in a date range, ordered like a calendar."""
        try:
            start = _parse_date(start_date, date.today())
            end = _parse_date(end_date, start + timedelta(days=30))
        except ValueError:
            return {"error": "invalid_date", "detail": "dates must be YYYY-MM-DD"}
        if end < start:
            return {"error": "invalid_range", "detail": "end_date must not precede start_date"}

        with SessionLocal() as session:
            stmt = select(Action).where(
                Action.user_id == user_id,
                Action.deleted_at.is_(None),
                Action.due_at >= start,
                Action.due_at <= end,
            )
            effective_goal_id = goal_id or goal_id_context
            if effective_goal_id:
                stmt = stmt.where(Action.goal_id == effective_goal_id)
            if not include_completed:
                stmt = stmt.where(Action.status.in_(["pending", "in_progress", "deferred"]))
            actions = list(session.scalars(stmt.order_by(Action.due_at, Action.created_at)))
            return {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "actions": [_serialize_action(action) for action in actions],
                "count": len(actions),
            }

    @tool("update_action_calendar", args_schema=UpdateActionCalendarInput)
    def update_action_calendar(
        action_id: str,
        due_at: str | None = None,
        clear_due_date: bool = False,
        recurrence: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Reschedule an action and optionally update recurrence or status."""
        with SessionLocal() as session:
            action = session.get(Action, action_id)
            if action is None:
                return {"error": "action_not_found", "action_id": action_id}
            if action.user_id != user_id:
                return {"error": "forbidden", "action_id": action_id}
            if clear_due_date:
                action.due_at = None
            elif due_at is not None:
                try:
                    action.due_at = date.fromisoformat(due_at)
                except ValueError:
                    return {"error": "invalid_date", "detail": "due_at must be YYYY-MM-DD"}
            if recurrence is not None:
                action.recurrence = recurrence
            if status is not None:
                try:
                    validate_action_links(
                        session,
                        user_id=user_id,
                        goal_id=action.goal_id,
                        scenario_id=action.scenario_id,
                        pathway_id=action.pathway_id,
                        requirement_id=action.requirement_id,
                        risk_factor_id=action.risk_factor_id,
                    )
                    set_action_status(session, action, status)
                except LifeTreeError as exc:
                    return {"error": exc.code, "detail": exc.message}
            session.commit()
            session.refresh(action)
            return _serialize_action(action)

    return [list_action_calendar, update_action_calendar]


__all__ = ["build_action_calendar_tools"]
