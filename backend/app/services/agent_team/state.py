"""Typed state for the AgentTeam StateGraph (§D.5 of the spec).

The graph runs as a Celery task and threads mutable state through these
fields. ``AgentTeamJob`` rows in the DB are the persistent mirror: each
node updates the row before yielding back to the graph so a soft-timeout
failure still leaves partial results in the DB.

Reducer notes:
- ``specialist_results`` uses ``operator.add`` so the Send-API fan-out
  (dispatch → N parallel specialists → aggregate) accumulates each
  specialist's result into the list rather than overwriting it.
- ``review_gaps`` uses the same reducer so a review round can append
  newly-discovered gaps to the previous round's.
- ``llm_calls`` / ``failure_count`` / ``iteration`` use ``add`` so
  parallel specialists can increment them without clobbering each other.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class SubtaskSpec(TypedDict, total=False):
    """One slice of the main agent's decomposition."""

    subtask_id: str             # stable id for matching results
    role: str                   # ResearchSpecialist / ValidationSpecialist / ...
    instruction: str            # what the sub-agent should do
    engine: str | None          # bound search engine (None = any)
    domain: str | None          # bound domain for AnySearch
    budget: int                 # max_tool_calls for this sub-agent


class SpecialistResult(TypedDict, total=False):
    """Structured result returned by one sub-agent."""

    subtask_id: str
    role: str
    status: str                 # "completed" | "failed" | "budget_exceeded"
    output: str                 # the sub-agent's textual answer
    atoms: dict[str, Any]       # structured atoms extracted (events/assertions/...)
    sources: list[dict[str, Any]]  # sources the sub-agent cited
    llm_calls: int
    tool_calls: int
    error: str | None


class ReviewGap(TypedDict, total=False):
    """A coverage gap identified by the review node."""

    domain: str                 # e.g. "policy" / "academic" / "chinese_news"
    reason: str                 # why this gap matters
    suggested_role: str         # role to dispatch for the next round


class TeamState(TypedDict, total=False):
    """LangGraph state schema for the AgentTeam pipeline.

    Input:
    - ``job_id``: the AgentTeamJob ID.
    - ``objective``: the user's objective.
    - ``scope``: free-form dict (goal_id / engines / domains / budget overrides).
    - ``template``: team template identifier (see TEAM_TEMPLATES).

    Output:
    - ``subtasks``: the main agent's decomposition.
    - ``specialist_results``: each specialist's structured result.
    - ``aggregated``: the main agent's merged intermediate output.
    - ``review_gaps``: coverage gaps found during review.
    - ``final_output``: the final output dict.
    - ``error``: populated when a node fails fatally.
    """

    # Input
    job_id: str
    user_id: str
    objective: str
    scope: dict[str, Any]
    template: str

    # Budget (resolved from scope + global defaults)
    max_specialists: int
    max_iterations: int
    max_llm_calls: int
    max_tool_calls_per_specialist: int

    # Running counters (``add`` reducer: parallel specialists can increment)
    llm_calls: Annotated[int, operator.add]
    failure_count: Annotated[int, operator.add]
    iteration: int

    # Intermediate / output
    subtasks: list[SubtaskSpec]
    # ``add`` reducer: each parallel specialist appends its result.
    specialist_results: Annotated[list[SpecialistResult], operator.add]
    aggregated: dict[str, Any]
    # ``add`` reducer: review rounds append gaps.
    review_gaps: Annotated[list[ReviewGap], operator.add]
    final_output: dict[str, Any]
    error: str | None
