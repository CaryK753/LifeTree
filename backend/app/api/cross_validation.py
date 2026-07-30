"""Cross-source validation endpoints.

GET  /cross-validation/conflicts  — list conflicting relationships.
POST /cross-validation/resolve    — resolve a conflict by source credibility.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.services.cross_validation import CrossValidationService

router = APIRouter(prefix="/cross-validation", tags=["cross-validation"])


class ResolveBody(BaseModel):
    subject_id: str
    predicate: str
    winning_source_id: str
    rationale: str | None = None


@router.get("/conflicts")
def list_conflicts(
    user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    """List all conflicting relationship groups across sources."""
    svc = CrossValidationService(db, user.id)
    conflicts = svc.list_conflicts()
    return {"conflicts": conflicts, "count": len(conflicts)}


@router.post("/resolve")
def resolve(
    body: ResolveBody, user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    """Resolve a conflict by boosting the winning source's credibility."""
    svc = CrossValidationService(db, user.id)
    return svc.resolve_conflict(
        subject_id=body.subject_id,
        predicate=body.predicate,
        winning_source_id=body.winning_source_id,
        rationale=body.rationale,
    )
