"""Information lifecycle (half-life / decay) endpoints.

Exposes the decay service so the frontend can:
  - GET /lifecycle/distribution  → fresh/stale/expired/archived counts
  - GET /lifecycle/events        → list events with decay scores (filterable)
  - POST /lifecycle/{id}/refresh → mark as reviewed (resets decay clock)
  - POST /lifecycle/{id}/archive → archive (excludes from active reasoning)
  - PATCH /lifecycle/{id}/half-life → override half-life days
  - POST /lifecycle/sweep        → manually trigger auto-archive sweep

Implements §4.8 of the project plan: knowledge half-life management.

Multi-user isolation: all endpoints resolve the authenticated user via
``CurrentUser`` and filter events by ``user.id``. In single-user mode
``CurrentUser`` falls back to the default user, so behavior is unchanged.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.event import Event
from app.schemas.api import EventRead
from app.services.decay import DecayService

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])

StatusFilter = Literal["fresh", "stale", "expired", "archived"]


class DecayScoreRead(BaseModel):
    event_id: str
    score: float
    age_days: float
    half_life_days: int
    status: str
    last_refreshed_at: str | None = None


class LifecycleEventRead(BaseModel):
    """Event payload augmented with decay metadata for the lifecycle UI."""

    event: EventRead
    decay: DecayScoreRead


class DecayDistributionRead(BaseModel):
    total: int
    fresh: int
    stale: int
    expired: int
    archived: int
    avg_score: float


class HalfLifeUpdate(BaseModel):
    half_life_days: int = Field(
        ...,
        ge=0,
        le=36500,
        description="New half-life in days. Pass 0 to reset to the source-kind default.",
    )


def _check_event_owner(ev: Event, user: CurrentUser) -> None:
    """Raise 403 if the event is not owned by the user (legacy NULL rows OK)."""
    if ev.user_id is not None and ev.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this event")


@router.get("/distribution", response_model=DecayDistributionRead)
def get_distribution(
    user: CurrentUser, db: Session = Depends(get_db)
) -> DecayDistributionRead:
    """Aggregate decay distribution for the user's events."""
    uid = None if user.role == "admin" else user.id
    dist = DecayService(db).distribution(user_id=uid)
    return DecayDistributionRead(**dist.to_dict())


@router.get("/events", response_model=list[LifecycleEventRead])
def list_lifecycle_events(
    user: CurrentUser,
    status: StatusFilter | None = Query(
        None,
        description="Filter by decay status. Omit to list all.",
    ),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[LifecycleEventRead]:
    """List events with their computed decay scores."""
    uid = None if user.role == "admin" else user.id
    rows = DecayService(db).list_events(status=status, limit=limit, user_id=uid)
    out: list[LifecycleEventRead] = []
    for ev, score in rows:
        out.append(
            LifecycleEventRead(
                event=EventRead.model_validate(ev, from_attributes=True),
                decay=DecayScoreRead(**score.to_dict()),
            )
        )
    return out


@router.post("/events/{event_id}/refresh", response_model=LifecycleEventRead)
def refresh_event(
    event_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> LifecycleEventRead:
    """Mark an event as freshly reviewed — resets its decay clock."""
    svc = DecayService(db)
    ev = svc.refresh(event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    _check_event_owner(ev, user)
    score = svc.score_event(ev)
    return LifecycleEventRead(
        event=EventRead.model_validate(ev, from_attributes=True),
        decay=DecayScoreRead(**score.to_dict()),
    )


@router.post("/events/{event_id}/archive", response_model=LifecycleEventRead)
def archive_event(
    event_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> LifecycleEventRead:
    """Archive an event — excludes it from active reasoning/dashboard."""
    svc = DecayService(db)
    ev = svc.archive(event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    _check_event_owner(ev, user)
    score = svc.score_event(ev)
    return LifecycleEventRead(
        event=EventRead.model_validate(ev, from_attributes=True),
        decay=DecayScoreRead(**score.to_dict()),
    )


@router.patch("/events/{event_id}/half-life", response_model=LifecycleEventRead)
def update_half_life(
    event_id: str,
    body: HalfLifeUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> LifecycleEventRead:
    """Override the half-life (days) for a specific event."""
    svc = DecayService(db)
    ev = svc.set_half_life(event_id, body.half_life_days)
    if ev is None:
        raise HTTPException(404, "Event not found")
    _check_event_owner(ev, user)
    score = svc.score_event(ev)
    return LifecycleEventRead(
        event=EventRead.model_validate(ev, from_attributes=True),
        decay=DecayScoreRead(**score.to_dict()),
    )


@router.post("/sweep")
def sweep_expired(user: CurrentUser, db: Session = Depends(get_db)) -> dict:
    """Manually trigger the auto-archive sweep.

    Normally invoked by the daily Celery beat task; exposed here so the
    user can force a cleanup on demand.
    """
    archived = DecayService(db).sweep_expired()
    return {"status": "ok", "archived": archived}
