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

from typing import Any

from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.postgres import SessionLocal
from app.models.event import Event, InformationSource
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.models.memory import UserMemory
from app.models.scenario import Scenario
from app.models.user import UserProfile
from app.models.user_runtime import UserServiceConfig
from app.services.crawler import CrawlerService
from app.services.graph import GraphService
from app.services.scenarios import ScenarioService

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
        url = item.get("url", "unknown")
        raw = item.get("raw_content", "") or item.get("content", "")
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

    async def user_web_search(query: str, max_results: int = 5) -> str:
        return await _web_search(query, max_results, api_key=user_tavily_key)

    async def user_web_fetch(urls: list[str]) -> str:
        return await _web_fetch(urls, api_key=user_tavily_key)

    # ---------- Query tools ----------

    @tool("list_pathways", args_schema=ListPathwaysInput)
    def list_pathways(goal_id: str | None = None) -> dict[str, Any]:
        """List all pathways for a goal, including their requirement counts."""
        effective_goal_id = goal_id or goal_id_context
        if not effective_goal_id:
            return {"error": "no_goal_context", "message": "No goal_id provided and no goal context set for this conversation."}
        pathways = list(db.scalars(select(Pathway).where(Pathway.goal_id == effective_goal_id)))
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
    def get_scenario_summary(scenario_id: str | None = None) -> dict[str, Any]:
        """Get a scenario's cached probability / risk summary without re-running."""
        effective_scenario_id = scenario_id or scenario_id_context
        if not effective_scenario_id:
            return {"error": "no_scenario_context", "message": "No scenario_id provided and no scenario context set for this conversation."}
        sc = db.get(Scenario, effective_scenario_id)
        if sc is None:
            return {"error": "scenario_not_found", "scenario_id": effective_scenario_id}
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
            g = Goal(
                user_id=user_id,
                title=title,
                description=description,
                scenario=scenario,
                target_date=td,
                status="draft",
            )
            session.add(g)
            session.flush()
            session.commit()
            session.refresh(g)
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
            if parent_pathway_id:
                parent = session.get(Pathway, parent_pathway_id)
                if parent is None:
                    return {"error": "parent_pathway_not_found", "parent_pathway_id": parent_pathway_id}
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
        """
        with SessionLocal() as session:
            p = session.get(Pathway, pathway_id)
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
            session.add(r)
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
            session.add(rf)
            session.commit()
            session.refresh(rf)
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
                demo["lifecycle_stage"] = lifecycle_stage
            if cruising_mode is not None:
                demo["cruising_mode"] = cruising_mode
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
        goal_id: str | None = None, name: str = "", description: str | None = None
    ) -> dict[str, Any]:
        """Create a new scenario branch for parallel sandbox推演 during conversation.

        Use when the user considers an alternative pathway or 'what if' scenario.
        """
        effective_goal_id = goal_id or goal_id_context
        if not effective_goal_id:
            return {"error": "no_goal_context", "message": "No goal_id provided and no goal context set for this conversation."}
        with SessionLocal() as session:
            g = session.get(Goal, effective_goal_id)
            if g is None:
                return {"error": "goal_not_found", "goal_id": effective_goal_id}
            sc_svc = ScenarioService(session)
            sc = sc_svc.create_branch(goal_id=effective_goal_id, name=name, description=description)
            branch_count = sc_svc.count_active_branches(effective_goal_id)
            return {
                "ok": True,
                "scenario_id": sc.id,
                "name": sc.name,
                "branch_count": branch_count,
            }

    @tool("add_user_source", args_schema=AddUserSourceInput)
    def add_user_source(
        content: str,
        source_type: str = "chat_mention",
        credibility: str = "pending",
    ) -> dict[str, Any]:
        """Add a user-provided information source (text snippet from a consultant email, forum post, etc.) and queue it for structuring."""
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

            result: dict[str, Any] = {
                "source_id": source.id,
                "kind": source.kind,
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

        log.info(
            "advisor.tool.add_user_source",
            source_id=source.id,
            source_type=source_type,
            graph_synced=result["graph_synced"],
        )
        return result

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
        update_requirement_status,
        create_risk_factor,
        update_user_profile,
        create_scenario_branch,
        add_user_source,
        # Memory
        list_memories,
        remember,
        forget,
        # Web
        StructuredTool.from_function(
            coroutine=user_web_search,
            name="web_search",
            description="Search the web for current information using Tavily. Use this when the user asks about recent events, current facts, news, or anything not in the local knowledge graph. Returns a list of results with title, URL, and snippet.",
            args_schema=WebSearchInput,
        ),
        StructuredTool.from_function(
            coroutine=user_web_fetch,
            name="web_fetch",
            description="Extract clean text content from one or more web pages. Use this after web_search to read full articles, or when the user provides a URL. Pass up to 5 URLs.",
            args_schema=WebFetchInput,
        ),
    ]
    return tools


__all__ = ["build_advisor_tools"]
