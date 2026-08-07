"""Assertion-level conflict detection & Scenario branching (LangGraph).

Public surface:
- ``run_conflict_detection``: synchronous entrypoint that compiles + invokes
  the StateGraph and returns the final state.
- ``build_conflict_graph``: compile the graph manually (for testing or
  streaming use cases).
- ``ConflictState`` / ``ConflictGroup`` / ``TrendAnalysis``: typed state schemas.
"""

from .graph import (
    AUTO_MERGE_MIN_BONUS,
    AUTO_MERGE_MIN_ENGINES,
    CONFLICT_CONFIDENCE_DELTA,
    MIN_CONFIDENCE_FOR_BRANCH,
    ConflictState,
    auto_merge_node,
    build_conflict_graph,
    classify_impact_node,
    detect_conflicts_node,
    finalize_node,
    run_conflict_detection,
    spawn_scenario_branches_node,
    trend_analysis_node,
)
from .state import ConflictGroup, TrendAnalysis

__all__ = [
    "ConflictState",
    "ConflictGroup",
    "TrendAnalysis",
    "build_conflict_graph",
    "run_conflict_detection",
    "detect_conflicts_node",
    "classify_impact_node",
    "auto_merge_node",
    "trend_analysis_node",
    "spawn_scenario_branches_node",
    "finalize_node",
    "CONFLICT_CONFIDENCE_DELTA",
    "MIN_CONFIDENCE_FOR_BRANCH",
    "AUTO_MERGE_MIN_ENGINES",
    "AUTO_MERGE_MIN_BONUS",
]
