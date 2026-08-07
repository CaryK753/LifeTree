"""Assertion-level conflict-detection StateGraph.

Refactored in §B.2 of the cross-validation spec to unify conflict detection
on ``Assertion`` (deprecated Relationship-level detection). The graph now:

1. ``detect_conflicts_node`` — groups open Assertions by (subject, predicate)
   and flags groups with ≥2 distinct ``object_value``. Temporal validity
   filter: only Assertions where ``valid_to IS NULL OR valid_to > now``.
2. ``classify_impact_node`` — severity from confidence spread + source
   credibility gap; upgrades severity when ≥2 distinct goals are affected
   (via Assertion.scenario_id → Scenario.goal_id).
3. ``auto_merge_node`` — cross-engine consensus voting: when ≥2 distinct
   engines agree on a value and all supporting sources are ≥ medium
   credibility, auto-confirm the winning Assertions and write a
   ``ConflictResolution`` (auto_merged=true). Auto-merged groups exit the
   human-review pipeline.
4. ``trend_analysis_node`` — temporal series analysis per (subject, predicate):
   identifies value-transition points supported by ≥2 engines. When
   ``direction=changing``, marks old-value Assertions ``valid_to`` and
   records a ``TrendAnalysis`` for branch spawning.
5. ``spawn_scenario_branches_node`` — spawns a Scenario branch for
   ``severity ≥ medium`` conflicts or ``direction=changing`` trends.

Graph topology::

    detect_conflicts → classify_impact → auto_merge → trend_analysis
        → (conditional) spawn_branches → finalize
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.event import Assertion, InformationSource
from app.models.intelligence import ConflictResolution
from app.models.scenario import Scenario, ScenarioStatus
from app.services.scenarios import ScenarioService

from .state import ConflictState

log = get_logger(__name__)


# ---------- Constants ----------

# Minimum confidence delta to consider a conflict "material".
CONFLICT_CONFIDENCE_DELTA = 0.3
# Minimum absolute confidence on the lower side to bother branching.
MIN_CONFIDENCE_FOR_BRANCH = 0.25

# Cross-engine consensus thresholds (§A.7 / §B.2).
# Auto-merge requires at least this many *distinct* engines agreeing on a value.
AUTO_MERGE_MIN_ENGINES = 2
# engine_diversity_bonus = 1.0 + 0.2 × distinct_engine_count; must be ≥ this.
AUTO_MERGE_MIN_BONUS = 1.4
# Minimum source credibility to auto-merge without human review.
AUTO_MERGE_MIN_CREDIBILITY = "medium"

# Credibility ranking for comparisons.
_CREDIBILITY_RANK = {"high": 4, "user_marked_reliable": 4, "medium": 3, "low": 2, "pending": 1, "user_marked_questionable": 1}


# ---------- Helpers ----------

def _credibility_rank(value: str | None) -> int:
    return _CREDIBILITY_RANK.get(value or "", 1)


def _is_temporally_valid(a: Assertion, *, now: datetime | None = None) -> bool:
    """An Assertion is temporally valid if valid_to is unset or in the future."""
    if a.valid_to is None:
        return True
    return a.valid_to > (now or datetime.now(timezone.utc))


def _assertion_summary(a: Assertion, source: InformationSource | None) -> dict[str, Any]:
    return {
        "id": a.id,
        "claim": a.claim,
        "object_value": a.object_value,
        "confidence": a.confidence,
        "source_id": a.source_id,
        "source_title": source.title if source else None,
        "source_credibility": source.credibility if source else "pending",
        "source_credibility_score": source.credibility_score if source else 0.5,
        "engine": a.engine,
        "observed_at": a.observed_at.isoformat() if a.observed_at else None,
        "valid_from": a.valid_from.isoformat() if a.valid_from else None,
        "valid_to": a.valid_to.isoformat() if a.valid_to else None,
        "scenario_id": a.scenario_id,
        "source_excerpt": a.source_excerpt,
    }


# ---------- Node implementations ----------

def detect_conflicts_node(state: ConflictState, *, db: Session) -> ConflictState:
    """Find open Assertions on the same (subject, predicate) with different object_value.

    Temporal filter: only Assertions where ``valid_to IS NULL OR valid_to > now``.
    Incremental mode: when ``assertion_ids`` is provided, the scan is scoped to
    the (subject, predicate) pairs of those Assertions (but compares against all
    temporally-valid Assertions for the same user).
    """
    user_id = state.get("user_id")
    assertion_ids = state.get("assertion_ids")

    now = datetime.now(timezone.utc)
    stmt = select(Assertion).where(
        Assertion.status == "open",
        Assertion.user_id == user_id,
    )
    assertions = list(db.scalars(stmt))

    # Temporal validity filter.
    assertions = [a for a in assertions if _is_temporally_valid(a, now=now)]

    if assertion_ids:
        # Incremental mode: only consider (subject, predicate) pairs touched
        # by the newly-persisted Assertions.
        trigger_pairs = {
            (a.subject, a.predicate) for a in assertions if a.id in assertion_ids
        }
        assertions = [a for a in assertions if (a.subject, a.predicate) in trigger_pairs]

    # Preload sources for provenance.
    source_ids = {a.source_id for a in assertions if a.source_id}
    sources_map: dict[str, InformationSource] = {}
    if source_ids:
        for src in db.scalars(select(InformationSource).where(InformationSource.id.in_(source_ids))):
            sources_map[src.id] = src

    # Group by (subject, predicate).
    by_pair: dict[tuple[str, str], list[Assertion]] = defaultdict(list)
    for a in assertions:
        by_pair[(a.subject, a.predicate)].append(a)

    conflict_groups: list[dict[str, Any]] = []
    for (subject, predicate), group in by_pair.items():
        # Distinct object_values — None and "" are treated as the same "no value".
        def _value_key(v: Any) -> str:
            if v is None or v == "":
                return "__none__"
            return str(v)

        values_map: dict[str, list[Assertion]] = defaultdict(list)
        for a in group:
            values_map[_value_key(a.object_value)].append(a)

        if len(values_map) < 2:
            continue  # No conflict — everyone agrees.

        # Build the group.
        assertion_summaries = [_assertion_summary(a, sources_map.get(a.source_id)) for a in group]
        values_summary: list[dict[str, Any]] = []
        for vkey, vassertions in values_map.items():
            engines = sorted({a.engine for a in vassertions if a.engine})
            source_ids_for_value = sorted({a.source_id for a in vassertions if a.source_id})
            credibilities = [
                sources_map[a.source_id].credibility
                for a in vassertions
                if a.source_id and a.source_id in sources_map
            ]
            min_credibility = min(credibilities, key=_credibility_rank) if credibilities else "pending"
            values_summary.append({
                "value": vassertions[0].object_value,
                "assertion_ids": [a.id for a in vassertions],
                "engines": engines,
                "distinct_engine_count": len(engines),
                "source_ids": source_ids_for_value,
                "min_source_credibility": min_credibility,
                "supporting_count": len(vassertions),
            })

        conflict_groups.append({
            "subject": subject,
            "predicate": predicate,
            "assertions": assertion_summaries,
            "values": values_summary,
            "severity": "low",  # filled by classify_impact
            "cross_engine_consensus": None,
            "auto_merged": False,
            "affected_goal_count": 0,
        })

    log.info(
        "conflict.detected",
        count=len(conflict_groups),
        user_id=user_id,
        incremental=bool(assertion_ids),
    )
    return {"conflict_groups": conflict_groups, "auto_merged": [], "trends": [], "spawned_scenarios": [], "skipped": 0}


def classify_impact_node(state: ConflictState, *, db: Session) -> ConflictState:
    """Classify severity per conflict group.

    Heuristic:
    - Base severity from the credibility gap between conflicting values.
    - Upgrade one level if ≥2 distinct goals are affected (via
      Assertion.scenario_id → Scenario.goal_id).
    """
    from app.models.scenario import Scenario  # local import to avoid cycle

    groups = state.get("conflict_groups", [])
    if not groups:
        return {"skipped": 0}

    # Collect all scenario_ids referenced by assertions across groups.
    all_scenario_ids = {
        a["scenario_id"]
        for g in groups
        for a in g["assertions"]
        if a.get("scenario_id")
    }
    scenario_goal_map: dict[str, str] = {}
    if all_scenario_ids:
        for sc in db.scalars(select(Scenario).where(Scenario.id.in_(all_scenario_ids))):
            scenario_goal_map[sc.id] = sc.goal_id

    skipped = 0
    for g in groups:
        # Affected goals for this group.
        goal_ids = {
            scenario_goal_map[a["scenario_id"]]
            for a in g["assertions"]
            if a.get("scenario_id") and a["scenario_id"] in scenario_goal_map
        }
        g["affected_goal_count"] = len(goal_ids)

        # Base severity from source credibility gap.
        scores = [a["source_credibility_score"] for a in g["assertions"]]
        gap = (max(scores) - min(scores)) if scores else 0.0
        if gap > 0.3:
            severity = "high"
        elif gap > 0.1:
            severity = "medium"
        else:
            severity = "low"

        # Confidence spread — material if spread ≥ delta and low side ≥ min.
        confs = [a["confidence"] for a in g["assertions"]]
        spread = (max(confs) - min(confs)) if confs else 0.0
        low_side = min(confs) if confs else 0.0
        if spread >= CONFLICT_CONFIDENCE_DELTA and low_side >= MIN_CONFIDENCE_FOR_BRANCH:
            if severity == "low":
                severity = "medium"

        # Upgrade if ≥2 distinct goals affected.
        if len(goal_ids) >= 2 and severity != "high":
            severity = "high" if severity == "medium" else "medium"

        g["severity"] = severity
        if severity == "low":
            skipped += 1

    return {"conflict_groups": groups, "skipped": skipped}


def auto_merge_node(state: ConflictState, *, db: Session, user_id: str) -> ConflictState:
    """Auto-merge conflict groups via cross-engine consensus voting (§B.2 / §A.7).

    A group is auto-merged when:
    - The winning ``object_value`` is supported by ≥ ``AUTO_MERGE_MIN_ENGINES``
      distinct engines.
    - ``engine_diversity_bonus = 1.0 + 0.2 × distinct_engine_count`` ≥ ``AUTO_MERGE_MIN_BONUS``.
    - All supporting sources for the winning value have credibility ≥ medium.

    On auto-merge:
    - Winning Assertions → ``status='confirmed'``.
    - Losing Assertions → ``conflicting_with_id`` set to the first winning
      Assertion (bidirectional link maintained).
    - A ``ConflictResolution`` row is written with ``auto_merged=true`` and the
      consensus snapshot, so the human-review pipeline skips this group.
    """
    groups = state.get("conflict_groups", [])
    auto_merged: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []

    for g in groups:
        # Find the value with the strongest cross-engine consensus.
        best_value: dict[str, Any] | None = None
        best_engine_count = 0
        for v in g["values"]:
            if v["distinct_engine_count"] > best_engine_count:
                best_engine_count = v["distinct_engine_count"]
                best_value = v

        if best_value is None:
            remaining.append(g)
            continue

        bonus = 1.0 + 0.2 * best_engine_count
        min_credibility = best_value["min_source_credibility"]
        can_auto_merge = (
            best_engine_count >= AUTO_MERGE_MIN_ENGINES
            and bonus >= AUTO_MERGE_MIN_BONUS
            and _credibility_rank(min_credibility) >= _credibility_rank(AUTO_MERGE_MIN_CREDIBILITY)
        )

        if not can_auto_merge:
            remaining.append(g)
            continue

        # Execute auto-merge.
        winning_ids = best_value["assertion_ids"]
        # Recompute losing assertion ids (assertions not in winning value).
        winning_id_set = set(winning_ids)
        losing_assertions = [a for a in g["assertions"] if a["id"] not in winning_id_set]

        # Load ORM rows.
        winning_rows = list(db.scalars(select(Assertion).where(Assertion.id.in_(winning_ids))))
        losing_rows = list(db.scalars(select(Assertion).where(
            Assertion.id.in_([a["id"] for a in losing_assertions])
        )))
        anchor = winning_rows[0] if winning_rows else None

        if anchor is not None:
            for row in winning_rows:
                row.status = "confirmed"
                db.add(row)
            for row in losing_rows:
                row.status = "superseded"
                row.conflicting_with_id = anchor.id
                db.add(row)

        consensus_snapshot = {
            "value": best_value["value"],
            "supporting_engines": best_value["engines"],
            "engine_diversity_bonus": round(bonus, 2),
            "distinct_engine_count": best_engine_count,
            "auto_merged": True,
        }

        # Write ConflictResolution so list_conflicts skips this group.
        resolution_key = f"{g['subject']}:{g['predicate']}:{_value_hash(best_value['value'])}"
        existing = db.scalar(
            select(ConflictResolution).where(
                ConflictResolution.resolution_key == resolution_key,
                ConflictResolution.user_id == user_id,
            )
        )
        if existing is None and anchor is not None:
            winning_source_id = anchor.source_id or ""
            db.add(ConflictResolution(
                resolution_key=resolution_key,
                user_id=user_id,
                subject_id=g["subject"],
                predicate=g["predicate"],
                winning_source_id=winning_source_id,
                winning_object_id=str(best_value["value"]),
                losing_source_ids=sorted({a["source_id"] for a in losing_assertions if a["source_id"]}),
                rationale="auto_merged: cross-engine consensus",
                assertion_ids=[a["id"] for a in g["assertions"]],
                winning_assertion_id=anchor.id,
                cross_engine_consensus=consensus_snapshot,
            ))

        g["auto_merged"] = True
        g["cross_engine_consensus"] = consensus_snapshot
        auto_merged.append({
            "subject": g["subject"],
            "predicate": g["predicate"],
            "winning_value": best_value["value"],
            "engines": best_value["engines"],
            "engine_diversity_bonus": round(bonus, 2),
            "confirmed_assertion_ids": winning_ids,
            "superseded_assertion_ids": [a["id"] for a in losing_assertions],
        })
        log.info(
            "conflict.auto_merged",
            subject=g["subject"],
            predicate=g["predicate"],
            engines=best_value["engines"],
            bonus=round(bonus, 2),
        )

    return {"conflict_groups": remaining, "auto_merged": auto_merged}


def trend_analysis_node(state: ConflictState, *, db: Session, user_id: str) -> ConflictState:
    """Analyse temporal Assertion series for value-transition trends (§A.7).

    For each (subject, predicate) in the remaining conflict groups, examine
    the full temporal sequence (ordered by ``observed_at``). If a value
    transition is observed and the new value is supported by ≥2 distinct
    engines, mark ``direction='changing'`` and set ``valid_to`` on old-value
    Assertions up to the transition point.
    """
    groups = state.get("conflict_groups", [])
    if not groups:
        return {"trends": []}

    # Collect (subject, predicate) pairs to analyse.
    pairs = {(g["subject"], g["predicate"]) for g in groups}

    # Load all temporally-valid open+confirmed assertions for these pairs.
    stmt = select(Assertion).where(
        Assertion.user_id == user_id,
        Assertion.status.in_(["open", "confirmed"]),
    )
    all_assertions = list(db.scalars(stmt))
    by_pair: dict[tuple[str, str], list[Assertion]] = defaultdict(list)
    for a in all_assertions:
        if (a.subject, a.predicate) in pairs:
            by_pair[(a.subject, a.predicate)].append(a)

    trends: list[dict[str, Any]] = []
    for (subject, predicate), seq in by_pair.items():
        if len(seq) < 2:
            continue
        # Order by observed_at.
        seq_sorted = sorted(seq, key=lambda x: x.observed_at or datetime.min.replace(tzinfo=timezone.utc))

        # Need ≥2 distinct time points.
        time_points = {a.observed_at for a in seq_sorted if a.observed_at}
        if len(time_points) < 2:
            continue

        # Identify the early majority value vs later values.
        def _vkey(v: Any) -> str:
            return "__none__" if v is None or v == "" else str(v)

        # Split into early half / late half by median time.
        times = sorted(time_points)
        median_time = times[len(times) // 2]
        early = [a for a in seq_sorted if a.observed_at and a.observed_at <= median_time]
        late = [a for a in seq_sorted if a.observed_at and a.observed_at > median_time]
        if not early or not late:
            continue

        early_values = {_vkey(a.object_value) for a in early}
        late_values = {_vkey(a.object_value) for a in late}

        # Transition detected if early and late have different majority values.
        if early_values == late_values:
            # Stable — no trend to report.
            continue

        # The new value is the one that appears in late but not early (or grows).
        new_values = late_values - early_values
        if not new_values:
            new_values = late_values  # values diverged but no clear "new"

        # Check cross-engine support for the new value in the late period.
        late_new_assertions = [a for a in late if _vkey(a.object_value) in new_values]
        late_new_engines = {a.engine for a in late_new_assertions if a.engine}

        if len(late_new_engines) >= 2:
            direction = "changing"
        elif len(late_new_assertions) >= 2:
            direction = "changing"
        else:
            direction = "divergent"

        transition_point = None
        confidence = 0.5
        if direction == "changing" and late_new_assertions:
            # Transition point = earliest observation of the new value.
            transition_point = min(
                (a.observed_at for a in late_new_assertions if a.observed_at),
                default=None,
            )
            # Confidence scales with engine diversity + observation count.
            confidence = min(0.9, 0.4 + 0.15 * len(late_new_engines) + 0.05 * len(late_new_assertions))

            # Mark old-value Assertions valid_to = transition_point.
            if transition_point is not None:
                old_assertions = [a for a in seq_sorted if _vkey(a.object_value) not in new_values]
                for a in old_assertions:
                    if a.valid_to is None:
                        a.valid_to = transition_point
                        db.add(a)

        timeline = [
            {
                "value": a.object_value,
                "observed_at": a.observed_at.isoformat() if a.observed_at else None,
                "engine": a.engine,
                "assertion_id": a.id,
            }
            for a in seq_sorted
        ]

        trends.append({
            "subject": subject,
            "predicate": predicate,
            "direction": direction,
            "transition_point": transition_point.isoformat() if transition_point else None,
            "confidence": round(confidence, 2),
            "timeline": timeline,
        })
        log.info(
            "conflict.trend_detected",
            subject=subject,
            predicate=predicate,
            direction=direction,
            engines=list(late_new_engines),
        )

    return {"trends": trends}


def spawn_scenario_branches_node(
    state: ConflictState, *, db: Session, goal_id: str | None
) -> ConflictState:
    """Spawn Scenario branches for material conflicts or changing trends.

    Triggered for:
    - Conflict groups with ``severity ≥ medium``.
    - Trends with ``direction='changing'``.

    When ``goal_id`` is None, branch spawning is skipped (no parent scenario
    to branch off), but detection / auto-merge / trend results are still
    returned to the caller.
    """
    if goal_id is None:
        log.debug("conflict.no_goal_id_skip_spawn")
        return {"spawned_scenarios": []}

    service = ScenarioService(db)

    # Find or create the parent (baseline) scenario for this goal.
    parent = db.scalar(
        select(Scenario)
        .where(Scenario.goal_id == goal_id, Scenario.status == ScenarioStatus.ACTIVE.value)
        .order_by(Scenario.created_at.asc())
    )
    if parent is None:
        parent = db.scalar(
            select(Scenario)
            .where(Scenario.goal_id == goal_id)
            .order_by(Scenario.created_at.desc())
        )
    if parent is None:
        log.warning("conflict.no_parent_scenario", goal_id=goal_id)
        return {"spawned_scenarios": []}

    spawned: list[dict[str, Any]] = []

    # Conflict-driven branches.
    for g in state.get("conflict_groups", []):
        if g.get("severity") not in ("medium", "high"):
            continue
        assumptions = {
            "conflict_subject": g["subject"],
            "conflict_predicate": g["predicate"],
            "values": g["values"],
            "severity": g["severity"],
            "spawned_at": datetime.now(timezone.utc).isoformat(),
        }
        branch = service.spawn_branch(
            parent,
            name=f"Conflict: {g['subject'][:60]}",
            assumptions=assumptions,
        )
        spawned.append({
            "scenario_id": branch.id,
            "parent_id": parent.id,
            "subject": g["subject"],
            "kind": "conflict",
        })
        log.info("conflict.scenario_spawned", subject=g["subject"], branch_id=branch.id)

    # Trend-driven branches.
    for t in state.get("trends", []):
        if t["direction"] != "changing":
            continue
        assumptions = {
            "trend_subject": t["subject"],
            "trend_predicate": t["predicate"],
            "transition_point": t["transition_point"],
            "timeline": t["timeline"],
            "spawned_at": datetime.now(timezone.utc).isoformat(),
        }
        branch = service.spawn_branch(
            parent,
            name=f"Trend: {t['subject'][:60]}",
            assumptions=assumptions,
        )
        spawned.append({
            "scenario_id": branch.id,
            "parent_id": parent.id,
            "subject": t["subject"],
            "kind": "trend",
        })
        log.info("conflict.trend_branch_spawned", subject=t["subject"], branch_id=branch.id)

    return {"spawned_scenarios": spawned}


def finalize_node(state: ConflictState) -> ConflictState:
    """Terminal node; commits are handled by the caller's session."""
    return state


