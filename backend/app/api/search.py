"""Global search endpoint.

GET /search?q=&limit=20&semantic=false
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.services.search import SearchService

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    user: CurrentUser,
    db: Session = Depends(get_db),
    q: str = Query("", description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    semantic: bool = Query(False, description="Use pgvector semantic search on events"),
) -> dict:
    """Keyword or semantic search across the user's ontology."""
    svc = SearchService(db, user_id=user.id)
    if semantic:
        results = svc.semantic_search(q, limit=limit)
        return {"results": results, "total": len(results), "mode": "semantic"}
    result = svc.search(q, limit=limit)
    result["mode"] = "keyword"
    return result
