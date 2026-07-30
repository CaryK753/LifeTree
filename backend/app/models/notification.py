"""Notification & risk assessment models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import TimestampMixin, UUIDPkMixin

# ---------- Notifications ----------

class NotificationChannel(str, Enum):
    EMAIL = "email"
    IN_APP = "in_app"
    SMS = "sms"
    PUSH = "push"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    READ = "read"


class NotificationLog(UUIDPkMixin, TimestampMixin, Base):
    """Record of each notification attempt to a user."""

    __tablename__ = "notification_logs"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(16), default="in_app")
    status: Mapped[str] = mapped_column(String(16), default="pending")

    severity: Mapped[str] = mapped_column(String(16), default="info")
    # 'info' | 'warning' | 'critical'

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # Reference to triggering event / risk factor
    event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    risk_factor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # Personalized impact summary
    impact_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class WebPushSubscription(UUIDPkMixin, TimestampMixin, Base):
    """Browser push subscription owned by one user and endpoint."""

    __tablename__ = "web_push_subscriptions"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)


# ---------- Risk Assessment ----------

class RiskAssessment(UUIDPkMixin, TimestampMixin, Base):
    """Computed risk score for a (user, goal, scenario) tuple.

    Refreshed by the reasoning engine after each Event insertion or
    Scenario run.
    """

    __tablename__ = "risk_assessments"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="CASCADE"), index=True
    )
    scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # Composite risk score 0..1
    overall_risk: Mapped[float] = mapped_column(Float, default=0.0)

    # Per-factor breakdown
    factor_scores: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # e.g. [{"factor_id": "...", "name": "Policy Shift", "score": 0.62,
    #        "contribution": 0.32}]

    # Survival-style cumulative probability over time
    success_curve: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # e.g. [{"t": "2027-01-01", "p": 0.12}, ...]

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.utcnow()
    )

    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# ---------- Risk Propagation Log ----------

class RiskPropagationLog(UUIDPkMixin, TimestampMixin, Base):
    """Audit log of how a single Event propagated through the graph."""

    __tablename__ = "risk_propagation_logs"

    event_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    goal_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    path: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Sequence of nodes the risk traversed: [{"type": "RiskFactor",
    #   "id": "...", "name": "..."}, ...]

    initial_risk: Mapped[float] = mapped_column(Float, default=0.0)
    final_risk: Mapped[float] = mapped_column(Float, default=0.0)

    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


Index("ix_notifications_user_status", NotificationLog.user_id, NotificationLog.status)
Index("ix_web_push_user_enabled", WebPushSubscription.user_id, WebPushSubscription.enabled)
Index("ix_risk_assessments_user_goal", RiskAssessment.user_id, RiskAssessment.goal_id)
