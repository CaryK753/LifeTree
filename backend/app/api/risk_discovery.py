"""Risk area auto-sensing endpoints.

POST /risk-discovery/discover  — scan recent events, cluster, propose risks.
POST /risk-discovery/adopt     — persist a RiskFactor from a proposal.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.services.graph import GraphService
from app.services.risk_adoption import adopt_risk_for_pathway
from app.services.risk_discovery import RiskDiscoveryService
from app.services.risk_proposals import RiskProposalService

router = APIRouter(prefix="/risk-discovery", tags=["risk-discovery"])


class DiscoverBody(BaseModel):
    days: int = Field(14, ge=1, le=365)
    min_cluster_size: int = Field(3, ge=2, le=100)


class AdoptBody(BaseModel):
    proposal_id: str | None = None
    pathway_id: str
    name: str = Field(..., min_length=1, max_length=255)
    type: Literal[
        "policy", "economic", "security", "political", "health", "operational", "other"
    ] = "other"
    region: str | None = Field(None, max_length=64)
    level: Literal["low", "medium", "high"] = "medium"
    urgency: Literal["normal", "elevated", "urgent"] = "normal"
    description: str = Field("", max_length=4000)


@router.post("/discover")
async def discover(
    body: DiscoverBody, user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    """Scan recent events and return emerging-risk proposals."""
    svc = RiskDiscoveryService(db)
    proposals = await svc.discover_emerging_risks(
        user_id=user.id,
        days=body.days,
        min_cluster_size=body.min_cluster_size,
    )
    rows = RiskProposalService(db, user.id).persist(proposals)
    serialized = [RiskProposalService.serialize(row) for row in rows]
    return {"proposals": serialized, "count": len(serialized)}


@router.get("/proposals")
def list_risk_proposals(
    user: CurrentUser,
    status: str | None = "proposed",
    db: Session = Depends(get_db),
) -> dict:
    service = RiskProposalService(db, user.id)
    rows = service.list(status)
    return {"proposals": [service.serialize(row) for row in rows], "count": len(rows)}


@router.post("/proposals/{proposal_id}/reject")
def reject_risk_proposal(
    proposal_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    proposal = RiskProposalService(db, user.id).reject(proposal_id)
    if proposal is None:
        raise HTTPException(404, "Risk proposal not found")
    return RiskProposalService.serialize(proposal)


@router.post("/adopt")
def adopt(
    body: AdoptBody, user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    """Adopt a discovered risk into one of the user's pathways."""
    proposal_service = RiskProposalService(db, user.id)
    if body.proposal_id and proposal_service.get_owned(body.proposal_id) is None:
        raise HTTPException(404, "Risk proposal not found")
    result = adopt_risk_for_pathway(
        db,
        user_id=user.id,
        pathway_id=body.pathway_id,
        name=body.name,
        risk_type=body.type,
        region=body.region,
        values={
            "level": body.level,
            "urgency": body.urgency,
            "description": body.description,
        },
    )
    rf = result.risk_factor
    GraphService().upsert_risk_factor(rf)
    if body.proposal_id:
        proposal_service.mark_adopted(body.proposal_id, rf.id)
    return {
        "ok": True,
        "risk_factor_id": rf.id,
        "name": rf.name,
        "level": rf.level,
        "type": rf.type,
        "created": result.created,
        "linked": result.linked,
    }
