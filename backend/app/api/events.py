"""Event & InformationSource listing + source credibility endpoints.

Multi-user isolation: all endpoints resolve the authenticated user via
``CurrentUser`` and filter data by ``user.id``. Legacy rows with NULL
``user_id`` (created before this migration) remain visible to all users
via ``user_id IS NULL OR user_id = :uid`` filters. In single-user mode
``CurrentUser`` falls back to the default user, so behavior is unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.event import Event, InformationSource
from app.schemas.api import (
    CredibilityDistribution,
    EventRead,
    InformationSourceRead,
)

router = APIRouter(tags=["events", "sources"])


def _user_scope(user: CurrentUser):
    """Return a filter clause matching rows owned by ``user`` or legacy
    NULL-user rows. Admins see all rows."""
    if user.role == "admin":
        return None  # no filter
    return or_(Event.user_id == user.id, Event.user_id.is_(None))


def _source_scope(user: CurrentUser):
    if user.role == "admin":
        return None
    return or_(InformationSource.user_id == user.id, InformationSource.user_id.is_(None))


# ---------- Events ----------

@router.get("/events", response_model=list[EventRead])
def list_events(
    user: CurrentUser,
    limit: int = 100,
    risk_level: str | None = None,
    db: Session = Depends(get_db),
) -> list[Event]:
    stmt = select(Event)
    scope = _user_scope(user)
    if scope is not None:
        stmt = stmt.where(scope)
    if risk_level:
        stmt = stmt.where(Event.risk_flag_level == risk_level)
    return list(
        db.scalars(stmt.order_by(Event.created_at.desc()).limit(limit))
    )


@router.get("/events/{event_id}", response_model=EventRead)
def get_event(
    event_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> Event:
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    # Enforce ownership: only the owner (or admin) can read. Legacy NULL
    # rows are visible to everyone.
    if ev.user_id is not None and ev.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this event")
    return ev


# ---------- Sources ----------

@router.get("/sources", response_model=list[InformationSourceRead])
def list_sources(
    user: CurrentUser,
    limit: int = 100,
    kind: str | None = None,
    db: Session = Depends(get_db),
) -> list[InformationSource]:
    stmt = select(InformationSource)
    scope = _source_scope(user)
    if scope is not None:
        stmt = stmt.where(scope)
    if kind:
        stmt = stmt.where(InformationSource.kind == kind)
    return list(
        db.scalars(stmt.order_by(InformationSource.created_at.desc()).limit(limit))
    )


@router.get("/sources/credibility", response_model=CredibilityDistribution)
def credibility_distribution(
    user: CurrentUser, db: Session = Depends(get_db)
) -> CredibilityDistribution:
    """Aggregate credibility distribution for the user's sources."""
    scope = _source_scope(user)
    base = select(InformationSource.credibility, func.count())
    if scope is not None:
        base = base.where(scope)
    rows = db.execute(base.group_by(InformationSource.credibility)).all()

    counts = {row[0]: row[1] for row in rows}
    total = sum(counts.values())

    private_stmt = (
        select(func.count())
        .select_from(InformationSource)
        .where(InformationSource.kind == "user_upload")
    )
    if scope is not None:
        private_stmt = private_stmt.where(scope)
    private_count = db.scalar(private_stmt) or 0

    return CredibilityDistribution(
        high=counts.get("high", 0),
        medium=counts.get("medium", 0),
        low=counts.get("low", 0),
        pending=counts.get("pending", 0),
        user_marked_reliable=counts.get("user_marked_reliable", 0),
        user_marked_questionable=counts.get("user_marked_questionable", 0),
        total=total,
        private_share=(private_count / total) if total else 0.0,
    )


@router.patch("/sources/{source_id}/credibility", response_model=InformationSourceRead)
def mark_source_credibility(
    source_id: str,
    user: CurrentUser,
    credibility: str,
    db: Session = Depends(get_db),
) -> InformationSource:
    """User marks a source as reliable or questionable."""
    src = db.get(InformationSource, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    if src.user_id is not None and src.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this source")
    src.credibility = credibility
    if credibility == "user_marked_reliable":
        src.credibility_score = 0.9
    elif credibility == "user_marked_questionable":
        src.credibility_score = 0.2
    db.commit()
    db.refresh(src)
    return src


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(
    source_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> None:
    """Delete a source row.

    Events that reference this source via foreign-key columns are set to NULL
    (the FK is declared with ``ondelete="SET NULL"``), so deleting a source
    never cascades into losing events — only the source record is removed.
    """
    src = db.get(InformationSource, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    if src.user_id is not None and src.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this source")
    db.delete(src)
    db.commit()
