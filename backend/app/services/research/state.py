"""Typed state for the research StateGraph (§C.2 of the spec).

The graph runs as a Celery task and threads mutable state through these
fields. ``ResearchJob`` rows in the DB are the persistent mirror: each
node updates the row before yielding back to the graph so a soft-timeout
failure still leaves partial results in the DB.
"""

from __future__ import annotations

from typing import Any, TypedDict


class SubQuestionPlan(TypedDict, total=False):
    """One slice of the LLM-generated research plan."""

    q: str                       # the sub-question text
    engines: list[str]           # engines to query for this sub-question
    max_sources: int             # cap on URLs to collect
    expected_domains: list[str]  # hint for the domain router (AnySearch)


class ResearchPlan(TypedDict, total=False):
    """LLM-generated plan persisted to ``ResearchJob.plan``."""

    sub_questions: list[SubQuestionPlan]
    rationale: str
    expected_domains: list[str]  # union of all sub-question domains


class CollectedSource(TypedDict, total=False):
    """A search hit that has been promoted to a tracked source."""

    url: str
    title: str
    snippet: str
    score: float
    engine: str
    published_at: str | None
    sub_question: str  # which sub-question surfaced this source
    source_id: str | None  # InformationSource.id once persisted
    extracted: bool
    extract_chars: int


class StructuredAtoms(TypedDict, total=False):
    """Atoms produced by StructuringService.ingest_text, grouped for reporting."""

    events: list[dict[str, Any]]
    assertions: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    metrics: list[dict[str, Any]]


class ResearchState(TypedDict, total=False):
    """LangGraph state schema for the research pipeline.

    Input:
    - ``job_id``: the ResearchJob ID.
    - ``question``: the user's research question.
    - ``scope``: free-form dict (goal_id / pathway_id / region / time_range /
      budget overrides).
    - ``engines``: allowed engines (subset of configured engines).

    Output:
    - ``plan``: the LLM-generated research plan.
    - ``collected_sources``: all sources gathered across sub-questions.
    - ``extracted_pages``: full-page content for top-N sources.
    - ``structured_atoms``: atoms produced by StructuringService.
    - ``conflict_groups``: conflicts detected among new Assertions.
    - ``trends``: temporal trends among new Assertions.
    - ``report``: the final synthesis report.
    - ``error``: populated when a node fails fatally.
    """

    # Input
    job_id: str
    user_id: str
    question: str
    scope: dict[str, Any]
    engines: list[str]

    # Budget (resolved from scope + global defaults)
    max_sub_questions: int
    max_total_sources: int
    max_extract_chars: int
    max_llm_calls: int

    # Running counters
    llm_calls: int
    failure_count: int

    # Intermediate / output
    plan: ResearchPlan
    collected_sources: list[CollectedSource]
    extracted_pages: list[dict[str, Any]]
    structured_atoms: StructuredAtoms
    conflict_groups: list[dict[str, Any]]
    trends: list[dict[str, Any]]
    report: dict[str, Any]
    error: str | None
