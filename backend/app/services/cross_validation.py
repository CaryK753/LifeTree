"""Cross-source validation: detect and resolve conflicting Assertions.

Rewritten in §B.2 of the cross-validation spec as a thin LangGraph wrapper.
The old Relationship-level detection is deprecated; conflict detection is
now unified on ``Assertion`` (same subject+predicate, different object_value).

Public API (preserved for backward compat with callers):
- ``detect_conflicts(goal_id=None, assertion_ids=None)`` — runs the full
  LangGraph (detect → classify → auto_merge → trend → spawn). Has side
  effects: auto-confirms consensus Assertions, writes ConflictResolution
  rows, spawns Scenario branches. Use this after new Assertions are
  persisted or from the Celery batch-scan task.
- ``detect_conflicts_for_assertions(assertion_ids)`` — incremental version.
- ``list_conflicts(use_cache=True)`` — read-only listing (no side effects).
  Redis-cached (TTL 5min, key ``lifetree:conflicts:{user_id}``).
- ``resolve_conflict(subject_id, predicate, winning_source_id, rationale)``
  — user裁决: boosts winning source, penalizes losers, writes audit row.
- ``detect_trends(subject=None, predicate=None)`` — temporal trend analysis.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.event import Assertion, InformationSource
from app.models.intelligence import ConflictResolution
from app.services.conflict.graph import (
    classify_impact_node,
    detect_conflicts_node,
    run_conflict_detection,
    trend_analysis_node,
)
from app.services.source_reputation import SourceReputationService

log = get_logger(__name__)

# Redis cache TTL for conflict listings.
_CONFLICTS_CACHE_TTL = 300  # 5 minutes


class CrossValidationService:
    """Detect conflicting Assertions across sources and resolve them.

    Conflict = same (subject, predicate), different object_value, from
    different sources. Resolution boosts the winning source's Beta
    reputation and penalizes losers.
    """

    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id
        self.reputation = SourceReputationService(db, user_id)

    # ---------------- Detection (with side effects) ----------------

    def detect_conflicts(
        self,
        goal_id: str | None = None,
        *,
        assertion_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run the full conflict-detection graph (has side effects).

        Side effects: auto-merge consensus Assertions, write
        ConflictResolution rows, spawn Scenario branches for material
        conflicts / changing trends. Also refreshes the Redis cache.

        Returns the list of conflict groups remaining after auto-merge
        (i.e. those that still need human review).
        """
        state = run_conflict_detection(
            self.db,
            user_id=self.user_id,
            goal_id=goal_id,
            assertion_ids=assertion_ids,
        )
        groups = state.get("conflict_groups", [])
        # Persist results to cache so list_conflicts can read them cheaply.
        self._write_cache(groups)
        return groups

    def detect_conflicts_for_assertions(
        self, assertion_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Incremental detection scoped to newly-persisted Assertions."""
        return self.detect_conflicts(assertion_ids=assertion_ids)

    # ---------------- Listing (read-only, cached) ----------------

    def list_conflicts(self, use_cache: bool = True) -> list[dict[str, Any]]:
        """Read-only listing of conflict groups (no side effects).

        Tries Redis cache first (TTL 5min). On miss, runs the read-only
        detect + classify nodes (no auto_merge / spawn) and caches the
        result.
        """
        if use_cache:
            cached = self._read_cache()
            if cached is not None:
                return cached

        # Read-only query: detect + classify only (these nodes don't write).
        state: dict[str, Any] = {
            "user_id": self.user_id,
            "assertion_ids": None,
            "conflict_groups": [],
            "auto_merged": [],
            "trends": [],
            "spawned_scenarios": [],
            "skipped": 0,
        }
        state.update(detect_conflicts_node(state, db=self.db))
        state.update(classify_impact_node(state, db=self.db))

        # Filter out already-resolved conflict groups.
        groups = state.get("conflict_groups", [])
        if groups:
            resolved_keys = self._resolved_keys()
            groups = [
                g for g in groups
                if f"{g['subject']}:{g['predicate']}" not in resolved_keys
            ]

        if use_cache:
            self._write_cache(groups)
        return groups

    # ---------------- Trend analysis ----------------

    def detect_trends(
        self,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> list[dict[str, Any]]:
        """Analyse temporal Assertion series for value-transition trends.

        If subject+predicate are given, analyses that pair only.
        Otherwise analyses all pairs that currently have conflicts.
        """
        # Build a minimal state for trend_analysis_node.
        if subject and predicate:
            conflict_groups = [{"subject": subject, "predicate": predicate}]
        else:
            # Analyse all pairs with conflicts.
            conflicts = self.list_conflicts(use_cache=True)
            conflict_groups = [
                {"subject": c["subject"], "predicate": c["predicate"]}
                for c in conflicts
            ]

        if not conflict_groups:
            return []

        state: dict[str, Any] = {
            "user_id": self.user_id,
            "conflict_groups": conflict_groups,
            "trends": [],
        }
        result = trend_analysis_node(state, db=self.db, user_id=self.user_id)
        return result.get("trends", [])

    # ---------------- Resolution (user裁决) ----------------

    def resolve_conflict(
        self,
        subject_id: str,
        predicate: str,
        winning_source_id: str,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a conflict group by picking the winning source.

        ``subject_id`` here is the ``Assertion.subject`` string (the
        conflict key, not a UUID). The winning source's Assertions are
        confirmed, losing Assertions are superseded, and Beta reputation
        is updated for all involved sources.

        No longer creates ``Relationship(type='conflicts_with')`` edges
        (deprecated in §B.1 — Assertion.conflicting_with_id is used instead).
        """
        assertions = list(self.db.scalars(
            select(Assertion).where(
                Assertion.user_id == self.user_id,
                Assertion.subject == subject_id,
                Assertion.predicate == predicate,
                Assertion.status.in_(["open", "confirmed"]),
            )
        ))

        if not assertions:
            return {"ok": False, "error": "no_assertions_found"}

        # Group by object_value.
        def _vkey(v: Any) -> str:
            return "__none__" if v is None or v == "" else str(v)

        by_value: dict[str, list[Assertion]] = defaultdict(list)
        for a in assertions:
            by_value[_vkey(a.object_value)].append(a)

        if len(by_value) < 2:
            return {"ok": False, "error": "no_conflict_single_value"}

        # The winning value = the object_value of assertions from the
        # winning source.
        winning_assertions = [a for a in assertions if a.source_id == winning_source_id]
        if not winning_assertions:
            return {"ok": False, "error": "winning_source_not_found"}

        winning_value_key = _vkey(winning_assertions[0].object_value)
        # Validate all winning assertions agree on the value.
        winning_values = {_vkey(a.object_value) for a in winning_assertions}
        if len(winning_values) > 1:
            return {"ok": False, "error": "winning_source_is_ambiguous"}

        anchor = winning_assertions[0]
        winning_ids = {a.id for a in winning_assertions}
        # Only assertions with a *different* object_value are "losing".
        # Supporters (same value, different source) are neither boosted
        # nor penalized — they already agree with the winner.
        winning_value_key = next(iter(winning_values))
        losing_assertions = [
            a for a in assertions
            if a.id not in winning_ids and _vkey(a.object_value) != winning_value_key
        ]

        # Cross-engine consensus snapshot at resolution time.
        winning_engines = sorted({a.engine for a in winning_assertions if a.engine})
        bonus = 1.0 + 0.2 * len(winning_engines)
        consensus_snapshot = {
            "value": anchor.object_value,
            "supporting_engines": winning_engines,
            "engine_diversity_bonus": round(bonus, 2),
            "distinct_engine_count": len(winning_engines),
            "auto_merged": False,
            "user_resolved": True,
        }

        # Check for existing resolution.
        import hashlib
        value_hash = hashlib.sha256(str(anchor.object_value).encode()).hexdigest()[:16]
        resolution_key = f"{subject_id}:{predicate}:{value_hash}"
        existing = self.db.scalar(
            select(ConflictResolution).where(
                ConflictResolution.resolution_key == resolution_key,
                ConflictResolution.user_id == self.user_id,
            )
        )
        if existing is not None:
            return {
                "ok": True,
                "already_resolved": True,
                "subject_id": subject_id,
                "predicate": predicate,
                "winning_source_id": winning_source_id,
                "winning_object_id": str(anchor.object_value),
            }

        # Update Assertion statuses.
        for a in winning_assertions:
            a.status = "confirmed"
            self.db.add(a)
        for a in losing_assertions:
            a.status = "superseded"
            a.conflicting_with_id = anchor.id
            self.db.add(a)

        # Beta reputation: boost winner, penalize losers.
        boosted: list[dict[str, Any]] = []
        winning_source = self.db.get(InformationSource, winning_source_id)
        if winning_source is not None and winning_source.user_id == self.user_id:
            verdict = self.reputation.record_verdict(
                winning_source,
                evidence_key=f"{resolution_key}:winner",
                confirmed=True,
                meta={"subject_id": subject_id, "predicate": predicate},
            )
            boosted.append({
                "source_id": winning_source.id,
                "new_score": verdict.resulting_score,
            })

        penalized: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        for a in losing_assertions:
            if not a.source_id or a.source_id in seen_sources:
                continue
            seen_sources.add(a.source_id)
            src = self.db.get(InformationSource, a.source_id)
            if src is not None and src.user_id == self.user_id:
                verdict = self.reputation.record_verdict(
                    src,
                    evidence_key=f"{resolution_key}:loser:{src.id}",
                    confirmed=False,
                    meta={"subject_id": subject_id, "predicate": predicate},
                )
                penalized.append({
                    "source_id": src.id,
                    "new_score": verdict.resulting_score,
                })

        # Write audit row.
        self.db.add(ConflictResolution(
            resolution_key=resolution_key,
            user_id=self.user_id,
            subject_id=subject_id,
            predicate=predicate,
            winning_source_id=winning_source_id,
            winning_object_id=str(anchor.object_value),
            losing_source_ids=sorted(seen_sources),
            rationale=rationale,
            assertion_ids=[a.id for a in assertions],
            winning_assertion_id=anchor.id,
            cross_engine_consensus=consensus_snapshot,
        ))

        self.db.commit()

        # Invalidate cache.
        self._invalidate_cache()

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
            "winning_object_id": str(anchor.object_value),
            "boosted_sources": boosted,
            "penalized_sources": penalized,
            "resolution_key": resolution_key,
            "cross_engine_consensus": consensus_snapshot,
        }

    # ---------------- Cache helpers ----------------

    def _cache_key(self) -> str:
        return f"lifetree:conflicts:{self.user_id}"

    def _read_cache(self) -> list[dict[str, Any]] | None:
        try:
            from app.db.redis import get_redis

            redis = get_redis()
            raw = redis.get(self._cache_key())
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            log.debug("cross_validation.cache_read_failed", error=str(exc))
            return None

    def _write_cache(self, groups: list[dict[str, Any]]) -> None:
        try:
            from app.db.redis import get_redis

            redis = get_redis()
            redis.setex(self._cache_key(), _CONFLICTS_CACHE_TTL, json.dumps(groups, default=str))
        except Exception as exc:  # noqa: BLE001
            log.debug("cross_validation.cache_write_failed", error=str(exc))

    def _invalidate_cache(self) -> None:
        try:
            from app.db.redis import get_redis

            redis = get_redis()
            redis.delete(self._cache_key())
        except Exception as exc:  # noqa: BLE001
            log.debug("cross_validation.cache_invalidate_failed", error=str(exc))

    # ---------------- Helpers ----------------

    def _resolved_keys(self) -> set[str]:
        """Return ``{subject}:{predicate}`` keys that have a ConflictResolution."""
        rows = self.db.scalars(
            select(ConflictResolution).where(
                ConflictResolution.user_id == self.user_id
            )
        )
        return {f"{r.subject_id}:{r.predicate}" for r in rows}

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
