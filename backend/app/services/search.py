"""Global search across the user's ontology.

Per P1 feature: keyword (ilike) and semantic (pgvector) search across
Goals, Pathways, Requirements, Events, InformationSources, and UserMemories.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.event import Event, InformationSource
from app.models.goal import Goal, Pathway, Requirement
from app.models.memory import UserMemory

log = get_logger(__name__)


class SearchService:
    """Keyword + semantic search across all user-scoped entities."""

    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    # ---------------- Keyword search ----------------

    def search(self, query: str, limit: int = 20) -> dict:
        """ILIKE search across Goals, Pathways, Requirements, Events, Sources, Memories."""
        if not query or not query.strip():
            return {"results": [], "total": 0}

        pattern = f"%{query.strip()}%"
        results: list[dict] = []

        # Goals
        for g in self.db.scalars(
            select(Goal)
            .where(
                Goal.user_id == self.user_id,
                or_(Goal.title.ilike(pattern), Goal.description.ilike(pattern)),
            )
            .limit(limit)
        ):
            results.append(
                {
                    "type": "goal",
                    "id": g.id,
                    "title": g.title,
                    "snippet": (g.description or g.title)[:150],
                }
            )

        # Pathways (join Goal for user scope)
        for p in self.db.scalars(
            select(Pathway)
            .join(Goal, Goal.id == Pathway.goal_id)
            .where(
                Goal.user_id == self.user_id,
                or_(Pathway.name.ilike(pattern), Pathway.description.ilike(pattern)),
            )
            .limit(limit)
        ):
            results.append(
                {
                    "type": "pathway",
                    "id": p.id,
                    "title": p.name,
                    "snippet": (p.description or p.name)[:150],
                }
            )

        # Requirements (join Pathway + Goal for user scope)
        for r in self.db.scalars(
            select(Requirement)
            .join(Pathway, Pathway.id == Requirement.pathway_id)
            .join(Goal, Goal.id == Pathway.goal_id)
            .where(
                Goal.user_id == self.user_id,
                or_(
                    Requirement.name.ilike(pattern),
                    Requirement.description.ilike(pattern),
                ),
            )
            .limit(limit)
        ):
            results.append(
                {
                    "type": "requirement",
                    "id": r.id,
                    "title": r.name,
                    "snippet": (r.description or r.name)[:150],
                }
            )

        # Events (include legacy NULL user_id rows)
        for e in self.db.scalars(
            select(Event)
            .where(
                or_(Event.user_id == self.user_id, Event.user_id.is_(None)),
                or_(Event.subject.ilike(pattern), Event.action.ilike(pattern)),
            )
            .limit(limit)
        ):
            results.append(
                {
                    "type": "event",
                    "id": e.id,
                    "title": f"{e.subject} {e.action}",
                    "snippet": (e.object or "")[:150],
                }
            )

        # InformationSources (include legacy NULL user_id rows)
        for s in self.db.scalars(
            select(InformationSource)
            .where(
                or_(
                    InformationSource.user_id == self.user_id,
                    InformationSource.user_id.is_(None),
                ),
                InformationSource.title.ilike(pattern),
            )
            .limit(limit)
        ):
            results.append(
                {
                    "type": "source",
                    "id": s.id,
                    "title": s.title,
                    "snippet": s.title[:150],
                    "url": s.url,
                }
            )

        # UserMemories
        for m in self.db.scalars(
            select(UserMemory)
            .where(
                UserMemory.user_id == self.user_id,
                or_(
                    UserMemory.content.ilike(pattern),
                    UserMemory.category.ilike(pattern),
                ),
            )
            .limit(limit)
        ):
            results.append(
                {
                    "type": "memory",
                    "id": m.id,
                    "title": m.content[:80],
                    "snippet": m.content[:150],
                }
            )

        return {"results": results[:limit], "total": len(results)}

    # ---------------- Semantic search ----------------

    def semantic_search(self, query: str, limit: int = 10) -> list[dict]:
        """pgvector cosine similarity search on event embeddings.

        Falls back to ILIKE if embeddings are unavailable or dimension-mismatched.
        """
        if not query or not query.strip():
            return []

        from app.core.config import get_settings

        # Embed the query
        query_vec: list[float] | None = None
        try:
            from app.llm.embeddings import embed_texts

            embeddings = embed_texts([query])
            if embeddings and embeddings[0]:
                query_vec = embeddings[0]
        except Exception as exc:  # noqa: BLE001
            log.warning("search.embed_failed", error=str(exc))

        if query_vec is None:
            return self._event_ilike_fallback(query, limit)

        if get_settings().lifetree_storage_mode == "local":
            from app.services.runtime.vector_search import search_event_vectors

            results = search_event_vectors(
                self.db,
                user_id=self.user_id,
                query_vector=query_vec,
                limit=limit,
            )
            return results or self._event_ilike_fallback(query, limit)

        # Check dimension compatibility with stored embeddings
        sample = self.db.scalar(
            select(Event).where(Event.embedding.isnot(None)).limit(1)
        )
        if (
            sample is None
            or sample.embedding is None
            or len(sample.embedding) != len(query_vec)
        ):
            log.info("search.semantic_dim_mismatch_fallback_to_ilike")
            return self._event_ilike_fallback(query, limit)

        # Cosine similarity search via pgvector
        try:
            events = list(
                self.db.scalars(
                    select(Event)
                    .where(
                        or_(
                            Event.user_id == self.user_id,
                            Event.user_id.is_(None),
                        ),
                        Event.embedding.isnot(None),
                    )
                    .order_by(Event.embedding.cosine_distance(query_vec))
                    .limit(limit)
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("search.semantic_query_failed", error=str(exc))
            return self._event_ilike_fallback(query, limit)

        return [
            {
                "type": "event",
                "id": e.id,
                "title": f"{e.subject} {e.action}",
                "snippet": (e.object or "")[:150],
            }
            for e in events
        ]

    # ---------------- Helpers ----------------

    def _event_ilike_fallback(self, query: str, limit: int) -> list[dict]:
        pattern = f"%{query.strip()}%"
        events = list(
            self.db.scalars(
                select(Event)
                .where(
                    or_(Event.user_id == self.user_id, Event.user_id.is_(None)),
                    or_(Event.subject.ilike(pattern), Event.action.ilike(pattern)),
                )
                .limit(limit)
            )
        )
        return [
            {
                "type": "event",
                "id": e.id,
                "title": f"{e.subject} {e.action}",
                "snippet": (e.object or "")[:150],
            }
            for e in events
        ]
