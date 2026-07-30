"""Persistent records for long-running intelligence feedback loops."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import TimestampMixin, UUIDPkMixin


class CalibrationReport(UUIDPkMixin, TimestampMixin, Base):
    """Versioned calibration and drift result for one model scope."""

    __tablename__ = "calibration_reports"
    __table_args__ = (
        UniqueConstraint(
            "goal_type", "region", "window_end", name="uq_calibration_report_scope_window"
        ),
    )

    goal_type: Mapped[str] = mapped_column(String(64), default="__global__")
    region: Mapped[str] = mapped_column(String(16), default="__global__")
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    brier_score: Mapped[float] = mapped_column(Float, default=0.0)
    previous_brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    drift_score: Mapped[float] = mapped_column(Float, default=0.0)
    drift_detected: Mapped[bool] = mapped_column(default=False)
    calibrated: Mapped[bool] = mapped_column(default=False)
    reliability_curve: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class EvolutionMilestone(UUIDPkMixin, TimestampMixin, Base):
    """Projected scenario event and its eventual real-world comparison."""

    __tablename__ = "evolution_milestones"
    __table_args__ = (
        UniqueConstraint("scenario_id", "projection_key", name="uq_evolution_projection_key"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="CASCADE"), index=True
    )
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), index=True
    )
    projection_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    impact: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="expected")
    expected_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    matched_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    comparison_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class RiskProposal(UUIDPkMixin, TimestampMixin, Base):
    """Persisted emerging-risk proposal shown in the Review Inbox."""

    __tablename__ = "risk_proposals"
    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", name="uq_risk_proposal_user_fingerprint"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="other")
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    urgency: Mapped[str] = mapped_column(String(16), default="normal")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    cluster_size: Mapped[int] = mapped_column(Integer, default=0)
    affected_goals_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    impact_preview: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    adopted_risk_factor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class SourceAccuracyLog(UUIDPkMixin, TimestampMixin, Base):
    """Idempotent evidence used to update a source's Beta reputation."""

    __tablename__ = "source_accuracy_logs"
    __table_args__ = (
        UniqueConstraint("source_id", "evidence_key", name="uq_source_accuracy_evidence"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("information_sources.id", ondelete="CASCADE"), index=True
    )
    evidence_key: Mapped[str] = mapped_column(String(160), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    prior_alpha: Mapped[float] = mapped_column(Float, nullable=False)
    prior_beta: Mapped[float] = mapped_column(Float, nullable=False)
    posterior_alpha: Mapped[float] = mapped_column(Float, nullable=False)
    posterior_beta: Mapped[float] = mapped_column(Float, nullable=False)
    resulting_score: Mapped[float] = mapped_column(Float, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ConflictResolution(UUIDPkMixin, TimestampMixin, Base):
    """Auditable user decision for a cross-source conflict group."""

    __tablename__ = "conflict_resolutions"

    resolution_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    predicate: Mapped[str] = mapped_column(String(32), nullable=False)
    winning_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    winning_object_id: Mapped[str] = mapped_column(String(36), nullable=False)
    losing_source_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)


Index("ix_calibration_reports_scope", CalibrationReport.goal_type, CalibrationReport.region)
Index("ix_evolution_milestones_due", EvolutionMilestone.status, EvolutionMilestone.due_at)
Index("ix_risk_proposals_user_status", RiskProposal.user_id, RiskProposal.status)