# ---------- Edge routing ----------

def _should_spawn(state: ConflictState) -> str:
    """Route after trend_analysis: spawn if any material conflict or changing trend."""
    has_material = any(
        g.get("severity") in ("medium", "high")
        for g in state.get("conflict_groups", [])
    )
    has_changing = any(
        t.get("direction") == "changing"
        for t in state.get("trends", [])
    )
    if has_material or has_changing:
        return "spawn"
    return "skip"


def _value_hash(value: Any) -> str:
    """Stable short hash of an object_value for resolution_key."""
    import hashlib

    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


# ---------- Graph builder ----------

def build_conflict_graph(
    db: Session, *, user_id: str, goal_id: str | None = None
) -> Any:
    """Compile the Assertion-level conflict-detection StateGraph.

    The graph is built per invocation because nodes close over the DB session,
    user_id, and optional goal_id (mirrors the advisor pattern).
    """
    g = StateGraph(ConflictState)

    g.add_node("detect_conflicts", lambda s: detect_conflicts_node(s, db=db))
    g.add_node("classify_impact", lambda s: classify_impact_node(s, db=db))
    g.add_node("auto_merge", lambda s: auto_merge_node(s, db=db, user_id=user_id))
    g.add_node("trend_analysis", lambda s: trend_analysis_node(s, db=db, user_id=user_id))
    g.add_node(
        "spawn_branches",
        lambda s: spawn_scenario_branches_node(s, db=db, goal_id=goal_id),
    )
    g.add_node("finalize", finalize_node)

    g.set_entry_point("detect_conflicts")
    g.add_edge("detect_conflicts", "classify_impact")
    g.add_edge("classify_impact", "auto_merge")
    g.add_edge("auto_merge", "trend_analysis")
    g.add_conditional_edges(
        "trend_analysis",
        _should_spawn,
        {"spawn": "spawn_branches", "skip": "finalize"},
    )
    g.add_edge("spawn_branches", "finalize")
    g.add_edge("finalize", END)

    return g.compile()


