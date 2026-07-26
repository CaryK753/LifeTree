"""Conflict detection & Scenario branching service backed by LangGraph.

Public surface:
- ``run_conflict_detection``: synchronous entrypoint that compiles + invokes
  the StateGraph and returns the final state.
- ``build_conflict_graph``: compile the graph manually (for testing or
  streaming use cases).
- ``ConflictState``: typed state schema.
"""

from .graph import (
    CONFLICT_CONFIDENCE_DELTA,
    MIN_CONFIDENCE_FOR_BRANCH,
    ConflictState,
    build_conflict_graph,
    run_conflict_detection,
)

__all__ = [
    "ConflictState",
    "build_conflict_graph",
    "run_conflict_detection",
    "CONFLICT_CONFIDENCE_DELTA",
    "MIN_CONFIDENCE_FOR_BRANCH",
]
