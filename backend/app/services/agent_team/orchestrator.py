"""Main agent (Orchestrator) nodes for the AgentTeam graph (§D.5 of the spec).

The orchestrator has three responsibilities, each implemented as a
LangGraph node:

1. **decompose** — call the LLM to split the objective into sub-tasks,
   one per specialist. The decomposition is constrained by the team
   template's ``allowed_roles`` and ``decompose_hint`` (decision 7:
   "non-fully-automatic decomposition" — the main agent can only pick
   roles from the template's allowed set, not invent arbitrary roles).

2. **aggregate** — merge the specialists' structured results into a
   single intermediate output. Uses the template's ``aggregate_hint``.
   When ``always_synthesize=True``, the template also expects a
   SynthesisSpecialist to be dispatched as the final sub-agent; the
   orchestrator's aggregate node is a lightweight merge that feeds
   into the SynthesisSpecialist's context.

3. **review** — (iterative_research template only) check the aggregated
   output for coverage gaps. If gaps are found and ``iteration <
   max_iterations``, dispatch one more round of specialists for the
   gap domains. Otherwise, proceed to finalize.

Each node updates the persisted ``AgentTeamJob`` row (status / progress /
current_step) and publishes a progress event to Redis pub/sub channel
``lifetree:agent_team:{job_id}``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.exceptions import LLMNotConfiguredError
from app.core.logging import get_logger
from app.llm.client import get_chat_model, get_instructor_sync
from app.models.agent_team import AgentTeamJob, TeamStatus
from app.services.agent_team.roles import ROLES, RoleSpec
from app.services.agent_team.state import SubtaskSpec, TeamState
from app.services.agent_team.templates import TEMPLATES, TeamTemplate

log = get_logger(__name__)


# ---------- Default budgets (§D.6) ----------

DEFAULT_MAX_SPECIALISTS = 5
DEFAULT_MAX_ITERATIONS = 1
DEFAULT_MAX_LLM_CALLS = 80
DEFAULT_MAX_TOOL_CALLS_PER_SPECIALIST = 20


# ---------- Pydantic schema for LLM decomposition output ----------


class _SubtaskLLM(BaseModel):
    """LLM-produced sub-task spec (validated before adding to the plan)."""

    role: str = Field(..., description="Role name from the allowed set")
    instruction: str = Field(..., description="What this sub-agent should do")
    engine: str | None = Field(
        None, description="Bound search engine (tavily/exa/bocha/anysearch)"
    )
    domain: str | None = Field(
        None, description="Domain hint for AnySearch (policy/academic/news/...)"
    )
    budget: int = Field(
        20, description="Max tool calls for this sub-agent", ge=1, le=30
    )


class _Decomposition(BaseModel):
    subtasks: list[_SubtaskLLM]
    rationale: str = Field("", description="Why this decomposition was chosen")


# ---------- System prompts ----------


_DECOMPOSE_SYSTEM_PROMPT = """You are LifeTree's AgentTeam orchestrator.

Given an objective, a team template, and a list of allowed roles, decompose
the objective into sub-tasks — one per specialist sub-agent. Each sub-task
must:

- Assign a role from the allowed set (you CANNOT invent roles outside this set).
- Have a clear, focused instruction (1-3 sentences) telling the sub-agent
  what to investigate or produce.
- Bind a search engine and domain hint when the role involves web search.
  Engine domain strengths:
    - tavily: general, official, news (English)
    - exa: academic, semantic, technical
    - bocha: chinese_news, china_policy, forum
    - anysearch: vertical, structured, batch
- Set a budget (max tool calls, 5-20) appropriate to the sub-task complexity.

Rules:
- Aim for {min}-{max} specialists (respect max_specialists).
- For cross-domain research, assign distinct engines + domains to each
  specialist so cross-validation can vote across sources.
- For independent validation, assign distinct verification angles.
- If the template includes a SynthesisSpecialist and always_synthesize=True,
  add ONE SynthesisSpecialist as the final sub-task — its instruction should
  be "Synthesize the findings from the other specialists into a coherent
  output."
