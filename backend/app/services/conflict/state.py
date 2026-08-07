"""Typed state for the conflict-detection StateGraph.

Extended in §B.2 of the cross-validation spec to carry Assertion-level
conflict groups, cross-engine consensus metadata, trend analysis output,
and auto-merge results.

The graph runs after each new Assertion (or batch) is persisted. It detects
conflicting claims on the same (subject, predicate) with different
``object_value``, classifies impact, auto-merges multi-source consistent
facts via cross-engine voting, analyses temporal trends, and (if material)
spawns a Scenario branch.
"""

from __future__ import annotations

from typing import Any, TypedDict


class ConflictGroup(TypedDict, total=False):
    """A single conflict group: same subject+predicate, different object_value."""

    subject: str
    predicate: str
    # All participating assertions, each carrying provenance for voting.
    assertions: list[dict[str, Any]]
    # Distinct object_values and the engines/sources supporting each.
    values: list[dict[str, Any]]
    severity: str  # "low" | "medium" | "high"
    # Cross-engine consensus for the winning value (filled by auto_merge).
    cross_engine_consensus: dict[str, Any] | None
    auto_merged: bool
    affected_goal_count: int


class TrendAnalysis(TypedDict, total=False):
    """Trend reasoning output for one (subject, predicate) temporal series."""

    subject: str
    predicate: str
    direction: str  # "stable" | "changing" | "divergent"
    transition_point: str | None  # ISO 8601
    confidence: float
    timeline: list[dict[str, Any]]


class ConflictState(TypedDict, total=False):
    """State schema for the conflict-detection graph.

    Input:
    - ``assertion_ids``: newly-persisted Assertion IDs to scope the scan
      (incremental mode). When empty/None, runs a full scan for the user.
    - ``user_id``: the owning user (required — assertions are tenant-scoped).
    - ``goal_id``: optional goal scope (used to find parent scenario for
      branch spawning).

    Output:
    - ``conflict_groups``: detected conflict groups (Assertion-level).
    - ``auto_merged``: groups that were auto-confirmed via cross-engine
      consensus voting.
    - ``trends``: trend analyses for temporal assertion series.
    - ``spawned_scenarios``: newly-created Scenario branch IDs.
    - ``skipped``: count of low-impact conflicts that didn't warrant a branch.
    """

    # Input
    assertion_ids: list[str] | None
    user_id: str
    goal_id: str | None

    # Intermediate / output
    conflict_groups: list[ConflictGroup]
    auto_merged: list[dict[str, Any]]
    trends: list[TrendAnalysis]
    spawned_scenarios: list[dict[str, Any]]
    skipped: int
