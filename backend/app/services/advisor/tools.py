"""Tools exposed to the intelligent assistant LangGraph agent.

Each tool is a thin, dependency-free wrapper around the existing services
(ScenarioService, ReasoningEngine, raw DB queries). Tools take the DB session
and context IDs (user_id / goal_id / scenario_id) via a closure so the
LangGraph tool-calling interface stays clean.

Per project plan §7.3: the advisor can (1) query the user's ontology,
(2) trigger a scenario reasoning run, (3) list recent events, (4) suggest
a no-regret action. We expose exactly those capabilities here, plus a
writing channel for create_goal / create_pathway / create_risk_factor
and the unbounded "memory" channel (remember / list_memories / forget).
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.postgres import SessionLocal
from app.models.action import Action
from app.models.event import Event, InformationSource
from app.models.goal import (
    Goal,
    Pathway,
    Requirement,
    RiskFactor,
    pathway_requirements,
    pathway_risk_factors,
)
from app.models.memory import UserMemory
from app.models.scenario import Scenario
from app.models.user import UserProfile
from app.models.user_runtime import UserServiceConfig
from app.services.advisor.calendar_tools import build_action_calendar_tools
from app.services.crawler import CrawlerService
from app.services.goal_identity import find_equivalent_goal, lock_goal_identity
from app.services.graph import GraphService
from app.services.risk_adoption import adopt_risk_for_pathway
from app.services.risk_scope import risk_scope_clause
from app.services.scenario_contracts import resolve_create_pathway_id
from app.services.scenarios import ScenarioService
from app.services.source_discovery import SourceDiscoveryService
from app.services.tree_evolution import TreeEvolutionService

log = get_logger(__name__)


# ---------- Tool input schemas ----------

class ListPathwaysInput(BaseModel):
    goal_id: str | None = Field(None, description="Goal ID to list pathways for. Omit to use the current goal context.")


class ListRequirementsInput(BaseModel):
    pathway_id: str = Field(..., description="Pathway ID to list requirements for")


class ListRiskFactorsInput(BaseModel):
    region: str | None = Field(
        None, description="Optional region filter (e.g. 'CA', 'US')"
    )


class ListRecentEventsInput(BaseModel):
    limit: int = Field(10, description="Number of recent events to return", ge=1, le=50)
    risk_level: str | None = Field(
        None, description="Filter by risk level: 'low' | 'medium' | 'high'"
    )


class RunScenarioReasoningInput(BaseModel):
    scenario_id: str | None = Field(None, description="Scenario ID to run reasoning on. Omit to use the current scenario context.")


class GetScenarioSummaryInput(BaseModel):
    scenario_id: str | None = Field(None, description="Scenario ID to summarize. Omit to use the current scenario context.")


class EmptyInput(BaseModel):
    """Explicit no-argument schema for tools that only use bound context."""


# --- Write tools (create ontology entities) ---

class CreateGoalInput(BaseModel):
    title: str = Field(..., description="Short goal title, e.g. 'Get Canadian PR by 2029'")
    description: str | None = Field(None, description="Longer description / motivation")
    scenario: str = Field("generic", description="Scenario tag like 'fsw' or 'uk-study'")
    target_date: str | None = Field(
        None, description="ISO date string (YYYY-MM-DD) or null"
    )


class CreatePathwayInput(BaseModel):
    goal_id: str | None = Field(None, description="Parent goal ID. Omit to use the current goal context.")
    name: str = Field(..., description="Pathway name, e.g. 'Federal Skilled Worker Program'")
    description: str | None = None
    region: str | None = Field(None, description="Region tag like 'CA' or 'UK'")
    parent_pathway_id: str | None = Field(
        None, description="Optional parent pathway ID to create a sub-branch"
    )


class CreateRequirementInput(BaseModel):
    pathway_id: str = Field(..., description="Parent pathway ID")
    name: str = Field(..., description="Requirement name, e.g. 'IELTS Speaking 6.0'")
    type: str = Field(
        "other",
        description="One of: language, financial, education, experience, health, legal, other",
    )
    description: str | None = None
    threshold: dict[str, Any] | None = Field(
        None, description="Threshold JSON, e.g. {'score': 6.0, 'band': 'speaking'}"
    )
    current_value: dict[str, Any] | None = Field(
        None, description="User's current value, e.g. {'score': 5.5}"
    )
    gap_status: str | None = Field(
        None, description="One of: met, partial, missing, unknown"
    )
    weight: float = Field(1.0, description="Importance weight (default 1.0)")


class CreateRiskFactorInput(BaseModel):
    pathway_id: str | None = Field(
        None,
        description="Pathway to attach the risk to. Omit to use the current goal's first pathway.",
    )
    name: str = Field(..., description="Risk factor name")
    type: str = Field(
        "other",
        description="One of: policy, economic, security, political, health, operational, other",
    )
    description: str | None = None
    region: str | None = None
    level: str = Field("medium", description="One of: low, medium, high")
    urgency: str = Field("normal", description="One of: normal, elevated, urgent")
    probability: float | None = Field(None, ge=0.0, le=1.0)
    impact: float | None = Field(None, ge=0.0, le=1.0)


class UpdateRequirementStatusInput(BaseModel):
    requirement_id: str = Field(..., description="ID of the requirement node to update")
    gap_status: str = Field(
        ...,
        description="Requirement status: 'met' | 'partial' | 'missing' | 'unknown'",
    )
    current_value: dict[str, Any] | None = Field(
        None,
        description="Optional updated user current value dict, e.g. {'score': 7.5}",
    )


class AddUserSourceInput(BaseModel):
    content: str = Field(
        ..., description="Raw text snippet, email content, or forum post provided by user"
    )
    source_type: str = Field(
        "chat_mention",
        description="Source channel or type, e.g. 'chat_mention', 'consultant_email', 'forum_post'",
    )
    credibility: str = Field(
        "pending",
        description="Initial credibility rating: 'pending' | 'high' | 'medium' | 'low' | 'user_marked_reliable'",
    )


# --- Memory tools ---

class RememberInput(BaseModel):
    content: str = Field(
        ...,
        description=(
            "A short fact about the user worth remembering for future advice. "
            "Keep it under 200 chars and self-contained. Examples: "
            "'Has a 3-year-old daughter', 'Allergic to shellfish', "
            "'Currently a senior engineer at Acme'."
        ),
        max_length=1000,
    )
    category: str = Field(
        "other",
        description=(
            "Coarse category for filtering. Suggested values: "
            "family, career, health, finance, education, location, preference, "
            "goal, constraint, other."
        ),
        max_length=32,
    )
    importance: float = Field(
        0.5,
        description=(
            "0..1 — how central this fact is to the user's decisions. "
            "Use >=0.8 for hard constraints (legal status, deadline), "
            "0.3..0.7 for context (job title, family), "
            "<0.3 for trivia."
        ),
        ge=0.0,
        le=1.0,
    )


class ForgetIntInput(BaseModel):
    memory_id: str = Field(..., description="ID of the memory to delete")


class ListMemoriesInput(BaseModel):
    category: str | None = Field(
        None, description="Optional category filter (e.g. 'health')"
    )
    limit: int = Field(20, description="Max memories to return", ge=1, le=200)


# --- Profile & Scenario Branch tools ---

class UpdateUserProfileInput(BaseModel):
    lifecycle_stage: str | None = Field(
        None,
        description="User's lifecycle stage: 'planning' | 'submitted' | 'in_review' | 'waiting_eoi'",
    )
    cruising_mode: bool | None = Field(
        None,
        description="Whether to enable Cruising Mode during long waiting periods",
    )
    demographics_update: dict[str, Any] | None = Field(
        None,
        description="Updates to demographics dict, e.g. {'age': 30, 'language_score': 'IELTS 7.5'}",
    )


class CreateScenarioBranchInput(BaseModel):
    goal_id: str | None = Field(None, description="Goal ID to create scenario branch for. Omit to use the current goal context.")
    pathway_id: str | None = Field(
        None,
        description="Pathway this scenario evaluates. Omit only for a goal-wide what-if branch.",
    )
    name: str = Field(..., description="Scenario branch name, e.g. 'Canada FSW' or 'Japan IT'")
    description: str | None = Field(None, description="Optional description of the branch assumptions")


# --- Web tools ---

class WebSearchInput(BaseModel):
    query: str = Field(..., description="Search query string")
    max_results: int = Field(
        5, description="Max number of results to return (default 5, max 10)"
    )


class WebFetchInput(BaseModel):
    urls: list[str] = Field(
        ..., description="List of URLs to fetch and extract text from (max 5)"
    )


# --- Source discovery tools (P1 信源自动发现) ---

class ProposeSourcesInput(BaseModel):
    goal_id: str | None = Field(
        None, description="Goal ID to discover sources for. Omit to use the current goal context."
    )
    limit: int = Field(
        5, description="Max number of source candidates to propose (1-20)", ge=1, le=20
    )


# --- Action tools (P0-线B a4) ---

class CreateActionInput(BaseModel):
    title: str = Field(..., description="Short action title, e.g. 'Book IELTS test date'")
    description: str | None = Field(None, description="Longer description of the action")
    goal_id: str | None = Field(
        None, description="Parent goal ID. Omit to use the current goal context."
    )
    stage: str | None = Field(
        None, description="Stage tag, e.g. 'language_prep' or 'funds'"
    )
    due_at: str | None = Field(
        None, description="ISO date string (YYYY-MM-DD) or null"
    )
    cost: float = Field(
        0.5, description="Normalized cost 0..1 (time/money/effort blended)"
    )
    expected_prob_lift: float = Field(
        0.0, description="Expected absolute lift in scenario P(success) if completed, 0..1"
    )
    requirement_id: str | None = Field(
        None, description="Optional linked requirement — completing the action will mark it as 'met'"
    )
    risk_factor_id: str | None = Field(
        None, description="Optional linked risk factor — completing the action can mitigate it"
    )


class CompleteActionInput(BaseModel):
    action_id: str = Field(..., description="ID of the action to mark completed")


class ListTodayActionsInput(BaseModel):
    goal_id: str | None = Field(
        None, description="Optional goal filter. Omit to use the current goal context."
    )


# --- Discovery & search tools (P1) ---

class DiscoverRisksInput(BaseModel):
    days: int = Field(
        14, description="Lookback window in days for recent events to cluster", ge=1, le=90
    )


class GlobalSearchInput(BaseModel):
    query: str = Field(..., description="Search query string")
    limit: int = Field(20, description="Max results to return", ge=1, le=100)


# --- Goal management tools ---

class ListGoalsInput(BaseModel):
    status: str | None = Field(None, description="Filter by status: 'draft' | 'active' | 'achieved' | 'abandoned'")


class UpdateGoalInput(BaseModel):
    goal_id: str = Field(..., description="ID of the goal to update")
    title: str | None = Field(None, description="New title")
    description: str | None = Field(None, description="New description")
    target_date: str | None = Field(None, description="ISO date string (YYYY-MM-DD) or null")
    status: str | None = Field(None, description="New status: 'draft' | 'active' | 'achieved' | 'abandoned'")


class ArchiveGoalInput(BaseModel):
    goal_id: str = Field(..., description="ID of the goal to archive")


class UpdateRiskFactorInput(BaseModel):
    risk_factor_id: str = Field(..., description="ID of the risk factor to update")
    level: str | None = Field(None, description="New level: 'low' | 'medium' | 'high'")
    urgency: str | None = Field(None, description="New urgency: 'normal' | 'elevated' | 'urgent'")
    probability: float | None = Field(None, ge=0.0, le=1.0)
    impact: float | None = Field(None, ge=0.0, le=1.0)
    description: str | None = Field(None)


class CompareScenariosInput(BaseModel):
    scenario_ids: list[str] = Field(..., description="List of 2-5 scenario IDs to compare", min_length=2, max_length=5)


class IngestUrlInput(BaseModel):
    url: str = Field(..., description="URL to fetch and structure into the knowledge graph")
    source_type: str = Field("public", description="Source kind: 'public' | 'official' | 'news'")


class ListSourceProposalsInput(BaseModel):
    goal_id: str | None = Field(None, description="Optional goal filter")
    status: str | None = Field(None, description="Filter: 'proposed' | 'accepted' | 'rejected'")


class AcceptSourceProposalInput(BaseModel):
    proposal_id: str = Field(..., description="ID of the source proposal to accept")


class RejectSourceProposalInput(BaseModel):
    proposal_id: str = Field(..., description="ID of the source proposal to reject")


class ResolveConflictInput(BaseModel):
    subject_id: str = Field(..., description="The subject entity ID of the conflicting relationships")
    predicate: str = Field(..., description="The relationship type/predicate")
    winning_source_id: str = Field(..., description="ID of the source to treat as authoritative")


class UpdateActionInput(BaseModel):
    action_id: str = Field(..., description="ID of the action to update")
    title: str | None = None
    description: str | None = None
    stage: str | None = None
    due_at: str | None = Field(None, description="ISO date string (YYYY-MM-DD) or null")
    status: str | None = Field(None, description="New status: 'pending' | 'in_progress' | 'completed' | 'skipped' | 'deferred'")
    cost: float | None = Field(None, ge=0.0, le=1.0)
    expected_prob_lift: float | None = Field(None, ge=0.0, le=1.0)


class GetActionDetailInput(BaseModel):
    action_id: str = Field(..., description="ID of the action to retrieve")


# --- Decision-tree tools (§11.3 self-growing tree) ---

class ListDecisionTreeInput(BaseModel):
    goal_id: str | None = Field(
        None,
        description="Goal ID to inspect. Omit to use the current goal context.",
    )


class GrowTreeInput(BaseModel):
    parent_pathway_id: str = Field(
        ..., description="ID of the parent pathway to grow a child branch from."
    )
    name: str = Field(..., description="Short name for the new branch.")
    description: str | None = Field(None, description="1-2 sentence description.")
    region: str | None = Field(None, description="Region tag like 'CA' or 'UK'.")


class EvolveTreeInput(BaseModel):
    pathway_id: str = Field(
        ...,
        description="ID of the pathway to evolve. The LLM will propose 2-5 child branches.",
    )


class ConfirmBranchInput(BaseModel):
    pathway_id: str = Field(..., description="ID of the predicted branch to confirm.")


class SelectBranchInput(BaseModel):
    pathway_id: str = Field(..., description="ID of the branch to mark as in_progress.")
    abandon_siblings: bool = Field(
        False,
        description="If true, mark all sibling branches at the same tree_level as 'abandoned'.",
    )


class AbandonBranchInput(BaseModel):
    pathway_id: str = Field(..., description="ID of the branch to abandon.")


async def _web_search(
    query: str, max_results: int = 5, *, api_key: str | None = None, **kwargs: Any
) -> str:
    """Search the web for fresh information using Tavily."""
    svc = CrawlerService(api_key=api_key)
    if not svc.available:
        return (
            "Web search is not available — no Tavily API key configured. "
            "Ask the user to configure it in Settings."
        )
    results = await svc.search(
        query=query,
        max_results=min(max_results, 10),
        topic="general",
    )
    if not results:
        return f"No results found for: {query}"
    parts: list[str] = []
    for i, r in enumerate(results, 1):
        parts.append(f"{i}. [{r.title}]({r.url})\n   {r.content}")
        if r.published_at:
            parts.append(f"   Published: {r.published_at}")
    return "\n\n".join(parts)


async def _web_fetch(
    urls: list[str], *, api_key: str | None = None, **kwargs: Any
) -> str:
    """Extract clean text content from web pages using Tavily."""
    svc = CrawlerService(api_key=api_key)
    if not svc.available:
        return (
            "Web fetch is not available — no Tavily API key configured. "
            "Ask the user to configure it in Settings."
        )
    fetched = await svc.extract(urls=urls[:5])
    if not fetched:
        return "No text could be extracted from the specified URLs."
    parts: list[str] = []
    for item in fetched:
        url = item.url or "unknown"
        raw = item.content or ""
        # Truncate per document to keep LLM context reasonable
        snippet = raw[:3000] if raw else "(No text extracted)"
        parts.append(f"=== Content from {url} ===\n{snippet}")
    return "\n\n".join(parts)


# ---------- Tool factory ----------

def build_advisor_tools(
    db: Session,
    *,
    user_id: str,
    goal_id: str | None = None,
    scenario_id: str | None = None,
    include_web_search: bool = False,
    include_web_fetch: bool = False,
) -> list[StructuredTool]:
    """Build tools bound to a specific DB session and goal/scenario context.

    The returned tools are stateless from LangGraph's perspective — they close
    over ``db`` / ``goal_id_context`` / ``scenario_id_context`` so the LLM
    only needs to pass the truly variable arguments (e.g. a different
    scenario_id to compare against). If the LLM omits the id, the tool falls
    back to the conversation's context.

    Session strategy: LangGraph's ReAct agent may execute multiple tool_calls
    concurrently (sync tools run in a thread pool). SQLAlchemy Sessions are
    NOT thread-safe, so concurrent ``db.commit()`` on the shared request-level
    session triggers ``_prepare_impl() is already in progress``. To prevent
    this, **write tools** each open their own short-lived ``SessionLocal()``
    and commit/close within the tool body. **Read tools** continue to use the
    shared ``db`` since they never call ``commit()`` and ``autoflush=False``
    prevents implicit flushes.
    """
    goal_id_context = goal_id
    scenario_id_context = scenario_id
    graph_service = GraphService()
    user_service_config = db.get(UserServiceConfig, user_id)
    user_tavily_key = (
        user_service_config.tavily_api_key if user_service_config else None
    ) or None

    # ---------- Query tools ----------

    @tool("list_pathways", args_schema=ListPathwaysInput)
    def list_pathways(goal_id: str | None = None) -> dict[str, Any]:
        """List all pathways for a goal, including tree fields (node_type, tree_level, parent_pathway_id).

        Use this to understand the decision tree structure when the user asks
        'what are my options' or 'show me my pathways'.
        """
        effective_goal_id = goal_id or goal_id_context
        if not effective_goal_id:
            return {"error": "no_goal_context", "message": "No goal_id provided and no goal context set for this conversation."}
        goal = db.get(Goal, effective_goal_id)
        if goal is None:
            return {"error": "goal_not_found", "goal_id": effective_goal_id}
        if goal.user_id != user_id:
            return {"error": "forbidden", "goal_id": effective_goal_id}
        pathways = list(
            db.scalars(
                select(Pathway)
                .where(
                    Pathway.goal_id == effective_goal_id,
                    Pathway.deleted_at.is_(None),
                )
                .order_by(Pathway.tree_level.asc(), Pathway.display_order.asc())
            )
        )
        pathway_ids = [pathway.id for pathway in pathways]
        scenarios_by_pathway: dict[str, list[str]] = {}
        if pathway_ids:
            linked_scenarios = db.scalars(
                select(Scenario).where(
                    Scenario.pathway_id.in_(pathway_ids),
                    Scenario.deleted_at.is_(None),
                )
            )
            for scenario in linked_scenarios:
                if scenario.pathway_id:
                    scenarios_by_pathway.setdefault(scenario.pathway_id, []).append(
                        scenario.id
                    )
        return {
            "pathways": [
                {
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "node_type": p.node_type,
                    "tree_level": p.tree_level,
                    "display_order": p.display_order,
                    "parent_pathway_id": p.parent_pathway_id,
                    "decision_question": p.decision_question,
                    "evolution_hint": p.evolution_hint,
                    "region": p.region,
                    "description": p.description,
                    "scenario_ids": scenarios_by_pathway.get(p.id, []),
                    "scenario_id": p.scenario_id,
                }
                for p in pathways
            ]
        }

    @tool("list_requirements", args_schema=ListRequirementsInput)
    def list_requirements(pathway_id: str) -> dict[str, Any]:
        """List requirements for a pathway with gap analysis.

        §11.3: requirements are linked via the pathway_requirements M2M table.
        Falls back to the legacy Requirement.pathway_id column when no M2M
        rows exist (pre-migration data).
        """
        pathway = db.get(Pathway, pathway_id)
        goal = db.get(Goal, pathway.goal_id) if pathway is not None else None
        if pathway is None:
            return {"error": "pathway_not_found", "pathway_id": pathway_id}
        if goal is None or goal.user_id != user_id:
            return {"error": "forbidden", "pathway_id": pathway_id}

        # §11.3: query M2M table first
        reqs = list(
            db.scalars(
                select(Requirement)
                .join(
                    pathway_requirements,
                    pathway_requirements.c.requirement_id == Requirement.id,
                )
                .where(pathway_requirements.c.pathway_id == pathway_id)
                .order_by(Requirement.weight.desc())
            )
        )
        if not reqs:
            # Legacy fallback
            reqs = list(
                db.scalars(
                    select(Requirement)
                    .where(Requirement.pathway_id == pathway_id)
                    .order_by(Requirement.weight.desc())
                )
            )
        return {
            "requirements": [
                {
                    "id": r.id,
                    "name": r.name,
                    "type": r.type,
                    "threshold": r.threshold,
                    "current_value": r.current_value,
                    "gap_status": r.gap_status,
                    "gap_delta": r.gap_delta,
                    "weight": r.weight,
                }
                for r in reqs
            ]
        }

    @tool("list_risk_factors", args_schema=ListRiskFactorsInput)
    def list_risk_factors(region: str | None = None) -> dict[str, Any]:
        """List risk factors, optionally filtered by region."""
        # Scope to the user's pathways' regions + global (NULL region) risks.
        # In multi-user mode this prevents seeing another user's domain risks.
        user_pathway_regions = set()
        if goal_id_context:
            user_pathways = list(db.scalars(
                select(Pathway).where(Pathway.goal_id == goal_id_context)
            ))
            user_pathway_regions = {p.region for p in user_pathways if p.region}
        stmt = (
            select(RiskFactor)
            .where(
                RiskFactor.deleted_at.is_(None),
                risk_scope_clause(user_id),
            )
            .order_by(RiskFactor.level.desc())
        )
        if region:
            stmt = stmt.where(RiskFactor.region == region)
        elif user_pathway_regions:
            # Filter to the user's regions + global risks (NULL region)
            stmt = stmt.where(
                or_(RiskFactor.region.in_(user_pathway_regions), RiskFactor.region.is_(None))
            )
        rfs = list(db.scalars(stmt.limit(20)))
        return {
            "risk_factors": [
                {
                    "id": rf.id,
                    "name": rf.name,
                    "type": rf.type,
                    "level": rf.level,
                    "urgency": rf.urgency,
                    "probability": rf.probability,
                    "impact": rf.impact,
                }
                for rf in rfs
            ]
        }

    @tool("list_recent_events", args_schema=ListRecentEventsInput)
    def list_recent_events(limit: int = 10, risk_level: str | None = None) -> dict[str, Any]:
        """List recent events, newest first, optionally filtered by risk level."""
        # User isolation: only show events owned by this user (+ legacy NULL
        # user_id events which are global seed data).
        stmt = select(Event).where(
            or_(Event.user_id == user_id, Event.user_id.is_(None))
        ).order_by(Event.occurred_at.desc().nullslast())
        if risk_level:
            stmt = stmt.where(Event.risk_flag_level == risk_level)
        stmt = stmt.limit(limit)
        events = list(db.scalars(stmt))
        return {
            "events": [
                {
                    "id": e.id,
                    "subject": e.subject,
                    "action": e.action,
                    "object": e.object,
                    "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                    "risk_level": e.risk_flag_level,
                    "risk_type": e.risk_flag_type,
                    "new_value": e.new_value,
                    "old_value": e.old_value,
                }
                for e in events
            ]
        }

    @tool("get_scenario_summary", args_schema=GetScenarioSummaryInput)
    def get_scenario_summary(scenario_id: str | None = None) -> dict[str, Any]:
        """Get a scenario's cached probability / risk summary without re-running."""
        effective_scenario_id = scenario_id or scenario_id_context
        if not effective_scenario_id:
            return {"error": "no_scenario_context", "message": "No scenario_id provided and no scenario context set for this conversation."}
        sc = db.get(Scenario, effective_scenario_id)
        if sc is None:
            return {"error": "scenario_not_found", "scenario_id": effective_scenario_id}
        goal = db.get(Goal, sc.goal_id)
        if goal is None or goal.user_id != user_id:
            return {"error": "forbidden", "scenario_id": effective_scenario_id}
        return {
            "id": sc.id,
            "name": sc.name,
            "status": sc.status,
            "assumptions": sc.assumptions,
            "success_probability": sc.success_probability,
            "risk_score": sc.risk_score,
            "key_risk_factors": sc.key_risk_factors,
            "computed_at": sc.computed_at.isoformat() if sc.computed_at else None,
        }

    @tool("run_scenario_reasoning", args_schema=RunScenarioReasoningInput)
    def run_scenario_reasoning(scenario_id: str | None = None) -> dict[str, Any]:
        """Trigger the reasoning engine (Bayesian + Monte Carlo) on a scenario.

        Use this when the user asks 'what are my chances' or wants a fresh
        probability estimate. Returns the computed success probability and
        key risk factors. Takes ~5-10 seconds.
        """
        effective_scenario_id = scenario_id or scenario_id_context
        if not effective_scenario_id:
            return {"error": "no_scenario_context", "message": "No scenario_id provided and no scenario context set for this conversation."}
        # Use a dedicated session — ScenarioService/ReasoningEngine commit
        # internally multiple times, which would race with other tools on
        # the shared request session.
        with SessionLocal() as session:
            scenario = session.get(Scenario, effective_scenario_id)
            if scenario is None:
                return {
                    "error": "scenario_not_found",
                    "scenario_id": effective_scenario_id,
                }
            goal = session.get(Goal, scenario.goal_id)
            if goal is None or goal.user_id != user_id:
                return {"error": "forbidden", "scenario_id": effective_scenario_id}
            service = ScenarioService(session)
            try:
                run = service.run_reasoning(effective_scenario_id)
                return {
                    "run_id": run.id,
                    "status": run.status,
                    "duration_ms": run.duration_ms,
                    "result": run.result,
                    "error": run.error,
                }
            except Exception as exc:  # noqa: BLE001
                log.error("advisor.tool.run_reasoning_failed", error=str(exc))
                return {"error": "reasoning_failed", "message": str(exc)}

    # ---------- Write tools (ontology mutations) ----------

    @tool("create_goal", args_schema=CreateGoalInput)
    def create_goal(
        title: str,
        description: str | None = None,
        scenario: str = "generic",
        target_date: str | None = None,
    ) -> dict[str, Any]:
        """Create a new top-level goal for the user.

        Use this when the user expresses a new long-horizon intent that isn't
        already tracked (e.g. 'I want to retire to Portugal by 2030'). Returns
        the new goal ID. The advisor should then suggest adding pathways /
        requirements to flesh it out.
        """
        from datetime import date as date_type

        td: date_type | None = None
        if target_date:
            try:
                td = date_type.fromisoformat(target_date)
            except ValueError:
                return {"error": "invalid_date", "detail": "target_date must be YYYY-MM-DD"}

        with SessionLocal() as session:
            lock_goal_identity(session, user_id, title)
            existing = find_equivalent_goal(session, user_id, title)
            if existing is not None:
                return {
                    "goal_id": existing.id,
                    "title": existing.title,
                    "status": existing.status,
                    "reused": True,
                    "graph_synced": True,
                }
            g = Goal(
                user_id=user_id,
                title=title,
                description=description,
                scenario=scenario,
                target_date=td,
                status="active",
            )
            session.add(g)
            session.flush()
            session.commit()
            session.refresh(g)
            result: dict[str, Any] = {
                "goal_id": g.id,
                "title": g.title,
                "status": g.status,
                "reused": False,
                "graph_synced": True,
            }
        try:
            graph_service.upsert_goal(g)
        except Exception as exc:  # noqa: BLE001
            log.warning("advisor.tool.create_goal.graph_failed", error=str(exc))
            result["graph_synced"] = False
            result["graph_sync_error"] = str(exc)
        log.info(
            "advisor.tool.create_goal",
            goal_id=g.id,
            title=title,
            graph_synced=result["graph_synced"],
        )
        return result

    @tool("create_pathway", args_schema=CreatePathwayInput)
    def create_pathway(
        goal_id: str | None = None,
        name: str = "",
        description: str | None = None,
        region: str | None = None,
        parent_pathway_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a pathway (or sub-branch if parent_pathway_id is given) under a goal.

        Use when the user mentions a candidate route they could take, e.g.
        'maybe I should consider the UK Global Talent visa'. Returns the new
        pathway ID.
        """
        effective_goal_id = goal_id or goal_id_context
        if not effective_goal_id:
            return {"error": "no_goal_context", "message": "No goal_id provided and no goal context set for this conversation."}
        with SessionLocal() as session:
            g = session.get(Goal, effective_goal_id)
            if g is None:
                return {"error": "goal_not_found", "goal_id": effective_goal_id}
            if g.user_id != user_id:
                return {"error": "forbidden", "goal_id": effective_goal_id}
            if parent_pathway_id:
                parent = session.get(Pathway, parent_pathway_id)
                if parent is None:
                    return {"error": "parent_pathway_not_found", "parent_pathway_id": parent_pathway_id}
                if parent.goal_id != effective_goal_id:
                    return {
                        "error": "parent_pathway_goal_mismatch",
                        "parent_pathway_id": parent_pathway_id,
                    }
            p = Pathway(
                goal_id=effective_goal_id,
                name=name,
                description=description,
                region=region,
                parent_pathway_id=parent_pathway_id,
                status="candidate",
            )
            session.add(p)
            session.commit()
            session.refresh(p)
            result = {
                "pathway_id": p.id,
                "goal_id": p.goal_id,
                "name": p.name,
                "parent_pathway_id": p.parent_pathway_id,
                "graph_synced": True,
            }
        try:
            graph_service.upsert_pathway(p)
        except Exception as exc:  # noqa: BLE001
            log.warning("advisor.tool.create_pathway.graph_failed", error=str(exc))
            result["graph_synced"] = False
            result["graph_sync_error"] = str(exc)
        log.info(
            "advisor.tool.create_pathway",
            pathway_id=p.id,
            goal_id=goal_id,
            graph_synced=result["graph_synced"],
        )
        return result

    @tool("create_requirement", args_schema=CreateRequirementInput)
    def create_requirement(
        pathway_id: str,
        name: str,
        type: str = "other",
        description: str | None = None,
        threshold: dict[str, Any] | None = None,
        current_value: dict[str, Any] | None = None,
        gap_status: str | None = None,
        weight: float = 1.0,
    ) -> dict[str, Any]:
        """Add a requirement (eligibility criterion) to a pathway.

        Examples: 'IELTS Speaking 6.0' (type=language, threshold={'score':6.0}),
        'Proof of funds CAD 13000' (type=financial).

        §11.3: in addition to setting Requirement.pathway_id (legacy column),
        also inserts a row into the pathway_requirements M2M table so the
        new requirement is linked via the modern association.
        """
        from datetime import datetime
        from datetime import timezone as _tz

        with SessionLocal() as session:
            p = session.get(Pathway, pathway_id)
            if p is None:
                return {"error": "pathway_not_found", "pathway_id": pathway_id}
            goal = session.get(Goal, p.goal_id)
            if goal is None or goal.user_id != user_id:
                return {"error": "forbidden", "pathway_id": pathway_id}
            r = Requirement(
                pathway_id=pathway_id,
                name=name,
                type=type,
                description=description,
                threshold=threshold or {},
                current_value=current_value or {},
                gap_status=gap_status or "unknown",
                weight=weight,
            )
            session.add(r)
            session.flush()
            # §11.3: also insert into the pathway_requirements M2M table so
            # the new requirement is linked via the modern association
            # (not just the legacy pathway_id column). Idempotent: if the row
            # already exists, skip.
            existing = session.execute(
                select(pathway_requirements).where(
                    pathway_requirements.c.pathway_id == pathway_id,
                    pathway_requirements.c.requirement_id == r.id,
                )
            ).first()
            if not existing:
                session.execute(
                    pathway_requirements.insert().values(
                        pathway_id=pathway_id,
                        requirement_id=r.id,
                        is_blocking=True,
                        created_at=datetime.now(_tz.utc).isoformat(),
                    )
                )
            session.commit()
            session.refresh(r)
            result = {
                "requirement_id": r.id,
                "pathway_id": pathway_id,
                "name": r.name,
                "graph_synced": True,
            }
        try:
            graph_service.upsert_requirement(r)
        except Exception as exc:  # noqa: BLE001
            log.warning("advisor.tool.create_requirement.graph_failed", error=str(exc))
            result["graph_synced"] = False
            result["graph_sync_error"] = str(exc)
        return result

    @tool("update_requirement_status", args_schema=UpdateRequirementStatusInput)
    def update_requirement_status(
        requirement_id: str,
        gap_status: str,
        current_value: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a requirement node's status (met/partial/missing) and optionally its current_value."""
        with SessionLocal() as session:
            req = session.get(Requirement, requirement_id)
            if req is None:
                return {"error": "requirement_not_found", "requirement_id": requirement_id}
            owned_pathway = session.scalar(
                select(Pathway)
                .join(Goal, Goal.id == Pathway.goal_id)
                .join(
                    pathway_requirements,
                    pathway_requirements.c.pathway_id == Pathway.id,
                )
                .where(
                    pathway_requirements.c.requirement_id == requirement_id,
                    Goal.user_id == user_id,
                )
                .limit(1)
            )
            if owned_pathway is None and req.pathway_id:
                legacy_pathway = session.get(Pathway, req.pathway_id)
                legacy_goal = (
                    session.get(Goal, legacy_pathway.goal_id)
                    if legacy_pathway is not None
                    else None
                )
                if legacy_goal is not None and legacy_goal.user_id == user_id:
                    owned_pathway = legacy_pathway
            if owned_pathway is None:
                return {"error": "forbidden", "requirement_id": requirement_id}

            req.gap_status = gap_status
            if current_value is not None:
                req.current_value = current_value

            session.add(req)
            session.commit()
            session.refresh(req)

            result: dict[str, Any] = {
                "requirement_id": req.id,
                "name": req.name,
                "gap_status": req.gap_status,
                "current_value": req.current_value,
                "graph_synced": True,
            }
        try:
            graph_service.upsert_requirement(req)
        except Exception as exc:  # noqa: BLE001
            log.warning("advisor.tool.update_requirement_status.graph_failed", error=str(exc))
            result["graph_synced"] = False
            result["graph_sync_error"] = str(exc)

        log.info(
            "advisor.tool.update_requirement_status",
            requirement_id=req.id,
            gap_status=gap_status,
            graph_synced=result["graph_synced"],
        )
        return result

    @tool("create_risk_factor", args_schema=CreateRiskFactorInput)
    def create_risk_factor(
        name: str,
        pathway_id: str | None = None,
        type: str = "other",
        description: str | None = None,
        region: str | None = None,
        level: str = "medium",
        urgency: str = "normal",
        probability: float | None = None,
        impact: float | None = None,
    ) -> dict[str, Any]:
        """Register a potential risk factor the user should watch.

        Use when the user mentions a concern ('what if interest rates stay high?')
        and there isn't already a matching RiskFactor. The new factor will be
        linked into the knowledge graph and trigger personalized risk alerts.
        """
        with SessionLocal() as session:
            effective_pathway_id = pathway_id
            if effective_pathway_id is None and goal_id_context:
                effective_pathway_id = session.scalar(
                    select(Pathway.id)
                    .join(Goal, Goal.id == Pathway.goal_id)
                    .where(
                        Pathway.goal_id == goal_id_context,
                        Goal.user_id == user_id,
                    )
                    .order_by(Pathway.created_at.asc())
                    .limit(1)
                )
            if effective_pathway_id is None:
                return {
                    "error": "no_pathway_context",
                    "message": "A user-owned pathway is required to create a risk factor.",
                }
            adoption = adopt_risk_for_pathway(
                session,
                user_id=user_id,
                pathway_id=effective_pathway_id,
                name=name,
                risk_type=type,
                region=region,
                values={
                    "description": description,
                    "level": level,
                    "urgency": urgency,
                    "probability": probability,
                    "impact": impact,
                },
            )
            rf = adoption.risk_factor
            result = {
                "risk_factor_id": rf.id,
                "name": rf.name,
                "level": rf.level,
                "pathway_id": effective_pathway_id,
                "created": adoption.created,
                "linked": adoption.linked,
                "graph_synced": True,
            }
        try:
            graph_service.upsert_risk_factor(rf)
        except Exception as exc:  # noqa: BLE001
            log.warning("advisor.tool.create_risk_factor.graph_failed", error=str(exc))
            result["graph_synced"] = False
            result["graph_sync_error"] = str(exc)
        log.info(
            "advisor.tool.create_risk_factor",
            rf_id=rf.id,
            name=name,
            graph_synced=result["graph_synced"],
        )
        return result

    # ---------- Memory tools ----------

    @tool("list_memories", args_schema=ListMemoriesInput)
    def list_memories(
        category: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """List the user's stored memories (facts the advisor previously remembered).

        Call this at the start of a conversation or before suggesting a plan,
        so your advice is grounded in what you already know about the user.
        Memories are returned with id, content, category, importance.
        """
        with SessionLocal() as session:
            stmt = select(UserMemory).where(UserMemory.user_id == user_id)
            if category:
                stmt = stmt.where(UserMemory.category == category)
            stmt = stmt.order_by(
                UserMemory.importance.desc(), UserMemory.created_at.desc()
            ).limit(limit)
            mems = list(session.scalars(stmt))
            return {
                "memories": [
                    {
                        "id": m.id,
                        "content": m.content,
                        "category": m.category,
                        "importance": m.importance,
                    }
                    for m in mems
                ],
                "count": len(mems),
            }

    @tool("remember", args_schema=RememberInput)
    def remember(
        content: str, category: str = "other", importance: float = 0.5
    ) -> dict[str, Any]:
        """Persist a new fact about the user to long-term memory.

        Call this whenever the user shares personal context that would be
        useful in future conversations: family situation, health, finances,
        deadlines, constraints, strong preferences. Don't remember trivial
        small talk. If a similar memory already exists, update it rather than
        creating a duplicate.
        """
        with SessionLocal() as session:
            mem = UserMemory(
                user_id=user_id,
                content=content,
                category=category,
                importance=importance,
                source="chat",
            )
            session.add(mem)
            session.commit()
            session.refresh(mem)
            log.info(
                "advisor.tool.remember",
                memory_id=mem.id,
                category=category,
                importance=importance,
            )
            return {
                "memory_id": mem.id,
                "content": mem.content,
                "category": mem.category,
                "importance": mem.importance,
            }

    @tool("forget", args_schema=ForgetIntInput)
    def forget(memory_id: str) -> dict[str, Any]:
        """Delete a previously stored memory by ID.

        Use when the user explicitly says 'forget that' or 'that's no longer
        true'. Returns ok=true on success.
        """
        with SessionLocal() as session:
            mem = session.scalar(
                select(UserMemory).where(
                    UserMemory.id == memory_id, UserMemory.user_id == user_id
                )
            )
            if mem is None:
                return {"ok": False, "error": "memory_not_found", "memory_id": memory_id}
            session.delete(mem)
            session.commit()
            return {"ok": True, "memory_id": memory_id}

    @tool("update_user_profile", args_schema=UpdateUserProfileInput)
    def update_user_profile(
        lifecycle_stage: str | None = None,
        cruising_mode: bool | None = None,
        demographics_update: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update user profile demographics, lifecycle stage, or cruising mode during conversation.

        Use when the user shares details about their current stage, scores, age, or waiting status.
        """
        with SessionLocal() as session:
            user = session.get(UserProfile, user_id)
            if user is None:
                return {"ok": False, "error": "user_not_found"}
            demo = dict(user.demographics or {})
            if lifecycle_stage:
                user.lifecycle_stage = lifecycle_stage
            if cruising_mode is not None:
                user.cruising_mode = cruising_mode
            if demographics_update:
                demo.update(demographics_update)
            user.demographics = demo
            session.add(user)
            session.commit()
            return {
                "ok": True,
                "lifecycle_stage": user.lifecycle_stage,
                "cruising_mode": user.cruising_mode,
                "demographics": user.demographics,
            }

    @tool("create_scenario_branch", args_schema=CreateScenarioBranchInput)
    def create_scenario_branch(
        goal_id: str | None = None,
        pathway_id: str | None = None,
        name: str = "",
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new scenario branch for parallel sandbox推演 during conversation.

        Use when the user considers an alternative pathway or 'what if' scenario.
        """
        effective_goal_id = goal_id or goal_id_context
        if not effective_goal_id:
            return {"error": "no_goal_context", "message": "No goal_id provided and no goal context set for this conversation."}
        with SessionLocal() as session:
            g = session.get(Goal, effective_goal_id)
            if g is None or g.user_id != user_id:
                return {"error": "goal_not_found", "goal_id": effective_goal_id}
            if pathway_id:
                pathway = session.get(Pathway, pathway_id)
                if pathway is None or pathway.goal_id != g.id:
                    return {"error": "pathway_not_found", "pathway_id": pathway_id}
            try:
                effective_pathway_id = resolve_create_pathway_id(
                    session,
                    goal_id=effective_goal_id,
                    pathway_id=pathway_id,
                )
            except HTTPException as exc:
                return {
                    "error": "invalid_pathway" if pathway_id else "pathway_required",
                    "message": str(exc.detail),
                    "goal_id": effective_goal_id,
                }
            sc_svc = ScenarioService(session)
            sc = sc_svc.create_branch(
                goal_id=effective_goal_id,
                pathway_id=effective_pathway_id,
                name=name,
                description=description,
            )
            branch_count = sc_svc.count_active_branches(effective_goal_id)
            return {
                "ok": True,
                "scenario_id": sc.id,
                "pathway_id": sc.pathway_id,
                "name": sc.name,
                "branch_count": branch_count,
            }

    @tool("add_user_source", args_schema=AddUserSourceInput)
    def add_user_source(
        content: str,
        source_type: str = "chat_mention",
        credibility: str = "pending",
    ) -> dict[str, Any]:
        """Add a user-provided information source (text snippet from a consultant email, forum post, etc.).

        The source is persisted immediately and an async structuring task is
        dispatched to extract Events / Relationships / Metrics from the text
        via LLM, so the snippet doesn't just sit as raw_text — it becomes
        part of the knowledge graph.
        """
        with SessionLocal() as session:
            kind = source_type[:32] if source_type else "chat_mention"
            snippet = content[:40].strip().replace("\n", " ") if content else ""
            title = f"User Source ({source_type}): {snippet}" if snippet else f"User Source ({source_type})"

            source = InformationSource(
                user_id=user_id,
                kind=kind,
                title=title[:512],
                raw_text=content,
                credibility=credibility,
                meta={"source_type": source_type, "status": "queued_for_structuring"},
            )
            session.add(source)
            session.commit()
            session.refresh(source)
            source_id = source.id
            source_kind = source.kind

            result: dict[str, Any] = {
                "source_id": source_id,
                "kind": source_kind,
                "credibility": source.credibility,
                "status": "queued_for_structuring",
                "graph_synced": True,
            }
        try:
            graph_service.upsert_source(source)
        except Exception as exc:  # noqa: BLE001
            log.warning("advisor.tool.add_user_source.graph_failed", error=str(exc))
            result["graph_synced"] = False
            result["graph_sync_error"] = str(exc)

        # Fire-and-forget async structuring so the chat isn't blocked by a
        # 5-10s LLM extraction. The structuring service opens its own session.
        def _run_structuring() -> None:
            try:
                from app.services.structuring import StructuringService
                with SessionLocal() as struct_session:
                    svc = StructuringService(struct_session)
                    svc.ingest_text(
                        text=content,
                        title=title[:512],
                        source_kind=kind,
                        user_id=user_id,
                        skip_llm=False,
                    )
                log.info("advisor.tool.add_user_source.structured", source_id=source_id)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "advisor.tool.add_user_source.structuring_failed",
                    source_id=source_id,
                    error=str(exc),
                )

        import threading
        thread = threading.Thread(target=_run_structuring, daemon=True)
        thread.start()

        log.info(
            "advisor.tool.add_user_source",
            source_id=source_id,
            source_type=source_type,
            graph_synced=result["graph_synced"],
        )
        return result

    # ---------- Web tools ----------

    @tool("web_fetch", args_schema=WebFetchInput)
    async def web_fetch(urls: list[str]) -> str:
        """Extract clean text content from one or more web pages. Use this after web_search to read full articles, or when the user provides a URL. Pass up to 5 URLs."""
        return await _web_fetch(urls, api_key=user_tavily_key)

    @tool("web_search", args_schema=WebSearchInput)
    async def web_search(query: str, max_results: int = 5) -> str:
        """Search the web for current information using Tavily. Use this when the user asks about recent events, current facts, news, or anything not in the local knowledge graph. Returns a list of results with title, URL, and snippet."""
        return await _web_search(query, max_results, api_key=user_tavily_key)

    # ---------- Source discovery tools (P1 信源自动发现) ----------

    @tool("propose_sources", args_schema=ProposeSourcesInput)
    async def propose_sources(goal_id: str | None = None, limit: int = 5) -> dict[str, Any]:
        """Discover authoritative information sources for a goal via LLM + Tavily probe.

        Use this when the user wants to find new sources to monitor (official
        gazettes, news, stats APIs, forums) for their goal. Returns a list of
        proposed sources with title, url, kind, relevance, and the reason the
        LLM suggested them. Proposals are persisted as 'proposed' and can be
        accepted/rejected via the /source-proposals API.
        """
        effective_goal_id = goal_id or goal_id_context
        if not effective_goal_id:
            return {"error": "no_goal_context", "message": "No goal_id provided and no goal context set for this conversation."}
        with SessionLocal() as session:
            goal = session.get(Goal, effective_goal_id)
            if goal is None:
                return {"error": "goal_not_found", "goal_id": effective_goal_id}
            pathway = session.scalar(
                select(Pathway)
                .where(Pathway.goal_id == effective_goal_id)
                .order_by(Pathway.created_at.desc())
            )
            service = SourceDiscoveryService(session)
            try:
                proposals = await service.propose_sources(goal, pathway, limit=limit)
            except Exception as exc:  # noqa: BLE001
                log.error("advisor.tool.propose_sources_failed", error=str(exc))
                return {"error": "discovery_failed", "message": str(exc)}
            return {
                "proposals": [
                    {
                        "id": p.id,
                        "title": p.title,
                        "url": p.url,
                        "kind": p.kind,
                        "relevance_score": p.relevance_score,
                        "reason": p.proposed_reason,
                        "credibility_hint": p.credibility_hint,
                    }
                    for p in proposals
                ],
                "count": len(proposals),
            }

    # ---------- Action tools (P0-线B a4) ----------

    @tool("create_action", args_schema=CreateActionInput)
    def create_action(
        title: str,
        description: str | None = None,
        goal_id: str | None = None,
        stage: str | None = None,
        due_at: str | None = None,
        cost: float = 0.5,
        expected_prob_lift: float = 0.0,
        requirement_id: str | None = None,
        risk_factor_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new action for the user.

        Use this when the user agrees to a concrete next step during the chat,
        e.g. 'book IELTS test', 'update resume', or 'gather bank statements'.
        The action is queued on the /actions page; completing it can write
        back to a linked Requirement (mark it 'met') or RiskFactor.
        """
        effective_goal_id = goal_id or goal_id_context
        if not effective_goal_id:
            return {"error": "no_goal_context", "message": "No goal_id provided and no goal context set for this conversation."}

        dd: date_type | None = None
        if due_at:
            try:
                dd = date_type.fromisoformat(due_at)
            except ValueError:
                return {"error": "invalid_date", "detail": "due_at must be YYYY-MM-DD"}

        with SessionLocal() as session:
            g = session.get(Goal, effective_goal_id)
            if g is None:
                return {"error": "goal_not_found", "goal_id": effective_goal_id}
            action = Action(
                user_id=user_id,
                goal_id=effective_goal_id,
                title=title,
                description=description,
                stage=stage,
                status="pending",
                due_at=dd,
                cost=cost,
                expected_prob_lift=expected_prob_lift,
                requirement_id=requirement_id,
                risk_factor_id=risk_factor_id,
                source="agent",
            )
            session.add(action)
            session.commit()
            session.refresh(action)
            roi = (action.expected_prob_lift or 0.0) / max(action.cost or 0.0, 0.01)
            result: dict[str, Any] = {
                "id": action.id,
                "title": action.title,
                "roi": roi,
                "requirement_id": action.requirement_id,
                "risk_factor_id": action.risk_factor_id,
            }
        log.info("advisor.tool.create_action", action_id=action.id, title=title)
        return result

    @tool("complete_action", args_schema=CompleteActionInput)
    def complete_action(action_id: str) -> dict[str, Any]:
        """Mark an action as completed.

        If the action is linked to a Requirement, that requirement's
        gap_status is updated to 'met' so the next scenario probability
        recompute reflects the closure.
        """
        with SessionLocal() as session:
            action = session.get(Action, action_id)
            if action is None:
                return {"error": "action_not_found", "action_id": action_id}
            if action.user_id != user_id:
                return {"error": "forbidden", "action_id": action_id}
            action.status = "completed"
            action.completed_at = datetime.now(timezone.utc).isoformat()
            if action.requirement_id:
                req = session.get(Requirement, action.requirement_id)
                if req is not None:
                    req.gap_status = "met"
                    session.add(req)
            session.add(action)
            session.commit()
            session.refresh(action)
            result = {
                "id": action.id,
                "status": action.status,
                "completed_at": action.completed_at,
            }
        log.info("advisor.tool.complete_action", action_id=action_id)
        return result

    @tool("list_today_actions", args_schema=ListTodayActionsInput)
    def list_today_actions(goal_id: str | None = None) -> dict[str, Any]:
        """List today's pending/in_progress actions sorted by ROI desc.

        Includes overdue actions and daily-recurring actions. Use this at
        the start of a planning conversation to ground advice in what's
        already queued for today.
        """
        today = date_type.today()
        with SessionLocal() as session:
            stmt = (
                select(Action)
                .where(
                    Action.user_id == user_id,
                    Action.deleted_at.is_(None),
                    Action.status.in_(["pending", "in_progress"]),
                    or_(
                        Action.due_at == today,
                        Action.due_at < today,
                        Action.recurrence == "daily",
                    ),
                )
                .order_by(Action.created_at.desc())
            )
            effective_goal_id = goal_id or goal_id_context
            if effective_goal_id:
                stmt = stmt.where(Action.goal_id == effective_goal_id)
            actions = list(session.scalars(stmt))
            actions.sort(
                key=lambda a: (a.expected_prob_lift or 0.0) / max(a.cost or 0.0, 0.01),
                reverse=True,
            )
            return {
                "actions": [
                    {
                        "id": a.id,
                        "title": a.title,
                        "due_at": a.due_at.isoformat() if a.due_at else None,
                        "roi": (a.expected_prob_lift or 0.0) / max(a.cost or 0.0, 0.01),
                        "stage": a.stage,
                        "status": a.status,
                    }
                    for a in actions
                ],
                "count": len(actions),
            }

    # ---------- Discovery & search tools (P1) ----------

    @tool("discover_risks", args_schema=DiscoverRisksInput)
    async def discover_risks(days: int = 14) -> dict[str, Any]:
        """Discover emerging risk themes by clustering recent unlinked events.

        Use this when the user asks 'what risks should I watch?' or wants a
        fresh scan of recent events for emerging patterns. Returns proposed
        risk themes with cluster size, affected goals count, and urgency.
        """
        from app.services.risk_discovery import RiskDiscoveryService

        svc = RiskDiscoveryService(db)
        try:
            proposals = await svc.discover_emerging_risks(
                user_id=user_id, days=days
            )
            return {"proposals": proposals, "count": len(proposals)}
        except Exception as exc:  # noqa: BLE001
            log.error("advisor.tool.discover_risks_failed", error=str(exc))
            return {"error": "discovery_failed", "message": str(exc)}

    @tool("global_search", args_schema=GlobalSearchInput)
    def global_search(query: str, limit: int = 20) -> dict[str, Any]:
        """Search across the user's entire ontology: goals, pathways, requirements, events, sources, and memories.

        Use this when the user asks 'find', 'search', or 'where is' something
        in their knowledge base. Returns matched results with type, id, title,
        and a text snippet.
        """
        from app.services.search import SearchService

        svc = SearchService(db, user_id=user_id)
        return svc.search(query, limit=limit)

    # ---------- Goal management tools ----------

    @tool("list_goals", args_schema=ListGoalsInput)
    def list_goals(status: str | None = None) -> dict[str, Any]:
        """List all the user's goals, optionally filtered by status.

        Use this at the start of a conversation with a multi-goal user, or
        when the user wants to switch context to a different goal.
        """
        stmt = select(Goal).where(
            Goal.user_id == user_id,
            Goal.deleted_at.is_(None),
        )
        if status:
            stmt = stmt.where(Goal.status == status)
        stmt = stmt.order_by(Goal.created_at.desc())
        goals = list(db.scalars(stmt))
        return {
            "goals": [
                {
                    "id": g.id,
                    "title": g.title,
                    "scenario": g.scenario,
                    "status": g.status,
                    "target_date": g.target_date.isoformat() if g.target_date else None,
                }
                for g in goals
            ],
            "count": len(goals),
        }

    @tool("update_goal", args_schema=UpdateGoalInput)
    def update_goal(
        goal_id: str,
        title: str | None = None,
        description: str | None = None,
        target_date: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Update a goal's title, description, target date, or status."""
        with SessionLocal() as session:
            g = session.get(Goal, goal_id)
            if g is None:
                return {"error": "goal_not_found", "goal_id": goal_id}
            if g.user_id != user_id:
                return {"error": "forbidden", "goal_id": goal_id}
            if title is not None:
                g.title = title
            if description is not None:
                g.description = description
            if target_date is not None:
                try:
                    g.target_date = date_type.fromisoformat(target_date)
                except ValueError:
                    return {"error": "invalid_date", "detail": "target_date must be YYYY-MM-DD"}
            if status is not None:
                g.status = status
            session.add(g)
            session.commit()
            session.refresh(g)
            return {
                "goal_id": g.id,
                "title": g.title,
                "status": g.status,
                "target_date": g.target_date.isoformat() if g.target_date else None,
            }

    @tool("archive_goal", args_schema=ArchiveGoalInput)
    def archive_goal(goal_id: str) -> dict[str, Any]:
        """Archive (soft-delete) a goal the user no longer pursues.

        Sets status to 'abandoned'. The goal and its pathways/requirements
        remain in the knowledge graph for historical analysis but are
        excluded from active dashboards.
        """
        with SessionLocal() as session:
            g = session.get(Goal, goal_id)
            if g is None:
                return {"error": "goal_not_found", "goal_id": goal_id}
            if g.user_id != user_id:
                return {"error": "forbidden", "goal_id": goal_id}
            g.status = "abandoned"
            session.add(g)
            session.commit()
            return {"goal_id": g.id, "status": g.status, "archived": True}

    @tool("update_risk_factor", args_schema=UpdateRiskFactorInput)
    def update_risk_factor(
        risk_factor_id: str,
        level: str | None = None,
        urgency: str | None = None,
        probability: float | None = None,
        impact: float | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Update a risk factor's level, urgency, probability, impact, or description.

        Use when the user says a risk has been resolved (set level='low') or
        escalated (set level='high', urgency='urgent').
        """
        with SessionLocal() as session:
            rf = session.get(RiskFactor, risk_factor_id)
            if rf is None:
                return {"error": "risk_factor_not_found", "risk_factor_id": risk_factor_id}
            if rf.user_id != user_id:
                return {"error": "forbidden", "risk_factor_id": risk_factor_id}
            if level is not None:
                rf.level = level
            if urgency is not None:
                rf.urgency = urgency
            if probability is not None:
                rf.probability = probability
            if impact is not None:
                rf.impact = impact
            if description is not None:
                rf.description = description
            session.add(rf)
            session.commit()
            session.refresh(rf)
            result: dict[str, Any] = {
                "risk_factor_id": rf.id,
                "name": rf.name,
                "level": rf.level,
                "urgency": rf.urgency,
                "graph_synced": True,
            }
        try:
            graph_service.upsert_risk_factor(rf)
        except Exception as exc:  # noqa: BLE001
            result["graph_synced"] = False
            result["graph_sync_error"] = str(exc)
        return result

    @tool("compare_scenarios", args_schema=CompareScenariosInput)
    def compare_scenarios(scenario_ids: list[str]) -> dict[str, Any]:
        """Compare 2-5 scenarios side-by-side: probabilities, key risks, requirement gaps.

        Returns a structured comparison so the user can see which path has
        the highest success probability and what the trade-offs are.
        """
        scenarios = []
        for sid in scenario_ids:
            sc = db.get(Scenario, sid)
            if sc is None:
                return {"error": "scenario_not_found", "scenario_id": sid}
            goal = db.get(Goal, sc.goal_id)
            if goal is None or goal.user_id != user_id:
                return {"error": "forbidden", "scenario_id": sid}
            scenarios.append(sc)
        comparison = []
        for sc in scenarios:
            sp = sc.success_probability or {}
            comparison.append({
                "scenario_id": sc.id,
                "name": sc.name,
                "status": sc.status,
                "p50": sp.get("p50"),
                "p10": sp.get("p10"),
                "p90": sp.get("p90"),
                "risk_score": sc.risk_score,
                "key_risk_factors": sc.key_risk_factors,
                "computed_at": sc.computed_at.isoformat() if sc.computed_at else None,
            })
        # Sort by p50 descending so the best option is first
        comparison.sort(key=lambda x: x.get("p50") or 0, reverse=True)
        return {"comparison": comparison, "count": len(comparison)}

    # ---------- Source & discovery tools ----------

    @tool("ingest_url", args_schema=IngestUrlInput)
    async def ingest_url(url: str, source_type: str = "public") -> dict[str, Any]:
        """Fetch a URL and structure its content into the knowledge graph.

        Combines web_fetch + structuring in one step: extracts text from the
        URL via Tavily, then runs LLM extraction to produce Events /
        Relationships. Use when the user shares a link to an article,
        announcement, or official page.
        """
        if not user_tavily_key:
            return {"error": "no_tavily_key", "message": "Web fetch requires a Tavily API key. Ask the user to configure it in Settings."}
        text = await _web_fetch([url], api_key=user_tavily_key)
        if not text or text.startswith("No text"):
            return {"error": "fetch_failed", "url": url}
        with SessionLocal() as session:
            from app.services.structuring import StructuringService
            svc = StructuringService(session)
            try:
                source, extraction = svc.ingest_text(
                    text=text[:8000],
                    title=url[:200],
                    source_kind=source_type,
                    url=url,
                    user_id=user_id,
                )
                atom_count = len(extraction.events) + len(extraction.relationships) if extraction else 0
                return {
                    "source_id": source.id,
                    "url": url,
                    "atoms_extracted": atom_count,
                    "structured": extraction is not None,
                }
            except Exception as exc:  # noqa: BLE001
                log.error("advisor.tool.ingest_url_failed", url=url, error=str(exc))
                return {"error": "structuring_failed", "message": str(exc)}

    @tool("list_source_proposals", args_schema=ListSourceProposalsInput)
    def list_source_proposals(
        goal_id: str | None = None, status: str | None = None
    ) -> dict[str, Any]:
        """List source proposals for review (pending / accepted / rejected)."""
        from app.models.source_proposal import SourceProposal
        with SessionLocal() as session:
            stmt = select(SourceProposal).where(SourceProposal.user_id == user_id)
            effective_goal_id = goal_id or goal_id_context
            if effective_goal_id:
                stmt = stmt.where(SourceProposal.goal_id == effective_goal_id)
            if status:
                stmt = stmt.where(SourceProposal.status == status)
            stmt = stmt.order_by(SourceProposal.relevance_score.desc()).limit(20)
            proposals = list(session.scalars(stmt))
            return {
                "proposals": [
                    {
                        "id": p.id,
                        "title": p.title,
                        "url": p.url,
                        "kind": p.kind,
                        "relevance_score": p.relevance_score,
                        "credibility_hint": p.credibility_hint,
                        "status": p.status,
                        "reason": p.proposed_reason,
                    }
                    for p in proposals
                ],
                "count": len(proposals),
            }

    @tool("accept_source_proposal", args_schema=AcceptSourceProposalInput)
    def accept_source_proposal(proposal_id: str) -> dict[str, Any]:
        """Accept a proposed source — creates an InformationSource with auto-refresh enabled."""
        from app.services.source_discovery import SourceDiscoveryService
        with SessionLocal() as session:
            svc = SourceDiscoveryService(session)
            try:
                source = svc.accept_proposal(proposal_id, user_id)
                return {
                    "source_id": source.id,
                    "title": source.title,
                    "credibility": source.credibility,
                    "auto_refresh": source.auto_refresh,
                }
            except Exception as exc:  # noqa: BLE001
                return {"error": "accept_failed", "message": str(exc)}

    @tool("reject_source_proposal", args_schema=RejectSourceProposalInput)
    def reject_source_proposal(proposal_id: str) -> dict[str, Any]:
        """Reject a proposed source."""
        from app.services.source_discovery import SourceDiscoveryService
        with SessionLocal() as session:
            svc = SourceDiscoveryService(session)
            try:
                proposal = svc.reject_proposal(proposal_id, user_id)
                return {"proposal_id": proposal.id, "status": proposal.status}
            except Exception as exc:  # noqa: BLE001
                return {"error": "reject_failed", "message": str(exc)}

    @tool("list_conflicts", args_schema=EmptyInput)
    def list_conflicts() -> dict[str, Any]:
        """Find cross-source conflicts: same fact, different values from different sources.

        Returns a list of conflict groups with the conflicting values and
        source credibility scores so the user (or you) can decide which to trust.
        """
        from app.services.cross_validation import CrossValidationService
        svc = CrossValidationService(db, user_id)
        return {"conflicts": svc.detect_conflicts()}

    @tool("resolve_conflict", args_schema=ResolveConflictInput)
    def resolve_conflict(
        subject_id: str, predicate: str, winning_source_id: str
    ) -> dict[str, Any]:
        """Resolve a cross-source conflict by picking the authoritative source.

        Boosts the winning source's credibility and reduces the losing sources'.
        Creates a 'conflicts_with' relationship edge for audit trail.
        """
        from app.services.cross_validation import CrossValidationService
        svc = CrossValidationService(db, user_id)
        try:
            return svc.resolve_conflict(subject_id, predicate, winning_source_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": "resolve_failed", "message": str(exc)}

    # ---------- Profile & changes tools ----------

    @tool("get_user_profile", args_schema=EmptyInput)
    def get_user_profile() -> dict[str, Any]:
        """Get the user's full profile: demographics, lifecycle stage, cruising mode."""
        user = db.get(UserProfile, user_id)
        if user is None:
            return {"error": "user_not_found"}
        return {
            "user_id": user.id,
            "demographics": user.demographics,
            "lifecycle_stage": user.lifecycle_stage,
            "cruising_mode": user.cruising_mode,
            "risk_tolerance": user.risk_tolerance,
        }

    @tool("get_changes_summary", args_schema=EmptyInput)
    def get_changes_summary() -> dict[str, Any]:
        """Get a summary of what changed since the user's last visit.

        Returns counts of new events, sources, actions, risk factors, plus
        any high-risk events that appeared. Use when the user asks 'what's new?'
        or at the start of a follow-up conversation.
        """
        from app.models.llm_config import AppConfig
        from app.services.changes_summary import ChangesSummaryService
        # Read last-visit timestamp from AppConfig (stored by the API layer).
        last_visit_row = db.scalar(
            select(AppConfig).where(AppConfig.key == f"user_last_visit:{user_id}")
        )
        if last_visit_row and last_visit_row.value:
            try:
                from datetime import datetime as _dt
                since = _dt.fromisoformat(last_visit_row.value)
            except (ValueError, TypeError):
                from datetime import datetime as _dt
                from datetime import timedelta as _td
                since = _dt.now(timezone.utc) - _td(days=7)
        else:
            from datetime import datetime as _dt
            from datetime import timedelta as _td
            since = _dt.now(timezone.utc) - _td(days=7)
        svc = ChangesSummaryService(db, user_id)
        return svc.get_summary(since)

    # ---------- Action detail / update tools ----------

    @tool("get_action_detail", args_schema=GetActionDetailInput)
    def get_action_detail(action_id: str) -> dict[str, Any]:
        """Get full details of a single action by ID."""
        with SessionLocal() as session:
            action = session.get(Action, action_id)
            if action is None:
                return {"error": "action_not_found", "action_id": action_id}
            if action.user_id != user_id:
                return {"error": "forbidden", "action_id": action_id}
            roi = (action.expected_prob_lift or 0.0) / max(action.cost or 0.0, 0.01)
            return {
                "id": action.id,
                "title": action.title,
                "description": action.description,
                "status": action.status,
                "stage": action.stage,
                "due_at": action.due_at.isoformat() if action.due_at else None,
                "recurrence": action.recurrence,
                "cost": action.cost,
                "expected_prob_lift": action.expected_prob_lift,
                "roi": roi,
                "requirement_id": action.requirement_id,
                "risk_factor_id": action.risk_factor_id,
                "scenario_id": action.scenario_id,
                "completed_at": action.completed_at,
                "source": action.source,
            }

    @tool("update_action", args_schema=UpdateActionInput)
    def update_action(
        action_id: str,
        title: str | None = None,
        description: str | None = None,
        stage: str | None = None,
        due_at: str | None = None,
        status: str | None = None,
        cost: float | None = None,
        expected_prob_lift: float | None = None,
    ) -> dict[str, Any]:
        """Update an action's fields (title, due_at, stage, status, cost, etc.)."""
        with SessionLocal() as session:
            action = session.get(Action, action_id)
            if action is None:
                return {"error": "action_not_found", "action_id": action_id}
            if action.user_id != user_id:
                return {"error": "forbidden", "action_id": action_id}
            if title is not None:
                action.title = title
            if description is not None:
                action.description = description
            if stage is not None:
                action.stage = stage
            if due_at is not None:
                try:
                    action.due_at = date_type.fromisoformat(due_at)
                except ValueError:
                    return {"error": "invalid_date", "detail": "due_at must be YYYY-MM-DD"}
            if status is not None:
                action.status = status
                if status == "completed":
                    action.completed_at = datetime.now(timezone.utc).isoformat()
            if cost is not None:
                action.cost = cost
            if expected_prob_lift is not None:
                action.expected_prob_lift = expected_prob_lift
            session.add(action)
            session.commit()
            session.refresh(action)
            roi = (action.expected_prob_lift or 0.0) / max(action.cost or 0.0, 0.01)
            return {
                "id": action.id,
                "title": action.title,
                "status": action.status,
                "due_at": action.due_at.isoformat() if action.due_at else None,
                "roi": roi,
            }

    # ---------- Decision-tree tools (§11.3 self-growing tree) ----------

    @tool("list_decision_tree", args_schema=ListDecisionTreeInput)
    def list_decision_tree(goal_id: str | None = None) -> dict[str, Any]:
        """Return the full decision tree for a goal as a nested structure.

        Use this when the user asks 'what are my options', 'show me my
        decision tree', or wants to see all branches at once. Each node
        includes node_type, tree_level, status, evolution_hint, requirements,
        risk_factors, and the latest scenario probability (p50/p10/p90).
        """
        effective_goal_id = goal_id or goal_id_context
        if not effective_goal_id:
            return {"error": "no_goal_context", "message": "No goal_id provided and no goal context set for this conversation."}
        # Reuse the API module's tree builder so the agent sees the exact
        # same shape the frontend gets. Imported lazily to avoid a cross-layer
        # import at module load time.
        from app.api.decision_tree import _build_tree_node, _load_tree_indexes

        goal = db.get(Goal, effective_goal_id)
        if goal is None:
            return {"error": "goal_not_found", "goal_id": effective_goal_id}
        if goal.user_id != user_id:
            return {"error": "forbidden", "goal_id": effective_goal_id}

        (
            children_by_parent,
            requirements_by_pathway,
            risk_factors_by_pathway,
        ) = _load_tree_indexes(db, goal.id, goal.user_id)
        root_pathways = list(
            db.scalars(
                select(Pathway)
                .where(
                    Pathway.goal_id == goal.id,
                    Pathway.parent_pathway_id.is_(None),
                )
                .order_by(
                    Pathway.tree_level.asc(),
                    Pathway.display_order.asc(),
                    Pathway.created_at.asc(),
                )
            )
        )
        if not root_pathways:
            first = db.scalar(
                select(Pathway)
                .where(Pathway.goal_id == goal.id)
                .order_by(Pathway.created_at.asc())
            )
            if first is not None:
                root_pathways = [first]
        roots = [
            _build_tree_node(
                p,
                db,
                children_by_parent,
                requirements_by_pathway,
                risk_factors_by_pathway,
            )
            for p in root_pathways
        ]
        return {
            "goal_id": goal.id,
            "goal_title": goal.title,
            "roots": roots,
        }

    @tool("grow_tree", args_schema=GrowTreeInput)
    def grow_tree(
        parent_pathway_id: str,
        name: str,
        description: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Manually add a child branch to a pathway (status='confirmed').

        Use when the user mentions a specific route they want to add to the
        tree, e.g. 'add a Singapore Tech.Pass option under my APAC pathway'.
        Creates a Scenario for the new branch if the parent has one.
        """
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        with SessionLocal() as session:
            parent = session.get(Pathway, parent_pathway_id)
            if parent is None:
                return {"error": "parent_pathway_not_found", "parent_pathway_id": parent_pathway_id}
            goal = session.get(Goal, parent.goal_id)
            if goal is None or goal.user_id != user_id:
                return {"error": "forbidden", "parent_pathway_id": parent_pathway_id}

            new_pathway = Pathway(
                goal_id=parent.goal_id,
                name=name,
                description=description,
                region=region or parent.region,
                status="confirmed",
                parent_pathway_id=parent.id,
                node_type="branch",
                tree_level=(parent.tree_level or 0) + 1,
                display_order=0,
            )
            session.add(new_pathway)
            session.flush()

            if parent.scenario_id:
                parent_sc = session.get(Scenario, parent.scenario_id)
                new_sc = Scenario(
                    goal_id=parent.goal_id,
                    pathway_id=new_pathway.id,
                    name=f"{name} (branch)",
                    description=description,
                    status="active",
                    parent_scenario_id=parent.scenario_id,
                    assumptions=dict(parent_sc.assumptions or {}) if parent_sc else {},
                    impact_threshold=0.05,
                )
                session.add(new_sc)
                session.flush()
                new_pathway.scenario_id = new_sc.id
                session.add(new_pathway)

            # Link parent requirements + risk_factors (M2M inheritance)
            now_iso = _dt.now(_tz.utc).isoformat()
            parent_req_ids = {
                r.id for r in session.scalars(
                    select(Requirement).join(
                        pathway_requirements,
                        pathway_requirements.c.requirement_id == Requirement.id,
                    ).where(pathway_requirements.c.pathway_id == parent.id)
                )
            }
            if not parent_req_ids:
                parent_req_ids = {
                    r.id for r in session.scalars(
                        select(Requirement).where(Requirement.pathway_id == parent.id)
                    )
                }
            for req_id in parent_req_ids:
                session.execute(
                    pathway_requirements.insert().values(
                        pathway_id=new_pathway.id,
                        requirement_id=req_id,
                        is_blocking=True,
                        created_at=now_iso,
                    )
                )

            parent_rf_ids = {
                rf.id for rf in session.scalars(
                    select(RiskFactor).join(
                        pathway_risk_factors,
                        pathway_risk_factors.c.risk_factor_id == RiskFactor.id,
                    ).where(
                        pathway_risk_factors.c.pathway_id == parent.id,
                        RiskFactor.deleted_at.is_(None),
                        risk_scope_clause(user_id),
                    )
                )
            }
            for rf_id in parent_rf_ids:
                session.execute(
                    pathway_risk_factors.insert().values(
                        pathway_id=new_pathway.id,
                        risk_factor_id=rf_id,
                        created_at=now_iso,
                    )
                )

            session.commit()
            session.refresh(new_pathway)
            result = {
                "id": new_pathway.id,
                "name": new_pathway.name,
                "status": new_pathway.status,
                "node_type": new_pathway.node_type,
                "tree_level": new_pathway.tree_level,
                "parent_pathway_id": new_pathway.parent_pathway_id,
                "scenario_id": new_pathway.scenario_id,
                "region": new_pathway.region,
            }
        log.info(
            "advisor.tool.grow_tree",
            parent_pathway_id=parent_pathway_id,
            new_pathway_id=result["id"],
        )
        return result

    @tool("evolve_tree", args_schema=EvolveTreeInput)
    def evolve_tree(pathway_id: str) -> dict[str, Any]:
        """Run the LLM+math evolution pipeline on a pathway (自生长).

        The LLM proposes 2-5 candidate child branches based on the user's
        goal/requirements/risks/memories; each candidate is then scored by
        the Bayesian + Monte Carlo reasoning engine. Branches with P50 < 5%
        are filtered out. Returns the surviving predicted branches with
        their probability data.

        Use when the user says 'explore new possibilities', 'what are my
        options from here', or 'grow my tree'. Takes ~10-30s.
        """
        with SessionLocal() as session:
            pathway = session.get(Pathway, pathway_id)
            if pathway is None:
                return {"error": "pathway_not_found", "pathway_id": pathway_id}
            goal = session.get(Goal, pathway.goal_id)
            if goal is None or goal.user_id != user_id:
                return {"error": "forbidden", "pathway_id": pathway_id}

            # Minimal CurrentUser-like object — TreeEvolutionService only
            # needs .id for scoping memories/events.
            fake_user = type("U", (), {"id": user_id, "role": "user"})()
            service = TreeEvolutionService(session)
            try:
                branches = service.evolve_branch(pathway, fake_user)
            except Exception as exc:  # noqa: BLE001
                log.error("advisor.tool.evolve_tree_failed", error=str(exc))
                return {"error": "evolution_failed", "message": str(exc)}
        log.info(
            "advisor.tool.evolve_tree",
            pathway_id=pathway_id,
            branches=len(branches),
        )
        return {
            "parent_pathway_id": pathway_id,
            "predicted_branches": branches,
            "count": len(branches),
        }

    @tool("confirm_branch", args_schema=ConfirmBranchInput)
    def confirm_branch(pathway_id: str) -> dict[str, Any]:
        """Change a pathway's status from 'predicted' to 'confirmed'.

        Use when the user accepts an LLM-predicted branch as a real option,
        e.g. 'yeah the UK option looks good' or 'I'll consider that one'.
        """
        with SessionLocal() as session:
            pathway = session.get(Pathway, pathway_id)
            if pathway is None:
                return {"error": "pathway_not_found", "pathway_id": pathway_id}
            goal = session.get(Goal, pathway.goal_id)
            if goal is None or goal.user_id != user_id:
                return {"error": "forbidden", "pathway_id": pathway_id}
            if pathway.status != "predicted":
                return {
                    "error": "invalid_status",
                    "message": f"Pathway is in status '{pathway.status}', can only confirm 'predicted' branches.",
                    "pathway_id": pathway_id,
                }
            pathway.status = "confirmed"
            session.add(pathway)
            session.commit()
            session.refresh(pathway)
            result = {
                "id": pathway.id,
                "name": pathway.name,
                "status": pathway.status,
                "node_type": pathway.node_type,
                "tree_level": pathway.tree_level,
            }
        log.info("advisor.tool.confirm_branch", pathway_id=pathway_id)
        return result

    @tool("select_branch", args_schema=SelectBranchInput)
    def select_branch(
        pathway_id: str, abandon_siblings: bool = False
    ) -> dict[str, Any]:
        """Mark a branch as 'in_progress' (user is actively executing this path).

        Optionally abandon sibling branches at the same tree_level so the
        user's focus is clear. Use when the user says 'I'll go with X' or
        'I'm committing to this path'.
        """
        with SessionLocal() as session:
            pathway = session.get(Pathway, pathway_id)
            if pathway is None:
                return {"error": "pathway_not_found", "pathway_id": pathway_id}
            goal = session.get(Goal, pathway.goal_id)
            if goal is None or goal.user_id != user_id:
                return {"error": "forbidden", "pathway_id": pathway_id}
            if pathway.status not in ("confirmed", "predicted", "selected", "candidate"):
                return {
                    "error": "invalid_status",
                    "message": f"Pathway is in status '{pathway.status}', cannot select.",
                    "pathway_id": pathway_id,
                }
            pathway.status = "in_progress"
            session.add(pathway)

            abandoned_siblings: list[str] = []
            if abandon_siblings and pathway.parent_pathway_id:
                siblings = list(
                    session.scalars(
                        select(Pathway).where(
                            Pathway.parent_pathway_id == pathway.parent_pathway_id,
                            Pathway.id != pathway.id,
                            Pathway.status.in_(
                                ["predicted", "confirmed", "candidate", "selected"]
                            ),
                        )
                    )
                )
                for sib in siblings:
                    sib.status = "abandoned"
                    session.add(sib)
                    abandoned_siblings.append(sib.id)

            session.commit()
            session.refresh(pathway)
            result = {
                "id": pathway.id,
                "name": pathway.name,
                "status": pathway.status,
                "node_type": pathway.node_type,
                "tree_level": pathway.tree_level,
                "abandoned_siblings": abandoned_siblings,
            }
        log.info(
            "advisor.tool.select_branch",
            pathway_id=pathway_id,
            abandoned_siblings=abandoned_siblings,
        )
        return result

    @tool("abandon_branch", args_schema=AbandonBranchInput)
    def abandon_branch(pathway_id: str) -> dict[str, Any]:
        """Mark a branch as 'abandoned' (user gave up on this path).

        Use when the user says 'I'm giving up on X', 'forget the UK option',
        or 'drop that branch'.
        """
        with SessionLocal() as session:
            pathway = session.get(Pathway, pathway_id)
            if pathway is None:
                return {"error": "pathway_not_found", "pathway_id": pathway_id}
            goal = session.get(Goal, pathway.goal_id)
            if goal is None or goal.user_id != user_id:
                return {"error": "forbidden", "pathway_id": pathway_id}
            pathway.status = "abandoned"
            session.add(pathway)
            session.commit()
            session.refresh(pathway)
            result = {
                "id": pathway.id,
                "name": pathway.name,
                "status": pathway.status,
                "node_type": pathway.node_type,
                "tree_level": pathway.tree_level,
            }
        log.info("advisor.tool.abandon_branch", pathway_id=pathway_id)
        return result

    tools: list[StructuredTool] = [
        # Query
        list_goals,
        list_pathways,
        list_requirements,
        list_risk_factors,
        list_recent_events,
        get_scenario_summary,
        run_scenario_reasoning,
        compare_scenarios,
        get_user_profile,
        list_memories,
        get_changes_summary,
        global_search,
        # Write (ontology)
        create_goal,
        update_goal,
        archive_goal,
        create_pathway,
        create_requirement,
        update_requirement_status,
        create_risk_factor,
        update_risk_factor,
        update_user_profile,
        create_scenario_branch,
        add_user_source,
        # Actions
        create_action,
        complete_action,
        list_today_actions,
        get_action_detail,
        update_action,
        # Source & discovery
        ingest_url,
        propose_sources,
        list_source_proposals,
        accept_source_proposal,
        reject_source_proposal,
        discover_risks,
        list_conflicts,
        resolve_conflict,
        # Memory
        remember,
        forget,
        # Decision tree (§11.3 self-growing tree)
        list_decision_tree,
        grow_tree,
        evolve_tree,
        confirm_branch,
        select_branch,
        abandon_branch,
    ]
    tools.extend(
        build_action_calendar_tools(
            user_id=user_id, goal_id_context=goal_id_context
        )
    )
    if include_web_search:
        tools.append(web_search)
    if include_web_fetch:
        tools.append(web_fetch)
    return tools


__all__ = ["build_advisor_tools"]