- Return ONLY the JSON object — no markdown, no commentary.
"""


_AGGREGATE_SYSTEM_PROMPT = """You are LifeTree's AgentTeam aggregation agent.

Given an objective and a set of specialist results (each with a textual
output and any structured atoms), produce a merged intermediate output.

Rules:
- Highlight agreements and divergences across specialists.
- For divergent findings, note which specialist said what.
- Do NOT invent new information — only merge what the specialists reported.
- The output should be a structured JSON object with:
  - summary: 1-2 paragraph merge of the specialists' answers.
  - consensus: list of findings all specialists agree on.
  - divergences: list of findings where specialists disagreed (with
    which specialist said what).
  - gaps: list of domains/questions that were not covered.
- Return ONLY the JSON object.
"""


_REVIEW_SYSTEM_PROMPT = """You are LifeTree's AgentTeam review agent.

Given an objective, the aggregated output, and the specialist results,
identify coverage gaps that warrant another round of specialists.

A gap is worth filling when:
- The domain is central to the objective (not tangential).
- The existing specialists didn't cover it at all, or only superficially.
- Filling it would likely change the conclusion.

Rules:
- Return at most 3 gaps (prioritize by impact).
- For each gap, suggest the role and domain for a new specialist.
- If no gaps are worth filling, return an empty list.
- Return ONLY the JSON object.
"""


class _ReviewGapLLM(BaseModel):
    domain: str = Field(..., description="The gap domain (policy/academic/news/...)")
    reason: str = Field(..., description="Why this gap matters")
    suggested_role: str = Field(..., description="Role to dispatch for this gap")
    instruction: str = Field(..., description="Instruction for the new specialist")
    engine: str | None = Field(None, description="Engine to bind")
    budget: int = Field(15, description="Tool budget for the new specialist", ge=5, le=20)


class _Review(BaseModel):
    gaps: list[_ReviewGapLLM] = Field(default_factory=list)
    rationale: str = Field("", description="Why these gaps were selected (or not)")


# ---------- Node: decompose ----------


def decompose(db: Session, job: AgentTeamJob, state: TeamState) -> TeamState:
    """Main-agent node: decompose the objective into sub-tasks.

    Calls the LLM with the template's ``decompose_hint`` and the allowed
    roles. The LLM's output is validated: only roles in the template's
    ``allowed_roles`` are accepted; others are dropped. The sub-task IDs
    are assigned here (stable UUIDs for matching results).

    On LLM failure, falls back to a trivial decomposition that creates
    one specialist per allowed role (minus SynthesisSpecialist if
    always_synthesize is True — that's added separately).
    """
    _update_job(
        db,
        job,
        status=TeamStatus.DECOMPOSING,
        current_step="Decomposing objective into sub-tasks",
        progress=0.05,
    )

    template = TEMPLATES.get(job.template)
    if template is None:
        state["error"] = f"unknown_template: {job.template}"
        return state

    # Resolve budget from scope overrides or defaults.
    scope = job.scope or {}
    max_specialists = int(scope.get("max_specialists", DEFAULT_MAX_SPECIALISTS))
    max_iterations = int(
        scope.get("max_iterations", template.max_iterations)
    )
    max_llm_calls = int(scope.get("max_llm_calls", DEFAULT_MAX_LLM_CALLS))
    max_tool_calls_per_specialist = int(
        scope.get("max_tool_calls_per_specialist", DEFAULT_MAX_TOOL_CALLS_PER_SPECIALIST)
    )

    state.update(
        {
            "max_specialists": max_specialists,
            "max_iterations": max_iterations,
            "max_llm_calls": max_llm_calls,
            "max_tool_calls_per_specialist": max_tool_calls_per_specialist,
            "llm_calls": 0,
            "failure_count": 0,
            "iteration": 0,
            "specialist_results": [],
            "review_gaps": [],
        }
    )

    subtasks: list[SubtaskSpec] = []
    try:
        client = get_instructor_sync()
        model_name = get_chat_model().model.name
        decomposition = client.chat.completions.create(
            model=model_name,
            response_model=_Decomposition,
            messages=[
                {
                    "role": "system",
                    "content": _DECOMPOSE_SYSTEM_PROMPT.format(
                        min=min(3, max_specialists),
                        max=max_specialists,
                    ),
                },
                {
                    "role": "user",
                    "content": _build_decompose_user_prompt(job, template, scope),
                },
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        subtasks = _validate_subtasks(
            decomposition.subtasks, template, max_specialists, max_tool_calls_per_specialist
        )
        state["llm_calls"] = state.get("llm_calls", 0) + 1
    except LLMNotConfiguredError:
        log.warning("agent_team.decompose_llm_not_configured", job_id=job.id)
        subtasks = _fallback_decomposition(template, max_specialists, max_tool_calls_per_specialist)
        state["failure_count"] = state.get("failure_count", 0) + 1
    except Exception as exc:  # noqa: BLE001
        log.error("agent_team.decompose_failed", job_id=job.id, error=str(exc))
        subtasks = _fallback_decomposition(template, max_specialists, max_tool_calls_per_specialist)
        state["failure_count"] = state.get("failure_count", 0) + 1

    # Assign stable sub-task IDs.
    for i, st in enumerate(subtasks):
        st["subtask_id"] = f"st_{i+1}_{uuid.uuid4().hex[:8]}"

    # If the template always_synthesizes and no SynthesisSpecialist was
    # added by the LLM, append one.
    if template.always_synthesize and not any(
        s.get("role") == "SynthesisSpecialist" for s in subtasks
    ):
        synth = _make_synthesis_subtask(max_tool_calls_per_specialist)
        synth["subtask_id"] = f"st_{len(subtasks)+1}_{uuid.uuid4().hex[:8]}"
        subtasks.append(synth)

    # Cap at max_specialists (including the synthesis specialist).
    if len(subtasks) > max_specialists + 1:  # +1 for the synthesis specialist
        subtasks = subtasks[: max_specialists + 1]

    state["subtasks"] = subtasks
    job.subtasks = list(subtasks)  # type: ignore[assignment]
    job.progress = 0.10
    db.commit()

    log.info(
        "agent_team.decomposed",
        job_id=job.id,
        subtasks=len(subtasks),
        roles=[s.get("role") for s in subtasks],
    )
    return state


def _build_decompose_user_prompt(
    job: AgentTeamJob, template: TeamTemplate, scope: dict[str, Any]
) -> str:
    """Build the user prompt for the decomposition LLM call."""
    allowed_roles_desc = []
    for role_name in template.allowed_roles:
        spec = ROLES.get(role_name)
        if spec:
            allowed_roles_desc.append(f"- {role_name}: {spec.description}")

    engines = scope.get("engines", [])
    domains = scope.get("domains", [])
    engines_str = ", ".join(engines) if engines else "(use all configured)"
    domains_str = ", ".join(domains) if domains else "(auto-detect)"

    return (
        f"Objective: {job.objective}\n\n"
        f"Team template: {template.name}\n"
        f"Template description: {template.description}\n"
        f"Decomposition hint: {template.decompose_hint}\n\n"
        f"Allowed roles:\n{chr(10).join(allowed_roles_desc)}\n\n"
        f"Available engines: {engines_str}\n"
        f"Target domains: {domains_str}\n"
        f"Scope: {json.dumps(scope, ensure_ascii=False, default=str)}\n\n"
        f"Decompose the objective into sub-tasks."
    )


def _validate_subtasks(
    llm_subtasks: list[_SubtaskLLM],
    template: TeamTemplate,
    max_specialists: int,
    default_budget: int,
) -> list[SubtaskSpec]:
    """Validate the LLM's decomposition: filter out disallowed roles."""
    out: list[SubtaskSpec] = []
    for st in llm_subtasks:
        if st.role not in template.allowed_roles:
            log.warning("agent_team.decompose_role_not_allowed", role=st.role)
            continue
        out.append(
            {
                "subtask_id": "",  # assigned by decompose()
                "role": st.role,
                "instruction": st.instruction,
                "engine": st.engine,
                "domain": st.domain,
                "budget": min(int(st.budget), 30) if st.budget else default_budget,
            }
        )
        if len(out) >= max_specialists:
            break
    return out


def _fallback_decomposition(
    template: TeamTemplate,
    max_specialists: int,
    default_budget: int,
) -> list[SubtaskSpec]:
    """Trivial decomposition used when the LLM is unavailable.

    Creates one specialist per non-synthesis allowed role, with a
    generic instruction. If always_synthesize=True, the synthesis
    specialist is appended by decompose() after this returns.
    """
    out: list[SubtaskSpec] = []
    for role_name in template.allowed_roles:
        if role_name == "SynthesisSpecialist":
            continue
        spec = ROLES.get(role_name)
        if spec is None:
            continue
        out.append(
            {
                "subtask_id": "",
                "role": role_name,
                "instruction": (
                    f"Investigate the objective from the perspective of a "
                    f"{role_name}. Focus on your specialty area."
                ),
                "engine": None,
                "domain": None,
                "budget": default_budget,
            }
        )
        if len(out) >= max_specialists:
            break
    return out


def _make_synthesis_subtask(default_budget: int) -> SubtaskSpec:
    """Create the SynthesisSpecialist sub-task (appended when always_synthesize=True)."""
    return {
        "subtask_id": "",
        "role": "SynthesisSpecialist",
        "instruction": (
            "Synthesize the findings from the other specialists into a "
            "coherent final output. Highlight consensus and divergences. "
            "Use list_assertions / list_conflicts / detect_trends to read "
            "the structured atoms they produced."
        ),
        "engine": None,
        "domain": None,
        "budget": min(default_budget, 10),
    }


# ---------- Node: aggregate ----------


def aggregate(db: Session, job: AgentTeamJob, state: TeamState) -> TeamState:
    """Main-agent node: merge specialist results into an intermediate output.

    Calls the LLM with the template's ``aggregate_hint`` and the
    specialists' outputs. The LLM's output is persisted to
    ``job.aggregated`` and feeds into the review node (for iterative
    templates) or the finalize node.

    On LLM failure, falls back to a trivial concatenation of the
    specialists' outputs.
    """
    _update_job(
        db,
        job,
        status=TeamStatus.AGGREGATING,
        current_step="Aggregating specialist results",
        progress=0.80,
    )

    template = TEMPLATES.get(job.template)
    specialist_results = state.get("specialist_results", [])
    if not specialist_results:
        state["aggregated"] = {
            "summary": "No specialist results to aggregate.",
            "consensus": [],
            "divergences": [],
            "gaps": [],
        }
        job.aggregated = dict(state["aggregated"])  # type: ignore[assignment]
        job.progress = 0.85
        db.commit()
        return state

    aggregated: dict[str, Any]
    try:
        client = get_instructor_sync()
        model_name = get_chat_model().model.name
        result = client.chat.completions.create(
            model=model_name,
            response_model=_Aggregation,
            messages=[
                {"role": "system", "content": _AGGREGATE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_aggregate_user_prompt(
                        job, template, specialist_results
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        aggregated = {
            "summary": result.summary,
            "consensus": [c.model_dump() for c in result.consensus],
            "divergences": [d.model_dump() for d in result.divergences],
            "gaps": [g.model_dump() for g in result.gaps],
        }
        state["llm_calls"] = state.get("llm_calls", 0) + 1
    except LLMNotConfiguredError:
        log.warning("agent_team.aggregate_llm_not_configured", job_id=job.id)
        aggregated = _fallback_aggregation(specialist_results)
        state["failure_count"] = state.get("failure_count", 0) + 1
    except Exception as exc:  # noqa: BLE001
        log.error("agent_team.aggregate_failed", job_id=job.id, error=str(exc))
        aggregated = _fallback_aggregation(specialist_results)
        state["failure_count"] = state.get("failure_count", 0) + 1

    # Count failures and budget-exceeded specialists for the report.
    failed = sum(
        1 for r in specialist_results
        if r.get("status") in ("failed", "budget_exceeded")
    )
    if failed > 0:
        aggregated.setdefault("warnings", []).append(
            f"{failed} specialist(s) failed or exceeded budget; "
            "results may be incomplete."
        )

    state["aggregated"] = aggregated
    job.aggregated = dict(aggregated)  # type: ignore[assignment]
    job.specialist_results = list(specialist_results)  # type: ignore[assignment]
    job.progress = 0.85
    db.commit()
    _publish_progress(job)

    log.info(
        "agent_team.aggregated",
        job_id=job.id,
        specialists=len(specialist_results),
        failed=failed,
    )
    return state


class _ConsensusFinding(BaseModel):
    finding: str
    supporting_specialists: list[str] = Field(default_factory=list)


class _DivergenceFinding(BaseModel):
    finding: str
    positions: list[dict[str, Any]] = Field(default_factory=list)


class _Gap(BaseModel):
    domain: str
    reason: str


class _Aggregation(BaseModel):
    summary: str
    consensus: list[_ConsensusFinding] = Field(default_factory=list)
    divergences: list[_DivergenceFinding] = Field(default_factory=list)
    gaps: list[_Gap] = Field(default_factory=list)


def _build_aggregate_user_prompt(
    job: AgentTeamJob,
    template: TeamTemplate | None,
    specialist_results: list[dict[str, Any]],
) -> str:
    """Build the user prompt for the aggregation LLM call."""
    template_desc = template.description if template else ""
    aggregate_hint = template.aggregate_hint if template else ""

    # Trim specialist outputs to keep the prompt under token limits.
    specialists_summary = []
    for r in specialist_results:
        output = (r.get("output") or "")[:800]
        specialists_summary.append(
            {
                "subtask_id": r.get("subtask_id"),
                "role": r.get("role"),
                "status": r.get("status"),
                "output": output,
                "sources_count": len(r.get("sources", [])),
                "assertions_count": len(r.get("atoms", {}).get("assertions", [])),
            }
        )

    return (
        f"Objective: {job.objective}\n\n"
        f"Template: {job.template}\n"
        f"Template description: {template_desc}\n"
        f"Aggregation hint: {aggregate_hint}\n\n"
        f"Specialist results (truncated):\n"
        f"{json.dumps(specialists_summary, ensure_ascii=False, default=str)}\n\n"
        f"Produce the aggregated output."
    )


def _fallback_aggregation(
    specialist_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Trivial aggregation used when the LLM is unavailable."""
    parts = []
    for r in specialist_results:
        role = r.get("role", "unknown")
        output = (r.get("output") or "(no output)")[:500]
        parts.append(f"[{role}] {output}")
    return {
        "summary": "\n\n".join(parts) if parts else "No results.",
        "consensus": [],
        "divergences": [],
        "gaps": [],
    }


# ---------- Node: review ----------


def review(db: Session, job: AgentTeamJob, state: TeamState) -> TeamState:
    """Main-agent node: check for coverage gaps (iterative templates only).

    For ``iterative_research`` (and any template with ``max_iterations > 1``),
    this node calls the LLM to identify coverage gaps. If gaps are found and
    ``iteration < max_iterations``, new sub-tasks are added to ``state.subtasks``
    and the graph loops back to dispatch. Otherwise, the graph proceeds to
    finalize.

    For non-iterative templates (max_iterations == 1), this node is a no-op
    that passes through to finalize.
    """
    _update_job(
        db,
        job,
        status=TeamStatus.REVIEWING,
        current_step="Reviewing for coverage gaps",
        progress=0.90,
    )

    template = TEMPLATES.get(job.template)
    if template is None:
        state["error"] = f"unknown_template: {job.template}"
        return state

    max_iterations = state.get("max_iterations", template.max_iterations)
    current_iteration = state.get("iteration", 0)

    # Non-iterative templates: skip review, go straight to finalize.
    if max_iterations <= 1:
        state["review_gaps"] = []
        job.progress = 0.92
        db.commit()
        return state

    # Already used all iterations: skip review.
    if current_iteration >= max_iterations:
        log.info(
            "agent_team.review_max_iterations_reached",
            job_id=job.id,
            iteration=current_iteration,
        )
        state["review_gaps"] = []
        job.progress = 0.92
        db.commit()
        return state

    aggregated = state.get("aggregated") or {}
    specialist_results = state.get("specialist_results", [])

    gaps: list[dict[str, Any]] = []
    try:
        client = get_instructor_sync()
        model_name = get_chat_model().model.name
        review_result = client.chat.completions.create(
            model=model_name,
            response_model=_Review,
            messages=[
                {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_review_user_prompt(
                        job, aggregated, specialist_results
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=1000,
        )
        for g in review_result.gaps:
            gaps.append(
                {
                    "domain": g.domain,
                    "reason": g.reason,
                    "suggested_role": g.suggested_role,
                    "instruction": g.instruction,
                    "engine": g.engine,
                    "budget": g.budget,
                }
            )
        state["llm_calls"] = state.get("llm_calls", 0) + 1
    except LLMNotConfiguredError:
        log.warning("agent_team.review_llm_not_configured", job_id=job.id)
        state["failure_count"] = state.get("failure_count", 0) + 1
    except Exception as exc:  # noqa: BLE001
        log.error("agent_team.review_failed", job_id=job.id, error=str(exc))
        state["failure_count"] = state.get("failure_count", 0) + 1

    # Convert gaps to new sub-tasks for the next iteration.
    new_subtasks: list[SubtaskSpec] = []
    for i, g in enumerate(gaps[:3]):  # cap at 3 gap-fillers
        role_name = g.get("suggested_role", "ResearchSpecialist")
        if role_name not in template.allowed_roles:
            role_name = template.allowed_roles[0]
        new_subtasks.append(
            {
                "subtask_id": f"gap_{current_iteration+1}_{i+1}_{uuid.uuid4().hex[:8]}",
                "role": role_name,
                "instruction": g.get("instruction", ""),
                "engine": g.get("engine"),
                "domain": g.get("domain"),
                "budget": min(int(g.get("budget", 15)), 20),
            }
        )

    state["review_gaps"] = gaps
    job.review_gaps = list(gaps)  # type: ignore[assignment]
    if new_subtasks:
        # Add gap-filling sub-tasks for the next dispatch round.
        state["subtasks"] = list(state.get("subtasks", [])) + new_subtasks
        job.subtasks = list(state["subtasks"])  # type: ignore[assignment]
        state["iteration"] = current_iteration + 1
        job.iterations = state["iteration"]

    db.commit()
    _publish_progress(job)

    log.info(
        "agent_team.reviewed",
        job_id=job.id,
        gaps=len(gaps),
        new_subtasks=len(new_subtasks),
        iteration=state.get("iteration", 0),
    )
    return state


def _build_review_user_prompt(
    job: AgentTeamJob,
    aggregated: dict[str, Any],
    specialist_results: list[dict[str, Any]],
) -> str:
    """Build the user prompt for the review LLM call."""
    specialists_summary = [
        {
            "role": r.get("role"),
            "status": r.get("status"),
            "sources_count": len(r.get("sources", [])),
        }
        for r in specialist_results
    ]
    return (
        f"Objective: {job.objective}\n\n"
        f"Aggregated output:\n{json.dumps(aggregated, ensure_ascii=False, default=str)}\n\n"
        f"Specialist summary:\n{json.dumps(specialists_summary, ensure_ascii=False, default=str)}\n\n"
        f"Identify coverage gaps worth filling in another round."
    )


# ---------- Conditional edge: should_continue_after_review ----------


def should_dispatch_after_review(state: TeamState) -> str:
    """Conditional edge after the review node.

    Returns ``"dispatch"`` if the review found gaps and we haven't hit
    ``max_iterations`` yet (loop back to dispatch the gap-fillers).
    Otherwise returns ``"finalize"``.
    """
    if state.get("error"):
        return "finalize"

    max_iterations = state.get("max_iterations", 1)
    # review() increments ``iteration`` when it adds gap-filling subtasks.
    # If iteration > 0, it means at least one review round happened and
    # added subtasks. Check whether we're still within budget and whether
    # there are pending (undispatched) subtasks.
    if state.get("iteration", 0) > max_iterations:
        return "finalize"

    all_subtask_ids = {s.get("subtask_id") for s in state.get("subtasks", [])}
    completed_subtask_ids = {
        r.get("subtask_id") for r in state.get("specialist_results", [])
    }
    pending = all_subtask_ids - completed_subtask_ids
    return "dispatch" if pending else "finalize"


# ---------- Node: finalize ----------


def finalize(db: Session, job: AgentTeamJob, state: TeamState) -> TeamState:
    """Mark the job as COMPLETED and persist the final output."""
    error = state.get("error")
    if error:
        _update_job(
            db,
            job,
            status=TeamStatus.FAILED,
            current_step=f"Failed: {error[:120]}",
            progress=job.progress,
        )
        job.error = error
        db.commit()
        _publish_progress(job)
        return state

    # Assemble the final output from the aggregated result + metadata.
    aggregated = state.get("aggregated") or {}
    specialist_results = state.get("specialist_results", [])

    final_output: dict[str, Any] = {
        **aggregated,
        "template": job.template,
        "objective": job.objective,
        "specialist_count": len(specialist_results),
        "specialist_summaries": [
            {
                "subtask_id": r.get("subtask_id"),
                "role": r.get("role"),
                "status": r.get("status"),
                "tool_calls": r.get("tool_calls", 0),
                "llm_calls": r.get("llm_calls", 0),
                "sources_count": len(r.get("sources", [])),
                "assertions_count": len(r.get("atoms", {}).get("assertions", [])),
                "error": r.get("error"),
            }
            for r in specialist_results
        ],
        "iterations": state.get("iteration", 0),
        "review_gaps": state.get("review_gaps", []),
        "team_metadata": {
            "total_llm_calls": state.get("llm_calls", 0),
            "failure_count": state.get("failure_count", 0),
            "honesty_disclaimer": (
                "本结论由多个子代理独立调研后汇总，基于公开信源自动聚合，"
                "未经独立验证，仅供参考。建议结合官方渠道与专业意见综合判断。"
            ),
        },
    }

    state["final_output"] = final_output
    job.final_output = dict(final_output)  # type: ignore[assignment]

    _update_job(
        db,
        job,
        status=TeamStatus.COMPLETED,
        current_step="AgentTeam task completed",
        progress=1.0,
    )
    db.commit()
    _publish_progress(job)

    log.info(
        "agent_team.finalized",
        job_id=job.id,
        specialists=len(specialist_results),
        iterations=state.get("iteration", 0),
    )
    return state


# ---------- Progress publisher / job updater ----------


def _update_job(
    db: Session,
    job: AgentTeamJob,
    *,
    status: TeamStatus,
    current_step: str,
    progress: float,
) -> None:
    """Update job status / progress / current_step, commit, and publish."""
    job.status = status.value
    job.current_step = current_step
    job.progress = max(0.0, min(1.0, progress))
    if status == TeamStatus.DECOMPOSING and job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
    if status == TeamStatus.COMPLETED:
        job.completed_at = datetime.now(timezone.utc)
        job.progress = 1.0
    db.commit()
    _publish_progress(job)


def _publish_progress(job: AgentTeamJob) -> None:
    """Push a progress event to Redis pub/sub for live UI updates.

    Channel: ``lifetree:agent_team:{job_id}``. Failures are non-fatal —
    pub/sub is best-effort; the DB row is the source of truth.
    """
    try:
        from app.db.redis import get_redis

        payload = {
            "job_id": job.id,
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "iteration": job.iterations,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        get_redis().publish(
            f"lifetree:agent_team:{job.id}",
            json.dumps(payload, default=str),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("agent_team.publish_progress_failed", job_id=job.id, error=str(exc))


__all__ = [
    "DEFAULT_MAX_LLM_CALLS",
    "DEFAULT_MAX_SPECIALISTS",
    "DEFAULT_MAX_TOOL_CALLS_PER_SPECIALIST",
    "aggregate",
    "decompose",
    "finalize",
    "review",
    "should_dispatch_after_review",
]
