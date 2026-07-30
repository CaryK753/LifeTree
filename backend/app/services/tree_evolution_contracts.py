"""Tolerant structured-output contracts for decision-tree evolution."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def branch_identity_key(value: str) -> str:
    """Normalize cosmetic differences so repeated evolution stays idempotent."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _bounded_number(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


class ProposedBranchRequirement(BaseModel):
    name: str = Field(..., max_length=200)
    type: Literal[
        "language", "financial", "education", "experience", "health", "legal", "other"
    ] = "other"
    threshold: dict[str, Any] = Field(default_factory=dict)
    gap_status: Literal["met", "partial", "missing", "unknown"] = "unknown"
    weight: float = Field(1.0, ge=0.05, le=2.0)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: Any) -> str:
        candidate = str(value or "other").lower()
        allowed = {"language", "financial", "education", "experience", "health", "legal"}
        return candidate if candidate in allowed else "other"

    @field_validator("gap_status", mode="before")
    @classmethod
    def normalize_gap_status(cls, value: Any) -> str:
        candidate = str(value or "unknown").lower()
        return candidate if candidate in {"met", "partial", "missing", "unknown"} else "unknown"

    @field_validator("threshold", mode="before")
    @classmethod
    def normalize_threshold(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {} if value in (None, "") else {"value": value}

    @field_validator("weight", mode="before")
    @classmethod
    def normalize_weight(cls, value: Any) -> float:
        return _bounded_number(value, 1.0, 0.05, 2.0)


class ProposedBranchRisk(BaseModel):
    name: str = Field(..., max_length=200)
    type: Literal[
        "policy", "economic", "security", "political", "health", "operational", "other"
    ] = "other"
    level: Literal["low", "medium", "high"] = "medium"
    probability: float = Field(0.5, ge=0.0, le=1.0)
    impact: float = Field(0.5, ge=0.0, le=1.0)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: Any) -> str:
        candidate = str(value or "other").lower()
        allowed = {"policy", "economic", "security", "political", "health", "operational"}
        return candidate if candidate in allowed else "other"

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, value: Any) -> str:
        candidate = str(value or "medium").lower()
        return candidate if candidate in {"low", "medium", "high"} else "medium"

    @field_validator("probability", "impact", mode="before")
    @classmethod
    def normalize_probability(cls, value: Any) -> float:
        return _bounded_number(value, 0.5, 0.0, 1.0)


class ProposedBranch(BaseModel):
    branch_name: str = Field(..., min_length=1, max_length=200)
    branch_description: str = Field("", max_length=400)
    region: str | None = None
    rationale: str = Field("", max_length=600)
    key_requirements: list[ProposedBranchRequirement] = Field(default_factory=list, max_length=6)
    key_risks: list[ProposedBranchRisk] = Field(default_factory=list, max_length=6)

    @field_validator("key_requirements", "key_risks", mode="before")
    @classmethod
    def normalize_optional_lists(cls, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []


class BranchProposal(BaseModel):
    branches: list[ProposedBranch] = Field(..., min_length=1, max_length=8)

    @field_validator("branches", mode="before")
    @classmethod
    def normalize_branches(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return [value]
        return value[:8] if isinstance(value, list) else value


class CompactBranch(BaseModel):
    branch_name: str = Field(..., min_length=1, max_length=200)
    branch_description: str = Field("", max_length=400)
    region: str | None = None
    rationale: str = Field("", max_length=600)


class CompactBranchProposal(BaseModel):
    branches: list[CompactBranch] = Field(..., min_length=1, max_length=5)

    def expand(self) -> BranchProposal:
        return BranchProposal(
            branches=[ProposedBranch(**branch.model_dump()) for branch in self.branches]
        )
