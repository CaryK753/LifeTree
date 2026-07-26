"""Typed state for the conflict-detection StateGraph.

The graph runs after each new Assertion (or batch of Events) is persisted.
It detects conflicting claims on the same subject, decides whether to
spawn a Scenario branch, and (if so) seeds the branch's assumptions.
"""

from __future__ import annotations

from typing import Any, TypedDict


class ConflictState(TypedDict, total=False):
    """State schema for the conflict-detection graph.

    Input:
    - ``assertion_id``: the triggering assertion (optional; can also run
      on a batch via ``subject_filter``).
    - ``goal_id``: scope the detection to a goal.

    Output:
    - ``conflicts``: list of detected conflict groups, each with the
      ``subject`` and the list of conflicting ``assertion_id``s.
    - ``spawned_scenarios``: list of newly-created Scenario IDs branched
      off the parent for each conflict group.
    - ``skipped``: count of low-impact conflicts that didn't warrant a
      new branch.
    """

    assertion_id: str | None
    goal_id: str
    conflicts: list[dict[str, Any]]
    spawned_scenarios: list[dict[str, Any]]
    skipped: int
