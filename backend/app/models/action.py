"""Action entity — actionable tasks the reasoning engine recommends and the
user tracks to completion.

Per project plan §11.2 缺口 C: previously the reasoning engine only emitted
a free-text ``optimal_action_sequence`` list that could not be tracked,
rescheduled, or written back into the ontology. This model makes actions
first-class citizens so the dashboard, /actions page, and LangGraph agent
can create / complete / list them, and so completing an action can update
the linked Requirement's gap_status and recompute scenario probability.

Each Action optionally links to:
    - a Requirement (completing it may mark the requirement as met)
    - a RiskFactor (completing it may mitigate the risk)
    - a Scenario (the action belongs to a what-if branch)
    - a Stage (a Pathway milestone grouping)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.types import JSON_DOCUMENT


class ActionStatus(str):
    """Action lifecycle states."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    DEFERRED = "deferred"


class Action(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A user-actionable task derived from the reasoning engine or created
    manually via the agent / UI.

    ROI is computed as ``expected_prob_lift / cost`` (both 0..1) — higher
    ROI = more bang-for-buck and surfaces first in the "highest-leverage
    actions" list.
    """

    __tablename__ = "actions"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE")
    )
    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="CASCADE")
    )

    # Optional ontology links — at least one of these should be set for
    # write-back to flow into the graph on completion.
    scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pathway_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requirement_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True
    )
    risk_factor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("risk_factors.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stage grouping (e.g. "language_prep" / "funds" / "submission") —
    # corresponds to a Pathway milestone; free-form string for flexibility.
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending | in_progress | completed | skipped | deferred

    # Scheduling
    due_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Recurrence: '' (one-off) | 'daily' | 'weekly' | 'monthly'
    recurrence: Mapped[str] = mapped_column(String(16), default="")

    # Generated occurrences point back to the recurring template. The key is
    # deterministic (template id + local due date), making scheduler retries
    # idempotent across Celery workers.
    recurrence_parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("actions.id", ondelete="CASCADE"), nullable=True
    )
    occurrence_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ROI inputs (0..1) — set by the reasoning engine or manually.
    cost: Mapped[float] = mapped_column(Float, default=0.5)
    # Normalized cost: time/money/effort blended per user priority factors.
    expected_prob_lift: Mapped[float] = mapped_column(Float, default=0.0)
    # Expected absolute lift in scenario P(success) if this action completes.
    # roi is derived: expected_prob_lift / max(cost, 0.01)

    # Outcome (filled when status → completed)
    completed_at: Mapped[datetime | None] = mapped_column(String(64), nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_prob_lift: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Source: 'reasoning' (engine-suggested) | 'agent' (chat-derived) | 'manual'
    source: Mapped[str] = mapped_column(String(16), default="manual")
    # Link back to the ScenarioRun that produced this action, if any.
    source_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    meta: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)

    def __repr__(self) -> str:
        return f"<Action {self.title} [{self.status}]>"


Index("ix_actions_user_status", Action.user_id, Action.status)
Index("ix_actions_goal", Action.goal_id)
Index("ix_actions_due", Action.due_at)
Index("ix_actions_scenario", Action.scenario_id)
Index("ix_actions_pathway", Action.pathway_id)
Index("ix_actions_requirement", Action.requirement_id)
Index("ix_actions_risk_factor", Action.risk_factor_id)
Index("ix_actions_stage", Action.stage)
Index("ix_actions_recurrence_parent", Action.recurrence_parent_id)
