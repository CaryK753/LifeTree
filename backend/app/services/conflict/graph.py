"""Conflict-detection StateGraph.

Per project plan §4.3: when conflicting assertions or events arise, the
system spawns a Scenario branch with independent assumptions so the
reasoning engine can compute probabilities for each world independently.

Graph topology (linear with a conditional skip):

    detect_conflicts
        │
        ▼
    classify_impact ──(low impact)──▶ finalize
        │
        ▼ (material conflict)
    spawn_scenario_branches
        │
        ▼
    finalize

This is a deliberately simple StateGraph. The value is in the explicit
state schema + the ability to add checkpointing / human-in-the-loop later
without rewriting the orchestration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.event import Assertion
from app.models.scenario import Scenario, ScenarioStatus
from app.services.scenarios import ScenarioService

from .state import ConflictState

log = get_logger(__name__)


# ---------- Constants ----------

# Minimum confidence delta to consider two assertions "conflicting"
CONFLICT_CONFIDENCE_DELTA = 0.3

# Minimum absolute confidence on the lower side to bother branching
MIN_CONFIDENCE_FOR_BRANCH = 0.25


# ---------- Node implementations ----------

def detect_conflicts_node(state: ConflictState, *, db: Session) -> ConflictState:
    """Find all open assertions on the same subject within the goal's scope.

    Two assertions "conflict" if they reference the same ``subject`` but
    make substantively different claims. We use a coarse heuristic here
    (different claim strings on the same subject); an LLM-based semantic
    comparison can be layered on later.
    """
    assertion_id = state.get("assertion_id")
    goal_id = state.get("goal_id")

    if assertion_id:
        trigger = db.get(Assertion, assertion_id)
        if trigger is None:
            return {"conflicts": [], "skipped": 0}
        subjects = {trigger.subject}
    else:
        # Batch mode: scan all open assertions linked to scenarios under goal
        subjects = None

    stmt = select(Assertion).where(Assertion.status == "open")
    if subjects is not None:
        stmt = stmt.where(Assertion.subject.in_(subjects))
    assertions = list(db.scalars(stmt))

    # Group by subject
    by_subject: dict[str, list[Assertion]] = {}
    for a in assertions:
        by_subject.setdefault(a.subject, []).append(a)

    conflicts: list[dict[str, Any]] = []
    for subject, group in by_subject.items():
        # Dedupe claim text; if only one unique claim, no conflict
        unique_claims = {a.claim for a in group}
        if len(unique_claims) < 2:
            continue
        conflicts.append(
            {
                "subject": subject,
                "assertions": [
                    {
                        "id": a.id,
                        "claim": a.claim,
                        "confidence": a.confidence,
                        "source_id": a.source_id,
                    }
                    for a in group
                ],
            }
        )

    log.info("conflict.detected", count=len(conflicts), goal_id=goal_id)
    return {"conflicts": conflicts, "spawned_scenarios": [], "skipped": 0}


def classify_impact_node(state: ConflictState) -> ConflictState:
    """Decide whether each conflict is material enough to branch.

    Heuristic: a conflict is material if the confidence spread between
    the two sides is >= ``CONFLICT_CONFIDENCE_DELTA`` AND the lower side
    is >= ``MIN_CONFIDENCE_FOR_BRANCH``. Low-impact conflicts are skipped
    to avoid branch explosion.
    """
    material: list[dict[str, Any]] = []
    skipped = 0
    for c in state.get("conflicts", []):
        confs = [a["confidence"] for a in c["assertions"]]
        if not confs:
            continue
        spread = max(confs) - min(confs)
        low_side = min(confs)
        if spread >= CONFLICT_CONFIDENCE_DELTA and low_side >= MIN_CONFIDENCE_FOR_BRANCH:
            material.append(c)
        else:
            skipped += 1

    return {"conflicts": material, "skipped": skipped}


def spawn_scenario_branches_node(
    state: ConflictState, *, db: Session, goal_id: str
) -> ConflictState:
    """For each material conflict, spawn a Scenario branch off the parent.

    Uses ``ScenarioService.spawn_branch`` so Neo4j mirroring is consistent.
    """
    service = ScenarioService(db)

    # Find or create the parent (baseline) scenario for this goal
    parent = db.scalar(
        select(Scenario)
        .where(Scenario.goal_id == goal_id, Scenario.status == ScenarioStatus.ACTIVE.value)
        .order_by(Scenario.created_at.asc())
    )
    if parent is None:
        # Fall back to the newest draft
        parent = db.scalar(
            select(Scenario)
            .where(Scenario.goal_id == goal_id)
            .order_by(Scenario.created_at.desc())
        )
    if parent is None:
        log.warning("conflict.no_parent_scenario", goal_id=goal_id)
        return {"spawned_scenarios": []}

    spawned: list[dict[str, Any]] = []
    for c in state.get("conflicts", []):
        assumptions = {
            "conflict_subject": c["subject"],
            "assertions": c["assertions"],
            "spawned_at": datetime.now(timezone.utc).isoformat(),
        }
        branch = service.spawn_branch(
            parent,
            name=f"Conflict: {c['subject'][:60]}",
            assumptions=assumptions,
        )
        spawned.append(
            {
                "scenario_id": branch.id,
                "parent_id": parent.id,
                "subject": c["subject"],
            }
        )
        log.info(
            "conflict.scenario_spawned",
            subject=c["subject"],
            branch_id=branch.id,
            parent_id=parent.id,
        )

    return {"spawned_scenarios": spawned}


def finalize_node(state: ConflictState) -> ConflictState:
    """Terminal node; could record metrics or emit notifications."""
    return state


# ---------- Edge routing ----------

def _should_spawn(state: ConflictState) -> str:
    """Route after classify_impact: spawn if material conflicts exist."""
    if state.get("conflicts"):
        return "spawn"
    return "skip"


# ---------- Graph builder ----------

def build_conflict_graph(
    db: Session, *, goal_id: str
) -> Any:
    """Compile the conflict-detection StateGraph.

    The graph is built per invocation because nodes close over the DB
    session and goal_id (mirrors the advisor pattern).
    """
    g = StateGraph(ConflictState)

    g.add_node("detect_conflicts", lambda s: detect_conflicts_node(s, db=db))
    g.add_node("classify_impact", classify_impact_node)
    g.add_node(
        "spawn_branches",
        lambda s: spawn_scenario_branches_node(s, db=db, goal_id=goal_id),
    )
    g.add_node("finalize", finalize_node)

    g.set_entry_point("detect_conflicts")
    g.add_edge("detect_conflicts", "classify_impact")
    g.add_conditional_edges(
        "classify_impact",
        _should_spawn,
        {"spawn": "spawn_branches", "skip": "finalize"},
    )
    g.add_edge("spawn_branches", "finalize")
    g.add_edge("finalize", END)

    return g.compile()


def run_conflict_detection(
    db: Session,
    *,
    goal_id: str,
    assertion_id: str | None = None,
) -> ConflictState:
    """Synchronously run the conflict-detection graph.

    Returns the final state. Useful from the structuring pipeline after a
    new assertion is persisted, or from a Celery task.
    """
    graph = build_conflict_graph(db, goal_id=goal_id)
    initial: ConflictState = {
        "assertion_id": assertion_id,
        "goal_id": goal_id,
        "conflicts": [],
        "spawned_scenarios": [],
        "skipped": 0,
    }
    final = graph.invoke(initial)
    return final  # type: ignore[return-value]


__all__ = [
    "ConflictState",
    "build_conflict_graph",
    "run_conflict_detection",
    "CONFLICT_CONFIDENCE_DELTA",
    "MIN_CONFIDENCE_FOR_BRANCH",
]
