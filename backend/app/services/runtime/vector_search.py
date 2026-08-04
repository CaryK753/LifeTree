"""Small-dataset cosine search for the local SQLite runtime."""

from __future__ import annotations

import math

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.event import Event


def search_event_vectors(
    db: Session,
    *,
    user_id: str,
    query_vector: list[float],
    limit: int,
) -> list[dict[str, str]]:
    """Rank local event vectors in process; mismatched dimensions are skipped."""
    if not query_vector or limit <= 0:
        return []
    candidates = db.scalars(
        select(Event).where(
            or_(Event.user_id == user_id, Event.user_id.is_(None)),
            Event.embedding.isnot(None),
        )
    )
    scored: list[tuple[float, Event]] = []
    for event in candidates:
        vector = event.embedding or []
        if len(vector) != len(query_vector):
            continue
        similarity = _cosine_similarity(query_vector, vector)
        if similarity is not None:
            scored.append((similarity, event))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "type": "event",
            "id": event.id,
            "title": f"{event.subject} {event.action}",
            "snippet": (event.object or "")[:150],
        }
        for _, event in scored[:limit]
    ]


def _cosine_similarity(left: list[float], right: list[float]) -> float | None:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return None
    return dot / (left_norm * right_norm)


__all__ = ["search_event_vectors"]
