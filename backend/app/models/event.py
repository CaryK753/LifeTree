"""Event / MetricSnapshot / Assertion / Relationship / InformationSource models.

These are the structured "information atoms" produced by the structuring pipeline.
Each links back to an InformationSource that tracks provenance and credibility.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base
from app.models.base import TimestampMixin, UUIDPkMixin


# ---------- InformationSource ----------

class SourceKind(str, Enum):
    PUBLIC = "public"
    USER_UPLOAD = "user_upload"
    ADVISOR = "advisor"
    OFFICIAL = "official"
    NEWS = "news"
    OTHER = "other"


class Credibility(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    PENDING = "pending"
    USER_MARKED_RELIABLE = "user_marked_reliable"
    USER_MARKED_QUESTIONABLE = "user_marked_questionable"


class InformationSource(UUIDPkMixin, TimestampMixin, Base):
    """A source of information: Tavily result, user upload, advisor email, etc."""

    __tablename__ = "information_sources"

    # Owner — NULL for legacy/global rows, set to the user who ingested it.
    # In single-user mode this is the default user's id.
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=True, index=True
    )

    kind: Mapped[str] = mapped_column(String(32), default="public")
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    credibility: Mapped[str] = mapped_column(String(32), default="pending")
    credibility_score: Mapped[float] = mapped_column(Float, default=0.5)

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Original user upload reference (if kind=user_upload). Holds either a
    # UUID (legacy) or a MinIO object key like "uploads/<uuid>/<filename>".
    user_upload_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<InformationSource {self.kind}:{self.title[:40]}>"


# ---------- Semantic fingerprint for dedup ----------

class EventFingerprint(UUIDPkMixin, TimestampMixin, Base):
    """Semantic fingerprint used for dedup/merge across sources.

    fingerprint = sha256(subject|action|object|time_window)
    """

    __tablename__ = "event_fingerprints"

    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    object: Mapped[str | None] = mapped_column(String(255), nullable=True)
    time_window: Mapped[str | None] = mapped_column(String(64), nullable=True)

    primary_event_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=1)


# ---------- Event (the structured atom) ----------

class Event(UUIDPkMixin, TimestampMixin, Base):
    """An atomic event: subject did action on object at time, old→new value.

    Linked to one or more InformationSource records (provenance) and to the
    RiskFactor / Goal / Pathway / Requirement nodes it affects.
    """

    __tablename__ = "events"

    # Owner — NULL for legacy/global rows, set to the user who ingested it.
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=True, index=True
    )

    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("information_sources.id", ondelete="SET NULL"), index=True
    )

    # Subject / Action / Object triple
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    object: Mapped[str | None] = mapped_column(String(255), nullable=True)

    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # old→new (stringified to support arbitrary types)
    old_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    # Risk flag assigned by LLM extraction layer
    risk_flag_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 'high' | 'medium' | 'low' | None
    risk_flag_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_flag_urgency: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Extraction confidence (0..1)
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.8)

    # Status for Review Inbox & auto-sinking (§4.9)
    # 'approved' | 'pending_review' | 'sunk_low_weight'
    status: Mapped[str] = mapped_column(String(32), default="approved")

    # Vector embedding (for RAG / similarity search across events)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    # Free-form metadata
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Knowledge half-life (days) — overrides default if set
    half_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped["InformationSource | None"] = relationship()

    def __repr__(self) -> str:
        return f"<Event {self.subject}:{self.action}>"


# ---------- MetricSnapshot ----------

class MetricSnapshot(UUIDPkMixin, TimestampMixin, Base):
    """A numeric data point at a point in time: e.g. CRS cutoff 510 at 2026-06-15."""

    __tablename__ = "metric_snapshots"

    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("information_sources.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# ---------- Assertion (unconfirmed claim) ----------

class Assertion(UUIDPkMixin, TimestampMixin, Base):
    """An unconfirmed statement, possibly conflicting with others.

    When two Assertions conflict, the system spawns a Scenario branch.
    """

    __tablename__ = "assertions"

    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("information_sources.id", ondelete="SET NULL"), index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)

    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    # 0..1 — credibility-weighted confidence
    status: Mapped[str] = mapped_column(String(16), default="open")
    # 'open' | 'confirmed' | 'refuted' | 'superseded'

    conflicting_with_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# ---------- Relationship (causal / correlation declaration) ----------

class Relationship(UUIDPkMixin, TimestampMixin, Base):
    """A causal/correlation statement between two entities.

    Subject ──[type]──▶ Object
    e.g. PolicyChange ──[AFFECTS]──▶ Pathway
    """

    __tablename__ = "relationships"

    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("information_sources.id", ondelete="SET NULL"), index=True
    )

    # Polymorphic subject/object refs (entity_type:entity_id)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 'AFFECTS' | 'REQUIRES' | 'ALTERNATIVE_TO' | 'WARNS' | 'EQUALS' | 'CAUSES'
    type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Edge weight: -1.0 (strongly negative) .. +1.0 (strongly positive)
    weight: Mapped[float] = mapped_column(Float, default=0.0)

    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


Index("ix_events_subject_action", Event.subject, Event.action)
Index("ix_metrics_name_region", MetricSnapshot.name, MetricSnapshot.region)
Index("ix_relationships_subject", Relationship.subject_type, Relationship.subject_id)
Index("ix_relationships_object", Relationship.object_type, Relationship.object_id)