def run_conflict_detection(
    db: Session,
    *,
    user_id: str,
    goal_id: str | None = None,
    assertion_ids: list[str] | None = None,
) -> ConflictState:
    """Synchronously run the Assertion-level conflict-detection graph.

    Returns the final state. Called from the structuring pipeline after new
    Assertions are persisted, or from a Celery batch-scan task.
    """
    graph = build_conflict_graph(db, user_id=user_id, goal_id=goal_id)
    initial: ConflictState = {
        "assertion_ids": assertion_ids,
        "user_id": user_id,
        "goal_id": goal_id,
        "conflict_groups": [],
        "auto_merged": [],
        "trends": [],
        "spawned_scenarios": [],
        "skipped": 0,
    }
    final = graph.invoke(initial)
    return final  # type: ignore[return-value]


__all__ = [
    "ConflictState",
    "build_conflict_graph",
    "run_conflict_detection",
    "detect_conflicts_node",
    "classify_impact_node",
    "auto_merge_node",
    "trend_analysis_node",
    "spawn_scenario_branches_node",
    "CONFLICT_CONFIDENCE_DELTA",
    "MIN_CONFIDENCE_FOR_BRANCH",
    "AUTO_MERGE_MIN_ENGINES",
    "AUTO_MERGE_MIN_BONUS",
]
