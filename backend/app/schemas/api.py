"""Schemas for events, sources, scenarios, notifications, knowledge graph, chat."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.entities import ORMModel


# ---------- Information sources ----------

class InformationSourceBase(BaseModel):
    kind: Literal[
        "public", "user_upload", "advisor", "official", "news", "other"
    ] = "public"
    title: str
    url: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    credibility: Literal[
        "high", "medium", "low", "pending",
        "user_marked_reliable", "user_marked_questionable"
    ] = "pending"
    credibility_score: float = 0.5
    raw_text: str | None = None
    meta: dict[str, Any] = {}
    user_upload_id: str | None = None


class InformationSourceCreate(InformationSourceBase):
    pass


class InformationSourceRead(InformationSourceBase, ORMModel):
    id: str
    created_at: datetime
    updated_at: datetime


# ---------- Events ----------

class EventBase(BaseModel):
    source_id: str | None = None
    subject: str
    action: str
    object: str | None = None
    occurred_at: datetime | None = None
    effective_at: datetime | None = None
    old_value: Any | None = None
    new_value: Any | None = None
    risk_flag_level: Literal["low", "medium", "high"] | None = None
    risk_flag_type: str | None = None
    risk_flag_urgency: Literal["normal", "elevated", "urgent"] | None = None
    extraction_confidence: float = 0.8
    meta: dict[str, Any] = {}


class EventCreate(EventBase):
    pass


class EventRead(EventBase, ORMModel):
    id: str
    half_life_days: int | None = None
    created_at: datetime
    updated_at: datetime


# ---------- Scenarios ----------

class ScenarioBase(BaseModel):
    name: str
    description: str | None = None
    status: Literal["draft", "active", "dormant", "merged", "closed"] = "draft"
    parent_scenario_id: str | None = None
    assumptions: dict[str, Any] = {}
    impact_threshold: float = 0.05


class ScenarioCreate(ScenarioBase):
    goal_id: str


class ScenarioRead(ScenarioBase, ORMModel):
    id: str
    goal_id: str
    success_probability: dict[str, Any] = {}
    risk_score: float | None = None
    key_risk_factors: list[dict[str, Any]] = []
    milestones: list[dict[str, Any]] = []
    computed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # §5 透明化 — survival curve + key risk times are needed for the
    # scenario comparison overlay view. Populated from the latest
    # ScenarioRun.result by the API layer (not stored on the Scenario
    # itself to avoid duplicating large JSON blobs).
    survival_curve: list[dict[str, Any]] = []
    key_risk_times: list[dict[str, Any]] = []
    median_time_months: float | None = None


class ScenarioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: Literal["draft", "active", "dormant", "merged", "closed"] | None = None
    assumptions: dict[str, Any] | None = None
    impact_threshold: float | None = None


class ScenarioRunRead(ORMModel):
    id: str
    scenario_id: str
    engine: str
    status: str
    iterations: int | None = None
    duration_ms: int | None = None
    result: dict[str, Any] = {}
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


# ---------- Knowledge graph ----------

class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    properties: dict[str, Any] = {}


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    weight: float = 0.0


class GraphSnapshot(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    scenario_id: str | None = None


# ---------- Notifications ----------

class NotificationRead(ORMModel):
    id: str
    user_id: str
    channel: str
    status: str
    severity: str
    title: str
    body: str
    event_id: str | None = None
    risk_factor_id: str | None = None
    impact_summary: dict[str, Any] = {}
    sent_at: datetime | None = None
    read_at: datetime | None = None
    created_at: datetime


# ---------- Risk assessment ----------

class RiskAssessmentRead(ORMModel):
    id: str
    user_id: str
    goal_id: str
    scenario_id: str | None = None
    overall_risk: float
    factor_scores: list[dict[str, Any]] = []
    success_curve: list[dict[str, Any]] = []
    computed_at: datetime


# ---------- Structuring ----------

class IngestTextRequest(BaseModel):
    """Request to ingest a piece of text through the structuring pipeline."""

    text: str = Field(..., min_length=1)
    title: str = "Untitled"
    source_kind: Literal[
        "public", "user_upload", "advisor", "official", "news", "other"
    ] = "public"
    url: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    user_id: str | None = None  # deprecated; ignored in single-user mode
    user_upload_id: str | None = None
    skip_llm: bool = False  # If True, store source only without LLM extraction


class IngestTextResponse(BaseModel):
    source_id: str
    events_created: int
    metrics_created: int
    assertions_created: int
    relationships_created: int
    extraction_confidence: float | None = None
    notifications_triggered: int = 0


# ---------- AI Advisor chat ----------

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    # For ``assistant`` messages that invoked tools, the list of tool calls
    # emitted by the model. Each entry is ``{"id": str, "name": str,
    # "args": dict}``. Required to round-trip tool interactions across turns
    # — the corresponding ``tool`` role messages reference the same id via
    # ``tool_call_id``.
    tool_calls: list[dict[str, Any]] | None = None
    # For ``tool`` role messages: the id of the assistant tool_call this
    # result corresponds to. Required so the model can match a tool result
    # back to the call that produced it.
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    user_id: str | None = None  # deprecated; ignored in single-user mode
    goal_id: str | None = None
    scenario_id: str | None = None
    messages: list[ChatMessage]
    tools: list[str] | None = None  # Tool names to expose
    stream: bool = True


class ChatToolCall(BaseModel):
    name: str
    args: dict[str, Any]
    result: dict[str, Any] | None = None


class ChatResponseChunk(BaseModel):
    """One streamed chunk from the AI advisor endpoint (SSE event payload)."""

    delta: str = ""
    tool_call: ChatToolCall | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


# ---------- Statistics ----------

class CredibilityDistribution(BaseModel):
    high: int = 0
    medium: int = 0
    low: int = 0
    pending: int = 0
    user_marked_reliable: int = 0
    user_marked_questionable: int = 0
    total: int = 0
    private_share: float = 0.0  # fraction from user uploads


class DashboardSummary(BaseModel):
    goal_id: str
    goal_title: str | None = None
    goal_scenario: str | None = None
    goal_target_date: str | None = None
    goal_status: str | None = None
    success_probability: dict[str, Any] = {}
    milestones: list[dict[str, Any]] = []
    recent_events: list[EventRead] = []
    risk_heatmap: list[dict[str, Any]] = []
    credibility: CredibilityDistribution = Field(default_factory=CredibilityDistribution)
    active_scenarios: int = 0
    consecutive_planning_days: int = 0
    # §5 透明化 + 收敛建议 — drill-down from the latest reasoning run
    regret_free_actions: list[dict[str, Any]] = []
    factor_contributions: list[dict[str, Any]] = []
    reasoning_explanation: str | None = None
    median_time_months: float | None = None
    survival_curve: list[dict[str, Any]] = []
    key_risk_times: list[dict[str, Any]] = []
    reasoning_run_id: str | None = None
    reasoning_iterations: int | None = None
