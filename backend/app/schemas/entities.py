"""Pydantic schemas for REST API request/response bodies."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------- Shared ----------

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------- Users ----------

class UserProfileBase(BaseModel):
    display_name: str
    email: str | None = None
    avatar_url: str | None = None
    demographics: dict[str, Any] = {}
    priority_factors: dict[str, Any] = {}
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    notify_channels: dict[str, bool] = {"email": True, "in_app": True}
    quiet_hours: dict[str, Any] = {}


class UserProfileCreate(UserProfileBase):
    external_id: str | None = None


class UserProfileRead(UserProfileBase, ORMModel):
    id: str
    primary_goal_id: str | None = None
    preferred_pathway_id: str | None = None
    progress: dict[str, Any] = {}
    implicit_tags: dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime


class UserProfileUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    demographics: dict[str, Any] | None = None
    priority_factors: dict[str, Any] | None = None
    risk_tolerance: Literal["low", "medium", "high"] | None = None
    notify_channels: dict[str, bool] | None = None
    quiet_hours: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None
    implicit_tags: dict[str, Any] | None = None
    primary_goal_id: str | None = None
    preferred_pathway_id: str | None = None


# ---------- User memories (unbounded "remember this" channel) ----------

class UserMemoryBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)
    category: str = Field("other", max_length=32)
    importance: float = Field(0.5, ge=0.0, le=1.0)
    source: Literal["chat", "manual", "upload", "plugin"] = "manual"
    meta: dict[str, Any] = {}


class UserMemoryCreate(UserMemoryBase):
    user_id: str | None = None  # defaults to default user in single-user mode


class UserMemoryRead(UserMemoryBase, ORMModel):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime


class UserMemoryUpdate(BaseModel):
    content: str | None = Field(None, min_length=1, max_length=1000)
    category: str | None = Field(None, max_length=32)
    importance: float | None = Field(None, ge=0.0, le=1.0)
    meta: dict[str, Any] | None = None


# ---------- Goals ----------

class GoalBase(BaseModel):
    title: str
    description: str | None = None
    scenario: str = "generic"
    target_date: date | None = None
    status: Literal["draft", "active", "paused", "achieved", "abandoned"] = "draft"
    meta: dict[str, Any] = {}


class GoalCreate(GoalBase):
    user_id: str | None = None  # optional in single-user mode; defaults to the default user
    pathways: list["PathwayCreate"] = []


class GoalRead(GoalBase, ORMModel):
    id: str
    user_id: str
    success_probability: dict[str, Any] = {}
    pathways: list["PathwayRead"] = []
    created_at: datetime
    updated_at: datetime


class GoalUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    scenario: str | None = None
    target_date: date | None = None
    status: Literal["draft", "active", "paused", "achieved", "abandoned"] | None = None
    meta: dict[str, Any] | None = None


# ---------- Pathways ----------

class PathwayBase(BaseModel):
    name: str
    description: str | None = None
    region: str | None = None
    status: Literal["candidate", "selected", "rejected", "superseded"] = "candidate"
    eligibility: dict[str, Any] = {}
    milestones: list[dict[str, Any]] = []
    parent_pathway_id: str | None = None
    scenario_id: str | None = None


class PathwayCreate(PathwayBase):
    requirements: list["RequirementCreate"] = []


class PathwayRead(PathwayBase, ORMModel):
    id: str
    goal_id: str
    requirements: list["RequirementRead"] = []
    created_at: datetime
    updated_at: datetime


class PathwayUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    region: str | None = None
    status: Literal["candidate", "selected", "rejected", "superseded"] | None = None
    eligibility: dict[str, Any] | None = None
    milestones: list[dict[str, Any]] | None = None
    parent_pathway_id: str | None = None
    scenario_id: str | None = None


# ---------- Requirements ----------

class RequirementBase(BaseModel):
    name: str
    type: Literal[
        "language", "financial", "education", "experience", "health", "legal", "other"
    ] = "other"
    description: str | None = None
    threshold: dict[str, Any] = {}
    current_value: dict[str, Any] = {}
    gap_status: Literal["met", "partial", "missing", "unknown"] = "unknown"
    gap_delta: float | None = None
    weight: float = 1.0


class RequirementCreate(RequirementBase):
    pass


class RequirementRead(RequirementBase, ORMModel):
    id: str
    pathway_id: str
    created_at: datetime
    updated_at: datetime


class RequirementUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    description: str | None = None
    threshold: dict[str, Any] | None = None
    current_value: dict[str, Any] | None = None
    gap_status: Literal["met", "partial", "missing", "unknown"] | None = None
    gap_delta: float | None = None
    weight: float | None = None


# ---------- RiskFactors ----------

class RiskFactorBase(BaseModel):
    type: Literal[
        "policy", "economic", "security", "political", "health", "operational", "other"
    ] = "other"
    name: str
    description: str | None = None
    region: str | None = None
    level: Literal["low", "medium", "high"] = "low"
    urgency: Literal["normal", "elevated", "urgent"] = "normal"
    probability: float | None = None
    impact: float | None = None
    half_life_days: int = 730
    meta: dict[str, Any] = {}


class RiskFactorCreate(RiskFactorBase):
    pass


class RiskFactorRead(RiskFactorBase, ORMModel):
    id: str
    created_at: datetime
    updated_at: datetime


class RiskFactorUpdate(BaseModel):
    type: str | None = None
    name: str | None = None
    description: str | None = None
    region: str | None = None
    level: Literal["low", "medium", "high"] | None = None
    urgency: Literal["normal", "elevated", "urgent"] | None = None
    probability: float | None = None
    impact: float | None = None
    half_life_days: int | None = None
    meta: dict[str, Any] | None = None


# Forward refs for nested models
GoalCreate.model_rebuild()
GoalRead.model_rebuild()
PathwayCreate.model_rebuild()
PathwayRead.model_rebuild()
