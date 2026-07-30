"""Unified Review Inbox for events, discoveries, and source conflicts."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.event import Credibility, Event, InformationSource
from app.models.source_proposal import SourceProposal
from app.services.cross_validation import CrossValidationService
from app.services.risk_proposals import RiskProposalService

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/inbox")
def unified_review_inbox(user: CurrentUser, db: Session = Depends(get_db)) -> dict:
    events = list(
        db.scalars(
            select(Event)
            .where(Event.user_id == user.id, Event.status == "pending_review")
            .order_by(Event.created_at.desc())
            .limit(100)
        )
    )
    sources = list(
        db.scalars(
            select(SourceProposal)
            .where(
                SourceProposal.user_id == user.id,
                SourceProposal.status == "proposed",
            )
            .order_by(SourceProposal.created_at.desc())
            .limit(100)
        )
    )
    pending_source_filters = [
        InformationSource.credibility == Credibility.PENDING.value,
    ]
    if user.role != "admin":
        pending_source_filters.append(
            or_(
                InformationSource.user_id == user.id,
                InformationSource.user_id.is_(None),
            )
        )
    pending_sources = list(
        db.scalars(
            select(InformationSource)
            .where(*pending_source_filters)
            .order_by(InformationSource.created_at.desc())
            .limit(100)
        )
    )
    risk_service = RiskProposalService(db, user.id)
    risks = risk_service.list("proposed")
    conflicts = CrossValidationService(db, user.id).list_conflicts()
    return {
        "counts": {
            "events": len(events),
            "source_proposals": len(sources),
            "pending_sources": len(pending_sources),
            "risk_proposals": len(risks),
            "conflicts": len(conflicts),
        },
        "events": [
            {
                "id": row.id,
                "subject": row.subject,
                "action": row.action,
                "risk_flag_level": row.risk_flag_level,
                "created_at": row.created_at.isoformat(),
            }
            for row in events
        ],
        "source_proposals": [
            {
                "id": row.id,
                "goal_id": row.goal_id,
                "title": row.title,
                "url": row.url,
                "relevance_score": row.relevance_score,
                "credibility_hint": row.credibility_hint,
                "probe_result": row.probe_result,
            }
            for row in sources
        ],
        "pending_sources": [
            {
                "id": row.id,
                "title": row.title,
                "kind": row.kind,
                "url": row.url,
                "publisher": row.publisher,
                "published_at": (row.published_at.isoformat() if row.published_at else None),
                "credibility": row.credibility,
            }
            for row in pending_sources
        ],
        "risk_proposals": [risk_service.serialize(row) for row in risks],
        "conflicts": conflicts,
    }
