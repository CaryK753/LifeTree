"""Cross-source validation: detect and resolve conflicting relationships.

Per P1 feature: finds Relationship rows that share the same (subject, predicate)
but assert different objects from different sources, and lets the user resolve
conflicts by boosting the winning source's credibility and penalizing losers.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.event import InformationSource, Relationship
from app.models.intelligence import ConflictResolution
from app.services.source_reputation import SourceReputationService

log = get_logger(__name__)


class CrossValidationService:
    """Detect conflicting relationships across sources and resolve them."""

    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    # ---------------- Public API ----------------

    def detect_conflicts(self) -> list[dict]:
        """Find relationships with the same (subject, predicate) but different objects."""
        rels = self._owned_relationships()
        if not rels:
            return []
        resolved = {
            (row.subject_id, row.predicate)
            for row in self.db.scalars(
                select(ConflictResolution).where(
                    ConflictResolution.user_id == self.user_id
                )
            )
        }

        # Group by (subject_id, subject_type, type/predicate)
        groups: dict[tuple[str, str, str], list[Relationship]] = defaultdict(list)
        for r in rels:
            if r.type == "conflicts_with":
                continue
            key = (r.subject_id, r.subject_type, r.type)
            groups[key].append(r)

        conflicts: list[dict] = []
        for (subject_id, subject_type, predicate), group_rels in groups.items():
            if (subject_id, predicate) in resolved:
                continue
            # Collect distinct object_ids and their source info
            obj_map: dict[str, list[Relationship]] = defaultdict(list)
            for r in group_rels:
                obj_map[r.object_id].append(r)

            if len(obj_map) <= 1:
                continue

            conflicting_values: list[dict] = []
            scores: list[float] = []
            for obj_id, rels_for_obj in obj_map.items():
                for r in rels_for_obj:
                    src = (
                        self.db.get(InformationSource, r.source_id)
                        if r.source_id
                        else None
                    )
                    score = src.credibility_score if src else 0.5
                    conflicting_values.append(
                        {
                            "object_id": obj_id,
                            "object_type": r.object_type,
                            "source_id": r.source_id,
                            "source_title": src.title if src else None,
                            "source_credibility": score,
                        }
                    )
                    scores.append(score)

            conflicts.append(
                {
                    "subject_id": subject_id,
                    "subject_type": subject_type,
                    "predicate": predicate,
                    "conflicting_values": conflicting_values,
                    "severity": self._severity(scores),
                }
            )

        return conflicts

    def list_conflicts(self) -> list[dict]:
        """Cached listing — currently identical to detect_conflicts."""
        return self.detect_conflicts()

    def resolve_conflict(
        self,
        subject_id: str,
        predicate: str,
        winning_source_id: str,
        rationale: str | None = None,
    ) -> dict:
        """Boost the winning source and penalize losers for a conflict group."""
        rels = self._owned_relationships(
            subject_id=subject_id,
            predicate=predicate,
        )
        if not rels:
            return {"ok": False, "error": "no_relationships_found"}

        winning = [r for r in rels if r.source_id == winning_source_id]

        if not winning:
            return {"ok": False, "error": "winning_source_not_found"}
        winning_object_ids = {r.object_id for r in winning}
        if len(winning_object_ids) != 1:
            return {"ok": False, "error": "winning_source_is_ambiguous"}

        win_obj = winning[0]
        losing = [r for r in rels if r.object_id != win_obj.object_id]
        resolution_key = f"{subject_id}:{predicate}:{winning_source_id}"
        existing_resolution = self.db.scalar(
            select(ConflictResolution).where(
                ConflictResolution.resolution_key == resolution_key
            )
        )
        if existing_resolution is not None:
            return {
                "ok": True,
                "already_resolved": True,
                "subject_id": subject_id,
                "predicate": predicate,
                "winning_source_id": winning_source_id,
                "winning_object_id": win_obj.object_id,
            }

        reputation = SourceReputationService(self.db, self.user_id)
        boosted: list[dict] = []
        winning_source = self.db.get(InformationSource, winning_source_id)
        if winning_source is not None and winning_source.user_id == self.user_id:
            verdict = reputation.record_verdict(
                winning_source,
                evidence_key=f"{resolution_key}:winner",
                confirmed=True,
                meta={"subject_id": subject_id, "predicate": predicate},
            )
            boosted.append(
                {
                    "source_id": winning_source.id,
                    "new_score": verdict.resulting_score,
                }
            )

        # Update each disagreeing source once using a bounded Beta posterior.
        penalized: list[dict] = []
        seen_sources: set[str] = set()
        for r in losing:
            if not r.source_id or r.source_id in seen_sources:
                continue
            seen_sources.add(r.source_id)
            src = self.db.get(InformationSource, r.source_id)
            if src is not None and src.user_id == self.user_id:
                verdict = reputation.record_verdict(
                    src,
                    evidence_key=f"{resolution_key}:loser:{src.id}",
                    confirmed=False,
                    meta={"subject_id": subject_id, "predicate": predicate},
                )
                penalized.append(
                    {"source_id": src.id, "new_score": verdict.resulting_score}
                )

        # Create conflicts_with edges between losing and winning objects
        conflicts_created: list[dict] = []
        seen_objects: set[str] = set()
        for r in losing:
            if r.object_id == win_obj.object_id or r.object_id in seen_objects:
                continue
            seen_objects.add(r.object_id)
            self.db.add(
                Relationship(
                    subject_type=r.object_type,
                    subject_id=r.object_id,
                    object_type=win_obj.object_type,
                    object_id=win_obj.object_id,
                    type="conflicts_with",
                    source_id=winning_source_id,
                    weight=-1.0,
                    confidence=0.8,
                    meta={
                        "resolution_key": resolution_key,
                        "resolved_by_user_id": self.user_id,
                    },
                )
            )
            conflicts_created.append(
                {"from": r.object_id, "to": win_obj.object_id}
            )

        self.db.add(ConflictResolution(
            resolution_key=resolution_key,
            user_id=self.user_id,
            subject_id=subject_id,
            predicate=predicate,
            winning_source_id=winning_source_id,
            winning_object_id=win_obj.object_id,
            losing_source_ids=sorted(seen_sources),
            rationale=rationale,
        ))

        self.db.commit()

        log.info(
            "cross_validation.resolved",
            user_id=self.user_id,
            subject_id=subject_id,
            predicate=predicate,
            winning_source=winning_source_id,
            boosted=len(boosted),
            penalized=len(penalized),
        )

        return {
            "ok": True,
            "subject_id": subject_id,
            "predicate": predicate,
            "winning_source_id": winning_source_id,
            "winning_object_id": win_obj.object_id,
            "boosted_sources": boosted,
            "penalized_sources": penalized,
            "conflicts_created": conflicts_created,
            "resolution_key": resolution_key,
        }

    def _owned_relationships(
        self,
        *,
        subject_id: str | None = None,
        predicate: str | None = None,
    ) -> list[Relationship]:
        """Load only relationships backed by a source owned by this user."""
        stmt = (
            select(Relationship)
            .join(
                InformationSource,
                InformationSource.id == Relationship.source_id,
            )
            .where(InformationSource.user_id == self.user_id)
        )
        if subject_id is not None:
            stmt = stmt.where(Relationship.subject_id == subject_id)
        if predicate is not None:
            stmt = stmt.where(Relationship.type == predicate)
        return list(self.db.scalars(stmt))

    # ---------------- Helpers ----------------

    @staticmethod
    def _severity(scores: list[float]) -> str:
        """Severity based on the credibility gap between conflicting sources."""
        if len(scores) < 2:
            return "low"
        gap = max(scores) - min(scores)
        if gap > 0.3:
            return "high"
        if gap > 0.1:
            return "medium"
        return "low"
