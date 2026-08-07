"""Deep-research service — multi-step retrieval + cross-source synthesis.

Implements §C.2 of the cross-validation / deep-research spec. The research
graph runs as a Celery task (``run_research_job``) and progresses through
six stages:

    planning → searching → extracting → structuring → validating → synthesizing

Each stage updates the persisted ``ResearchJob`` row (status / progress /
current_step) and publishes a progress event to Redis pub/sub so the
frontend ``/research/{job_id}`` page and the chat research-progress card
can render live updates.

Public entry points:
- ``ResearchState`` — TypedDict for the LangGraph state.
- ``build_research_graph(db, job)`` — compile the StateGraph for one job.
- ``run_research(db, job_id)`` — synchronous runner used by the Celery task.
"""

from __future__ import annotations

from app.services.research.graph import build_research_graph, run_research
from app.services.research.state import ResearchState

__all__ = [
    "ResearchState",
    "build_research_graph",
    "run_research",
]
