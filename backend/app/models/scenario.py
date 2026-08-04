"""Scenario / branch management models.

A Scenario is a parallel world of assumptions used for "what-if" reasoning.
When conflicting assertions appear, the system spawns a Scenario branch and
runs the reasoning engine independently for each.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.types import JSON_DOCUMENT


class ScenarioStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DORMANT = "dormant"
    MERGED = "merged"
    CLOSED = "closed"


class Scenario(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A scenario branch with independent risk/probability computations."""

    __tablename__ = "scenarios"

    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="CASCADE"), index=True
    )
    pathway_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pathways.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")

    # Branch lineage
    parent_scenario_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )

    # Assumptions encoded as free-form JSONB
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)

    # Computed outputs (cached; refreshed by reasoning engine)
    success_probability: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    key_risk_factors: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    milestones: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)

    # Impact threshold for branch retention (lower = more permissive)
    impact_threshold: Mapped[float] = mapped_column(Float, default=0.05)

    # Last computed
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    meta: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)

    parent: Mapped["Scenario | None"] = relationship(
        remote_side="Scenario.id", back_populates="children"
    )
    children: Mapped[list["Scenario"]] = relationship(back_populates="parent")

    def __repr__(self) -> str:
        return f"<Scenario {self.name}>"


class ScenarioRun(UUIDPkMixin, TimestampMixin, Base):
    """A single execution of the reasoning engine on a scenario.

    Used to track Monte Carlo / Bayesian runs for audit and progress reporting.
    """

    __tablename__ = "scenario_runs"

    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), index=True
    )
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    # 'monte_carlo' | 'bayesian' | 'survival' | 'risk_propagation'

    status: Mapped[str] = mapped_column(String(16), default="pending")
    # 'pending' | 'running' | 'completed' | 'failed'

    iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    result: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_scenario_runs_scenario", ScenarioRun.scenario_id)
