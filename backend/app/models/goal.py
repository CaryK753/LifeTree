"""Goal / Pathway / Requirement / RiskFactor models — the heart of the ontology."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.types import JSON_DOCUMENT

if TYPE_CHECKING:
    from app.models.user import UserProfile


# ---------- Enums ----------


class GoalStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"


class PathwayStatus(str, Enum):
    # Legacy values (backward compat)
    CANDIDATE = "candidate"
    SELECTED = "selected"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    # Decision-tree states (§11.3 self-growing tree)
    PREDICTED = "predicted"  # LLM+math generated, user hasn't confirmed (虚线)
    CONFIRMED = "confirmed"  # User confirmed as a real option (实线)
    IN_PROGRESS = "in_progress"  # User is actively executing (实线+强调)
    ABANDONED = "abandoned"  # User gave up on this branch


class PathwayNodeType(str, Enum):
    ROOT = "root"  # Top-level pathway under a goal
    DECISION = "decision"  # A decision point requiring user choice
    BRANCH = "branch"  # A candidate route
    MILESTONE = "milestone"  # A checkpoint along a route


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


# ---------- M2M Association Tables ----------

# Requirements ↔ Pathways (many-to-many, §11.3 shared requirement nodes)
pathway_requirements = Table(
    "pathway_requirements",
    Base.metadata,
    Column(
        "pathway_id", String(36), ForeignKey("pathways.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "requirement_id",
        String(36),
        ForeignKey("requirements.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("is_blocking", Boolean, default=True, nullable=False),
    Column("created_at", Text, nullable=True),  # ISO timestamp for audit
    Index("ix_pathway_requirements_pathway", "pathway_id"),
    Index("ix_pathway_requirements_requirement", "requirement_id"),
)

# RiskFactors ↔ Pathways (many-to-many, fixes bug where all branches showed
# the same key_risk_factors because RiskFactor had no pathway linkage)
pathway_risk_factors = Table(
    "pathway_risk_factors",
    Base.metadata,
    Column(
        "pathway_id", String(36), ForeignKey("pathways.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "risk_factor_id",
        String(36),
        ForeignKey("risk_factors.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", Text, nullable=True),
    Index("ix_pathway_risk_factors_pathway", "pathway_id"),
    Index("ix_pathway_risk_factors_risk", "risk_factor_id"),
)


# ---------- Goal ----------


class Goal(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A user goal: e.g. 'Obtain Canadian PR by 2029-12-31'."""

    __tablename__ = "goals"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenario: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # e.g. 'fsw' | 'uk-study' | generic tag
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")

    # Personalized probability cache
    success_probability: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    # e.g. {"p50": 0.42, "p10": 0.18, "p90": 0.61, "computed_at": "..."}

    meta: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)

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
    """A path to achieve a goal, e.g. 'Federal Skilled Worker Program'.

    Extended in §11.3 to support a self-growing decision tree:
    - node_type distinguishes root/decision/branch/milestone nodes
    - tree_status tracks the prediction→confirmation→execution lifecycle
    - tree_level + display_order drive React Flow layout
    - evolution_hint stores the LLM+math suggestion that spawned this branch

    Merged Scenario fields (v0.4.0): assumptions, success_probability,
    risk_score, key_risk_factors, impact_threshold, computed_at are now
    stored directly on Pathway. The scenarios table is kept for backward
    compat but new writes go to pathways. This eliminates the asymmetric
    Pathway↔Scenario soft link and makes the decision tree node the
    single source of truth for both route selection and probability.
    """

    __tablename__ = "pathways"

    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="candidate")
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # JSONB for free-form eligibility rules / cutoffs / steps
    eligibility: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    milestones: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)

    # Branch management (legacy parent-child for sub-pathways)
    parent_pathway_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pathways.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # --- Decision-tree fields (§11.3) ---
    node_type: Mapped[str] = mapped_column(
        String(16), default="branch"
    )  # 'root' | 'decision' | 'branch' | 'milestone'
    decision_question: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # e.g. "Which country should I target?"
    tree_level: Mapped[int] = mapped_column(Integer, default=0)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    evolution_hint: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # LLM+math rationale for predicted branches

    # --- Merged Scenario fields (v0.4.0) ---
    # Previously on the Scenario model; now stored directly on Pathway so
    # the decision tree node is the single source of truth.
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    success_probability: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    key_risk_factors: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    impact_threshold: Mapped[float] = mapped_column(Float, default=0.05)
    computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    goal: Mapped["Goal"] = relationship(back_populates="pathways")
    # M2M relationships — requirements and risk_factors are now shared across
    # pathways via association tables, not owned by a single pathway.
    requirements: Mapped[list["Requirement"]] = relationship(
        secondary=pathway_requirements, lazy="selectin"
    )
    risk_factors: Mapped[list["RiskFactor"]] = relationship(
        secondary=pathway_risk_factors, lazy="selectin"
    )
    parent: Mapped["Pathway | None"] = relationship(
        remote_side="Pathway.id", back_populates="children"
    )
    children: Mapped[list["Pathway"]] = relationship(back_populates="parent")

    def __repr__(self) -> str:
        return f"<Pathway {self.name}>"


# ---------- Requirement ----------


class Requirement(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A requirement node: language score, fund proof, education credential, etc.

    As of §11.3, requirements are shared across pathways via the
    pathway_requirements M2M table. The legacy pathway_id column is kept
    for backward compat but is no longer the primary association.
    """

    __tablename__ = "requirements"

    # Legacy column — kept nullable for backward compat. New code should use
    # the pathway_requirements M2M table. _load_context falls back to this
    # when no M2M rows exist.
    pathway_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pathways.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="other")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cutoffs & current user value (free-form)
    threshold: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    current_value: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)

    # Gap analysis cache
    gap_status: Mapped[str] = mapped_column(String(16), default="unknown")
    # 'met' | 'partial' | 'missing' | 'unknown'
    gap_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    weight: Mapped[float] = mapped_column(Float, default=1.0)
    # Importance weight for path scoring

    def __repr__(self) -> str:
        return f"<Requirement {self.name}>"


# ---------- RiskFactor ----------


class RiskFactor(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """An external risk factor: policy shift, currency volatility, security, etc."""

    __tablename__ = "risk_factors"

    # NULL means an administrator-managed global template. A non-NULL value
    # scopes the risk instance to one user.
    user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=True,
    )
    identity_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

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

    meta: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)

    def __repr__(self) -> str:
        return f"<RiskFactor {self.name} ({self.level})>"


Index("ix_pathways_goal", Pathway.goal_id)
Index("ix_requirements_pathway", Requirement.pathway_id)
Index("ix_risk_factors_user_id", RiskFactor.user_id)
Index(
    "uq_risk_factors_user_identity",
    RiskFactor.user_id,
    RiskFactor.identity_key,
    unique=True,
    postgresql_where=(
        RiskFactor.user_id.is_not(None)
        & RiskFactor.identity_key.is_not(None)
        & RiskFactor.deleted_at.is_(None)
    ),
)
