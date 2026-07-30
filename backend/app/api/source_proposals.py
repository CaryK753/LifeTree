"""Source auto-discovery endpoints (P1 信源自动发现).

Lets the authenticated user trigger LLM-driven source proposals for a goal,
list pending proposals, and accept/reject them. Accepting promotes a proposal
to a real ``InformationSource`` with auto-refresh enabled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.goal import Goal, Pathway
from app.models.source_proposal import SourceProposal
from app.services.source_discovery import SourceDiscoveryService

log = get_logger(__name__)
router = APIRouter(prefix="/source-proposals", tags=["source-proposals"])


# ---------- Schemas ----------


class ProposeRequest(BaseModel):
    goal_id: str = Field(..., description="Goal to discover sources for.")
    limit: int = Field(5, ge=1, le=20, description="Max candidates to propose.")


class SourceProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    goal_id: str
    user_id: str
    title: str
    url: str
    kind: str
    publisher: str | None = None
    proposed_reason: str
    relevance_score: float
    credibility_hint: str
    status: str
    probe_result: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime


class InformationSourceRead(BaseModel):
    """Minimal read view for the source created by accept."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    url: str | None = None
    publisher: str | None = None
    credibility: str
    auto_refresh: bool
    refresh_interval_minutes: int
    user_id: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------- Helpers ----------


def _get_owned_goal(goal_id: str, user: CurrentUser, db: Session) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    if goal.user_id != user.id:
        raise HTTPException(403, "You do not have access to this goal")
    return goal


def _get_owned_proposal(proposal_id: str, user: CurrentUser, db: Session) -> SourceProposal:
    proposal = db.get(SourceProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Source proposal not found")
    if proposal.user_id != user.id:
        raise HTTPException(403, "You do not have access to this proposal")
    return proposal


# ---------- Endpoints ----------


@router.post("/propose", response_model=list[SourceProposalRead])
async def propose(
    payload: ProposeRequest, user: CurrentUser, db: Session = Depends(get_db)
) -> list[SourceProposal]:
    """Trigger LLM-driven source discovery for a goal.

    Returns the newly created proposals (status='proposed'). The caller can
    then accept/reject each via the dedicated endpoints.
    """
    goal = _get_owned_goal(payload.goal_id, user, db)
    # Use the user's most recently created pathway (if any) to inform the
    # region hint. The discovery service only needs the region field.
    pathway = db.scalar(
        select(Pathway)
        .where(Pathway.goal_id == goal.id)
        .order_by(Pathway.created_at.desc())
    )
    service = SourceDiscoveryService(db)
    proposals = await service.propose_sources(goal, pathway, limit=payload.limit)
    return proposals


@router.get("", response_model=list[SourceProposalRead])
def list_proposals(
    user: CurrentUser,
    goal_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[SourceProposal]:
    """List the caller's source proposals, optionally filtered."""
    service = SourceDiscoveryService(db)
    return service.list_proposals(
        user_id=None if user.role == "admin" else user.id,
        goal_id=goal_id,
        status=status,
    )


@router.post("/{proposal_id}/accept", response_model=InformationSourceRead)
def accept_proposal(
    proposal_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> Any:
    """Accept a proposal — promotes it to an InformationSource with auto-refresh."""
    proposal = _get_owned_proposal(proposal_id, user, db)
    service = SourceDiscoveryService(db)
    source = service.accept_proposal(proposal.id, user.id)
    return source


@router.post("/{proposal_id}/reject", response_model=SourceProposalRead)
def reject_proposal(
    proposal_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> SourceProposal:
    """Reject a proposal — marks status='rejected', no source is created."""
    proposal = _get_owned_proposal(proposal_id, user, db)
    service = SourceDiscoveryService(db)
    return service.reject_proposal(proposal.id, user.id)
