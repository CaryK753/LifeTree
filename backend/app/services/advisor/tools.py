"""Tools exposed to the AI advisor LangGraph agent.

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

from typing import Any

from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import get_default_user
from app.models.event import Event, InformationSource
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.models.memory import UserMemory
from app.models.scenario import Scenario
from app.models.user import UserProfile
from app.services.crawler import CrawlerService
from app.services.graph import GraphService
from app.services.scenarios import ScenarioService

log = get_logger(__name__)


# ---------- Tool input schemas ----------

class ListPathwaysInput(BaseModel):
    goal_id: str = Field(..., description="Goal ID to list pathways for")


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
    scenario_id: str = Field(..., description="Scenario ID to run reasoning on")


class GetScenarioSummaryInput(BaseModel):
    scenario_id: str = Field(..., description="Scenario ID to summarize")


# --- Write tools (create ontology entities) ---

class CreateGoalInput(BaseModel):
    title: str = Field(..., description="Short goal title, e.g. 'Get Canadian PR by 2029'")
    description: str | None = Field(None, description="Longer description / motivation")
    scenario: str = Field("generic", description="Scenario tag like 'fsw' or 'uk-study'")
    target_date: str | None = Field(
        None, description="ISO date string (YYYY-MM-DD) or null"
    )


class CreatePathwayInput(BaseModel):
    goal_id: str = Field(..., description="Parent goal ID")
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


async def _web_search(input: WebSearchInput) -> str:
    """Search the web for fresh information using Tavily."""
    svc = CrawlerService()
    if not svc.available:
        return (
            "Web search is not available — no Tavily API key configured. "
            "Ask the user to configure it in Settings."
        )
    results = await svc.search(
        query=input.query,
        max_results=min(input.max_results, 10),
        topic="general",
    )
    if not results:
        return f"No results found for: {input.query}"
    parts: list[str] = []
    for i, r in enumerate(results, 1):
        parts.append(f"{i}. [{r.title}]({r.url})\n   {r.content}")
        if r.published_at:
            parts.append(f"   Published: {r.published_at}")
    return "\n\n".join(parts)


async def _web_fetch(input: WebFetchInput) -> str:
    """Extract clean text content from web pages using Tavily."""
    svc = CrawlerService()
    if not svc.available:
        return "Web fetch is not available — no Tavily API key configured."
    urls = input.urls[:5]  # cap at 5
    results = await svc.extract(urls)
    if not results:
        return f"Could not extract content from: {', '.join(urls)}"
    parts: list[str] = []
    for r in results:
        content = (r.content or "")[:4000]  # cap per-page content
        parts.append(f"--- {r.url} ---\n{content}")
    return "\n\n".join(parts)


# ---------- Tool factory ----------

def build_advisor_tools(
    db: Session,
    *,
    goal_id: str | None = None,
    scenario_id: str | None = None,
) -> list[StructuredTool]:
    """Build tools bound to a specific DB session and goal/scenario context.

    The returned tools are stateless from LangGraph's perspective — they close
    over ``db`` / ``goal_id`` / ``scenario_id`` so the LLM only needs to pass
    the truly variable arguments (e.g. a different scenario_id to compare
    against).
    """
    graph_service = GraphService()

    # ---------- Query tools ----------

    @tool("list_pathways", args_schema=ListPathwaysInput)
    def list_pathways(goal_id: str) -> dict[str, Any]:
        """List all pathways for a goal, including their requirement counts."""
        pathways = list(db.scalars(select(Pathway).where(Pathway.goal_id == goal_id)))
        return {
            "pathways": [
                {
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "region": p.region,
                    "description": p.description,
                }
                for p in pathways
            ]
        }

    @tool("list_requirements", args_schema=ListRequirementsInput)
    def list_requirements(pathway_id: str) -> dict[str, Any]:
        """List requirements for a pathway with gap analysis."""
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
        stmt = select(RiskFactor).order_by(RiskFactor.level.desc())
        if region:
            stmt = stmt.where(RiskFactor.region == region)
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
        stmt = select(Event).order_by(Event.occurred_at.desc().nullslast())
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
    def get_scenario_summary(scenario_id: str) -> dict[str, Any]:
        """Get a scenario's cached probability / risk summary without re-running."""
        sc = db.get(Scenario, scenario_id)
        if sc is None:
            return {"error": "scenario_not_found", "scenario_id": scenario_id}
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
    def run_scenario_reasoning(scenario_id: str) -> dict[str, Any]:
        """Trigger the reasoning engine (Bayesian + Monte Carlo) on a scenario.

        Use this when the user asks 'what are my chances' or wants a fresh
        probability estimate. Returns the computed success probability and
        key risk factors. Takes ~5-10 seconds.
        """
        service = ScenarioService(db)
        try:
            run = service.run_reasoning(scenario_id)
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

        user = get_default_user(db)
        td: date_type | None = None
        if target_date:
            try:
                td = date_type.fromisoformat(target_date)
            except ValueError:
                return {"error": "invalid_date", "detail": "target_date must be YYYY-MM-DD"}

        g = Goal(
            user_id=user.id,
            title=title,
            description=description,
            scenario=scenario,
            target_date=td,
            status="draft",
        )
        db.add(g)
        db.flush()
        db.commit()
        db.refresh(g)
        result: dict[str, Any] = {
            "goal_id": g.id,
            "title": g.title,
            "status": g.status,
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
        goal_id: str,
        name: str,
        description: str | None = None,
        region: str | None = None,
        parent_pathway_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a pathway (or sub-branch if parent_pathway_id is given) under a goal.

        Use when the user mentions a candidate route they could take, e.g.
        'maybe I should consider the UK Global Talent visa'. Returns the new
        pathway ID.
        """
        g = db.get(Goal, goal_id)
        if g is None:
            return {"error": "goal_not_found", "goal_id": goal_id}
        p = Pathway(
            goal_id=goal_id,
            name=name,
            description=description,
            region=region,
            parent_pathway_id=parent_pathway_id,
            status="candidate",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
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
        """
        p = db.get(Pathway, pathway_id)
        if p is None:
            return {"error": "pathway_not_found", "pathway_id": pathway_id}
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
        db.add(r)
        db.commit()
        db.refresh(r)
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

    @tool("create_risk_factor", args_schema=CreateRiskFactorInput)
    def create_risk_factor(
        name: str,
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
        rf = RiskFactor(
            name=name,
            type=type,
            description=description,
            region=region,
            level=level,
            urgency=urgency,
            probability=probability,
            impact=impact,
        )
        db.add(rf)
        db.commit()
        db.refresh(rf)
        result = {
            "risk_factor_id": rf.id,
            "name": rf.name,
            "level": rf.level,
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
        user = get_default_user(db)
        stmt = select(UserMemory).where(UserMemory.user_id == user.id)
        if category:
            stmt = stmt.where(UserMemory.category == category)
        stmt = stmt.order_by(
            UserMemory.importance.desc(), UserMemory.created_at.desc()
        ).limit(limit)
        mems = list(db.scalars(stmt))
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
        user = get_default_user(db)
        mem = UserMemory(
            user_id=user.id,
            content=content,
            category=category,
            importance=importance,
            source="chat",
        )
        db.add(mem)
        db.commit()
        db.refresh(mem)
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
        mem = db.get(UserMemory, memory_id)
        if mem is None:
            return {"ok": False, "error": "memory_not_found", "memory_id": memory_id}
        db.delete(mem)
        db.commit()
        return {"ok": True, "memory_id": memory_id}

    tools: list[StructuredTool] = [
        # Query
        list_pathways,
        list_requirements,
        list_risk_factors,
        list_recent_events,
        get_scenario_summary,
        run_scenario_reasoning,
        # Write (ontology)
        create_goal,
        create_pathway,
        create_requirement,
        create_risk_factor,
        # Memory
        list_memories,
        remember,
        forget,
        # Web
        StructuredTool.from_function(
            coroutine=_web_search,
            name="web_search",
            description="Search the web for current information using Tavily. Use this when the user asks about recent events, current facts, news, or anything not in the local knowledge graph. Returns a list of results with title, URL, and snippet.",
            args_schema=WebSearchInput,
        ),
        StructuredTool.from_function(
            coroutine=_web_fetch,
            name="web_fetch",
            description="Extract clean text content from one or more web pages. Use this after web_search to read full articles, or when the user provides a URL. Pass up to 5 URLs.",
            args_schema=WebFetchInput,
        ),
    ]
    return tools


__all__ = ["build_advisor_tools"]
