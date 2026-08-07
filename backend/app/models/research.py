"""Deep-research job state machine (§C.1 of the cross-validation spec).

A ``ResearchJob`` represents one user-initiated multi-step research task:
LLM planning → multi-source search → extraction → structuring → cross-
validation → synthesis. It is executed asynchronously by the
``run_research_job`` Celery task (``workers/research_tasks.py``).

Why a dedicated table (vs. reusing ``AdvisorState``):
- ``AdvisorState`` only stores the audit trail of one ReAct loop; research
  needs a first-class state machine with progress / current_step / partial
  results that the user can poll and the LLM can re-enter across turns.
- The final ``report`` is a structured JSON document (summary + key_findings
  + conflicts + trends + sources + research_metadata) consumed by the
  frontend ``/research/{id}`` page and the chat research-progress card.
- Source IDs / Assertion IDs / Conflict IDs are accumulated as the job runs
  so a partial result is still useful when the soft time limit fires.

All collected Assertions are written with ``status='pending_review'`` (or
``scenario_id=<research_branch>``); the research job never promotes
Assertions to ``status='approved'`` on the main graph branch — that path
stays with the Review Inbox.
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


class ResearchStatus(str, Enum):
    """Eight-state machine for ``ResearchJob.status``.

    Transitions are linear except for failure / cancel from any state::

        planning → searching → extracting → structuring → validating
            → synthesizing → completed

        any → failed | cancelled
    """

    PLANNING = "planning"          # LLM is generating the research plan
    SEARCHING = "searching"        # multi-source search in progress
    EXTRACTING = "extracting"      # batch-extracting top-N URL contents
    STRUCTURING = "structuring"    # StructuringService.ingest_text pipeline
    VALIDATING = "validating"      # cross-validation merge of new Assertions
    SYNTHESIZING = "synthesizing"  # LLM final-report synthesis
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchJob(UUIDPkMixin, TimestampMixin, Base):
    """One deep-research task owned by a user.

    The job is created with ``status='planning'`` by the ``start_research``
    Agent tool (or the ``POST /research`` API). The Celery task
    ``run_research_job`` advances it through the state machine. The user
    (or LLM via ``get_research_status``) polls for progress.
    """

    __tablename__ = "research_jobs"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-form scope bag: {goal_id?, pathway_id?, region?, time_range?,
    # max_sub_questions?, max_total_sources?, max_extract_chars?, max_llm_calls?}.
    scope: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    # LLM-generated research plan:
    # {sub_questions: [{q, engines, max_sources, expected_domains}], rationale}.
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    # Engine list the job is allowed to use (subset of configured engines).
    engines: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)

    status: Mapped[str] = mapped_column(String(32), default=ResearchStatus.PLANNING.value)
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    current_step: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Accumulated IDs — appended at each stage so partial results survive
    # a soft-timeout failure.
    source_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    assertion_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    conflict_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)

    # Final synthesis report (see §C.3 of the spec for the schema).
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Soft-fail counter: how many LLM / search calls failed during the run.
    # Used by the synthesizer to caveat the report.
    failure_count: Mapped[int] = mapped_column(Integer, default=0)


Index(
    "ix_research_jobs_user_status",
    ResearchJob.user_id,
    ResearchJob.status,
)
Index("ix_research_jobs_created_at", ResearchJob.created_at)
