"""Event & InformationSource listing + source credibility endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.models.event import Event, InformationSource
from app.schemas.api import (
    CredibilityDistribution,
    EventRead,
    InformationSourceRead,
)

router = APIRouter(tags=["events", "sources"])


# ---------- Events ----------

@router.get("/events", response_model=list[EventRead])
def list_events(
    limit: int = 100,
    risk_level: str | None = None,
    db: Session = Depends(get_db),
) -> list[Event]:
    stmt = select(Event)
    if risk_level:
        stmt = stmt.where(Event.risk_flag_level == risk_level)
    return list(
        db.scalars(stmt.order_by(Event.created_at.desc()).limit(limit))
    )


@router.get("/events/{event_id}", response_model=EventRead)
def get_event(event_id: str, db: Session = Depends(get_db)) -> Event:
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    return ev


# ---------- Sources ----------

@router.get("/sources", response_model=list[InformationSourceRead])
def list_sources(
    limit: int = 100,
    kind: str | None = None,
    db: Session = Depends(get_db),
) -> list[InformationSource]:
    stmt = select(InformationSource)
    if kind:
        stmt = stmt.where(InformationSource.kind == kind)
    return list(
        db.scalars(stmt.order_by(InformationSource.created_at.desc()).limit(limit))
    )


@router.get("/sources/credibility", response_model=CredibilityDistribution)
def credibility_distribution(db: Session = Depends(get_db)) -> CredibilityDistribution:
    """Aggregate credibility distribution across all sources."""
    rows = db.execute(
        select(InformationSource.credibility, func.count()).group_by(
            InformationSource.credibility
        )
    ).all()

    counts = {row[0]: row[1] for row in rows}
    total = sum(counts.values())

    private_count = db.scalar(
        select(func.count())
        .select_from(InformationSource)
        .where(InformationSource.kind == "user_upload")
    ) or 0

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
    credibility: str,
    db: Session = Depends(get_db),
) -> InformationSource:
    """User marks a source as reliable or questionable."""
    src = db.get(InformationSource, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    src.credibility = credibility
    if credibility == "user_marked_reliable":
        src.credibility_score = 0.9
    elif credibility == "user_marked_questionable":
        src.credibility_score = 0.2
    db.commit()
    db.refresh(src)
    return src


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str, db: Session = Depends(get_db)) -> None:
    """Delete a source row.

    Events that reference this source via foreign-key columns are set to NULL
    (the FK is declared with ``ondelete="SET NULL"``), so deleting a source
    never cascades into losing events — only the source record is removed.
    """
    src = db.get(InformationSource, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    db.delete(src)
    db.commit()
