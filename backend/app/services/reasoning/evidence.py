"""Build ontology evidence paths that can participate in decision reasoning."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.event import InformationSource, Relationship


@dataclass(slots=True)
class EvidenceBundle:
    scores: dict[str, float]
    paths_by_factor: dict[str, list[dict[str, Any]]]

    @property
    def summary(self) -> dict[str, Any]:
        values = list(self.scores.values())
        return {
            "factors_with_evidence": len(values),
            "path_count": sum(len(paths) for paths in self.paths_by_factor.values()),
            "mean_quality": sum(values) / len(values) if values else 0.0,
        }


def build_decision_evidence(db: Session, factor_ids: set[str]) -> EvidenceBundle:
    if not factor_ids:
        return EvidenceBundle(scores={}, paths_by_factor={})

    relationships = list(
        db.scalars(
            select(Relationship).where(
                or_(
                    Relationship.subject_id.in_(factor_ids),
                    Relationship.object_id.in_(factor_ids),
                )
            )
        )
    )
    source_ids = {rel.source_id for rel in relationships if rel.source_id}
    sources = {
        source.id: source
        for source in db.scalars(
            select(InformationSource).where(InformationSource.id.in_(source_ids))
        )
    } if source_ids else {}

    paths: dict[str, list[dict[str, Any]]] = {factor_id: [] for factor_id in factor_ids}
    for rel in relationships:
        factor_id = rel.subject_id if rel.subject_id in factor_ids else rel.object_id
        source = sources.get(rel.source_id or "")
        quality = _evidence_quality(rel, source)
        paths[factor_id].append(
            {
                "source_id": source.id if source else None,
                "source_title": source.title if source else None,
                "source_url": source.url if source else None,
                "from": {"type": rel.subject_type, "id": rel.subject_id},
                "relationship": rel.type,
                "to": {"type": rel.object_type, "id": rel.object_id},
                "weight": float(rel.weight or 0.0),
                "confidence": float(rel.confidence or 0.0),
                "evidence_quality": quality,
            }
        )

    scores = {
        factor_id: max((path["evidence_quality"] for path in factor_paths), default=0.0)
        for factor_id, factor_paths in paths.items()
        if factor_paths
    }
    return EvidenceBundle(scores=scores, paths_by_factor=paths)


def _evidence_quality(
    relationship: Relationship,
    source: InformationSource | None,
) -> float:
    confidence = max(0.0, min(1.0, float(relationship.confidence or 0.0)))
    credibility = max(0.0, min(1.0, float(source.credibility_score or 0.5))) if source else 0.35
    timestamp = (source.published_at or source.updated_at) if source else None
    freshness = 0.6
    if timestamp:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds() / 86400)
        freshness = 0.35 + 0.65 * math.exp(-age_days / 730.0)
    return round(confidence * (0.35 + 0.65 * credibility) * freshness, 4)
