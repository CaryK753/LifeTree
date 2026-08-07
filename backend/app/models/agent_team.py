"""AgentTeam job state machine (§D.2 of the cross-validation spec).

An ``AgentTeamJob`` represents one user-initiated multi-agent collaboration
task: the main agent (Orchestrator) decomposes the objective into subtasks,
dispatches them to specialist sub-agents (each with an independent context
and a pruned toolset), aggregates the results, optionally reviews for gaps
and dispatches another round (≤ 2 iterations), then produces a final output.

The job is executed asynchronously by the ``run_agent_team`` Celery task
(``workers/agent_team_tasks.py``).

Why a dedicated table (vs. reusing ``ResearchJob``):
- AgentTeam is a more general orchestration layer than deep research.
  ``ResearchJob`` runs a fixed 6-stage pipeline; AgentTeam's shape depends
  on the team template (fan-out / fan-in / iterative), so the state machine
  is different.
- Sub-agent results are accumulated as a list of structured dicts (one per
  specialist), not as flat ID lists like ResearchJob.
- The ``template`` field drives the orchestrator's behavior and the
  frontend's rendering (different templates produce different output
  shapes: research report / validation verdict / pathway comparison table /
  risk inventory).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import TimestampMixin, UUIDPkMixin
from app.models.types import JSON_DOCUMENT


class TeamStatus(str, Enum):
    """Seven-state machine for ``AgentTeamJob.status``.

    Transitions::

        decomposing → dispatching → running → aggregating → reviewing
            → (back to dispatching if gaps found, ≤ 2 iterations)
            → completed

        any → failed | cancelled
    """

    DECOMPOSING = "decomposing"    # main agent is splitting objective into subtasks
    DISPATCHING = "dispatching"    # main agent is assigning sub-agents
    RUNNING = "running"            # sub-agents are executing in parallel
    AGGREGATING = "aggregating"    # main agent is merging sub-agent results
    REVIEWING = "reviewing"        # main agent is checking for coverage gaps
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid team template identifiers. The orchestrator only allows these —
# arbitrary templates are rejected at the API/tool layer. See §D.4.
TEAM_TEMPLATES = (
    "cross_domain_research",   # N×ResearchSpecialist + SynthesisSpecialist
    "independent_validation",  # N×ValidationSpecialist + SynthesisSpecialist
    "multi_pathway_compare",   # N×ScenarioExplorer + SynthesisSpecialist
    "risk_scan",               # N×DomainAnalyst
    "iterative_research",      # ResearchSpecialist + SynthesisSpecialist (≤2 rounds)
)


class AgentTeamJob(UUIDPkMixin, TimestampMixin, Base):
    """One AgentTeam task owned by a user.

    Created with ``status='decomposing'`` by the ``start_team`` Agent tool
    (or the ``POST /agent-team`` API). The Celery task ``run_agent_team``
    advances it through the state machine. The user (or LLM via
    ``get_team_status``) polls for progress.
    """

    __tablename__ = "agent_team_jobs"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-form scope bag: {goal_id?, engines?, domains?, subquestions?,
    # max_specialists?, max_iterations?, max_llm_calls?}.
    scope: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    # Main-agent decomposition: [{role, instruction, engine?, domain?,
    # budget, subtask_id}].
    subtasks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list
    )
    # Each specialist's structured result:
    # [{subtask_id, role, output, atoms, sources, status, error?, llm_calls}].
    specialist_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list
    )

    status: Mapped[str] = mapped_column(
        String(32), default=TeamStatus.DECOMPOSING.value
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    current_step: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Aggregated output before final synthesis (main agent's merge).
    aggregated: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_DOCUMENT, nullable=True
    )
    # Coverage gaps found during review (drives iterative dispatch).
    review_gaps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list
    )
    iterations: Mapped[int] = mapped_column(Integer, default=0)  # fan-out rounds

    # Final output (shape depends on template — see §D.4 / D.9).
    final_output: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_DOCUMENT, nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Soft-fail counter: how many sub-agent / LLM calls failed.
    failure_count: Mapped[int] = mapped_column(Integer, default=0)


Index(
    "ix_agent_team_jobs_user_status",
    AgentTeamJob.user_id,
    AgentTeamJob.status,
)
Index("ix_agent_team_jobs_created_at", AgentTeamJob.created_at)
