"""Pydantic schemas for LLM structured-output extraction.

These are the "information atoms" defined in §4.1 of the project plan.
Each is a strict, LLM-fillable schema that Instructor uses to enforce output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

RiskLevel = Literal["low", "medium", "high"]
RiskUrgency = Literal["normal", "elevated", "urgent"]
RiskType = Literal["policy", "economic", "security", "political", "health", "operational", "other"]


class RiskFlag(BaseModel):
    """Risk metadata emitted alongside an extracted atom."""

    level: RiskLevel = Field(
        default="low", description="Severity of the risk implied by this atom."
    )
    type: RiskType = Field(default="other", description="Category of risk.")
    urgency: RiskUrgency = Field(default="normal", description="How soon the user must act.")
    rationale: str = Field(default="", description="One-sentence justification.")


class EventAtom(BaseModel):
    """An atomic event: subject did action on object at time, old→new value."""

    subject: str = Field(..., description="Actor / entity doing the action.")
    action: str = Field(..., description="What the subject did.")
    object: str | None = Field(None, description="Target of the action, if any.")
    occurred_at: datetime | None = Field(None, description="When the event happened (ISO 8601).")
    effective_at: datetime | None = Field(
        None,
        description="When the event takes legal/practical effect, if different.",
    )
    old_value: str | None = Field(None, description="Prior value, if a change.")
    new_value: str | None = Field(None, description="New value, if a change.")
    risk_flag: RiskFlag = Field(default_factory=RiskFlag)
    extraction_confidence: float = Field(
        default=0.8, ge=0.0, le=1.0, description="LLM's confidence in the extraction."
    )
    summary: str = Field("", description="One-sentence human-readable summary.")

    @field_validator("subject", "action")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be non-empty")
        return v.strip()


class MetricAtom(BaseModel):
    """A numeric data point: e.g. CRS cutoff 510 at 2026-06-15."""

    name: str = Field(..., description="Metric identifier, e.g. 'CRS_cutoff'.")
    region: str | None = Field(None, description="Geographic scope, if applicable.")
    value: float = Field(..., description="Numeric value.")
    unit: str | None = Field(None, description="Unit, e.g. 'points', 'CAD'.")
    captured_at: datetime | None = Field(None, description="When the value was measured.")
    risk_flag: RiskFlag = Field(default_factory=RiskFlag)


class AssertionAtom(BaseModel):
    """An unconfirmed claim, possibly conflicting with prior assertions."""

    subject: str = Field(...)
    predicate: str = Field("claims", description="Normalized relation or property name.")
    claim: str = Field(..., description="The proposition being asserted.")
    object_value: Any | None = Field(None, description="Structured claimed value when available.")
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    conflicts_with: str | None = Field(
        None,
        description="Free-form description of conflicting prior claim, if any.",
    )
    risk_flag: RiskFlag = Field(default_factory=RiskFlag)


class RelationshipAtom(BaseModel):
    """A causal / correlation statement: subject ──[type]──▶ object."""

    subject_type: Literal[
        "Goal", "Pathway", "Requirement", "RiskFactor", "Event", "MetricSnapshot"
    ] = Field(...)
    subject_id: str | None = Field(
        None,
        description=(
            "Optional existing entity ID. If absent, the structuring service "
            "will resolve by name with the LLM."
        ),
    )
    subject_name: str = Field(..., description="Human-readable subject label.")
    object_type: Literal[
        "Goal", "Pathway", "Requirement", "RiskFactor", "Event", "MetricSnapshot"
    ] = Field(...)
    object_id: str | None = Field(None)
    object_name: str = Field(...)
    type: Literal["AFFECTS", "REQUIRES", "ALTERNATIVE_TO", "WARNS", "EQUALS", "CAUSES"] = Field(...)
    weight: float = Field(default=0.0, ge=-1.0, le=1.0, description="Edge weight [-1, +1].")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class StructuredExtraction(BaseModel):
    """Top-level container returned by the structuring pipeline for one document."""

    events: list[EventAtom] = Field(default_factory=list)
    metrics: list[MetricAtom] = Field(default_factory=list)
    assertions: list[AssertionAtom] = Field(default_factory=list)
    relationships: list[RelationshipAtom] = Field(default_factory=list)
    source_summary: str = Field("", description="Short summary of the source document.")
    language: str = Field(default="en", description="Detected language code.")
    overall_confidence: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Pipeline-level extraction confidence."
    )
