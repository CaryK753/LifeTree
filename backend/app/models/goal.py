"""Goal / Pathway / Requirement / RiskFactor models — the heart of the ontology."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPkMixin


# ---------- Enums ----------

class GoalStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"


class PathwayStatus(str, Enum):
    CANDIDATE = "candidate"
    SELECTED = "selected"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class RequirementType(str, Enum):
    LANGUAGE = "language"
    FINANCIAL = "financial"
    EDUCATION = "education"
    EXPERIENCE = "experience"
    HEALTH = "health"
    LEGAL = "legal"
    OTHER = "other"


class RiskFactorType(str, Enum):
    POLICY = "policy"
    ECONOMIC = "economic"
    SECURITY = "security"
    POLITICAL = "political"
    HEALTH = "health"
    OPERATIONAL = "operational"
    OTHER = "other"


# ---------- Goal ----------

class Goal(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A user goal: e.g. 'Obtain Canadian PR by 2029-12-31'."""

    __tablename__ = "goals"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenario: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. 'fsw' | 'uk-study' | generic tag
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")

    # Personalized probability cache
    success_probability: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # e.g. {"p50": 0.42, "p10": 0.18, "p90": 0.61, "computed_at": "..."}

    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    user: Mapped["UserProfile"] = relationship(  # type: ignore[name-defined]
        back_populates="goals", foreign_keys="Goal.user_id"
    )
    pathways: Mapped[list["Pathway"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Goal {self.title}>"


# ---------- Pathway ----------

class Pathway(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A path to achieve a goal, e.g. 'Federal Skilled Worker Program'."""

    __tablename__ = "pathways"

    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="candidate")
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # JSONB for free-form eligibility rules / cutoffs / steps
    eligibility: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    milestones: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # Branch management
    parent_pathway_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pathways.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    goal: Mapped["Goal"] = relationship(back_populates="pathways")
    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="pathway", cascade="all, delete-orphan"
    )
    parent: Mapped["Pathway | None"] = relationship(
        remote_side="Pathway.id", back_populates="children"
    )
    children: Mapped[list["Pathway"]] = relationship(back_populates="parent")

    def __repr__(self) -> str:
        return f"<Pathway {self.name}>"


# ---------- Requirement ----------

class Requirement(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A requirement node: language score, fund proof, education credential, etc."""

    __tablename__ = "requirements"

    pathway_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pathways.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="other")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cutoffs & current user value (free-form)
    threshold: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    current_value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Gap analysis cache
    gap_status: Mapped[str] = mapped_column(String(16), default="unknown")
    # 'met' | 'partial' | 'missing' | 'unknown'
    gap_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    weight: Mapped[float] = mapped_column(Float, default=1.0)
    # Importance weight for path scoring

    pathway: Mapped["Pathway"] = relationship(back_populates="requirements")

    def __repr__(self) -> str:
        return f"<Requirement {self.name}>"


# ---------- RiskFactor ----------

class RiskFactor(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """An external risk factor: policy shift, currency volatility, security, etc."""

    __tablename__ = "risk_factors"

    type: Mapped[str] = mapped_column(String(32), default="other")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Current risk level: 'low' | 'medium' | 'high'
    level: Mapped[str] = mapped_column(String(16), default="low")
    urgency: Mapped[str] = mapped_column(String(16), default="normal")
    # 'normal' | 'elevated' | 'urgent'

    # Numeric scoring inputs (0..1)
    probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Knowledge half-life (days)
    half_life_days: Mapped[int] = mapped_column(Integer, default=730)

    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    def __repr__(self) -> str:
        return f"<RiskFactor {self.name} ({self.level})>"


Index("ix_pathways_goal", Pathway.goal_id)
Index("ix_requirements_pathway", Requirement.pathway_id)
