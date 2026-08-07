"""AgentTeam LangGraph orchestration (§D.5 of the spec).

Wires the orchestrator + specialist nodes into a StateGraph with Send-API
fan-out::

    decompose → dispatch ──Send──→ specialist × N → aggregate → review
                        ↑                                     │
                        └──────────── (gaps found) ──────────┘
                                                              │
                        (no gaps / max iterations) ──→ finalize

The ``dispatch`` node returns a list of ``Send("specialist", subtask)``
objects, one per pending sub-task. LangGraph runs the ``specialist`` node
in parallel for each Send; the ``specialist_results`` reducer
(``operator.add``) accumulates each result into the shared state.

Each orchestrator node updates the persisted ``AgentTeamJob`` row
(status / progress / current_step) and publishes a progress event to
Redis pub/sub channel ``lifetree:agent_team:{job_id}`` so the frontend
``/agent-team/{job_id}`` page and the chat team-progress card can render
live updates.

The graph is built per invocation because nodes close over the DB session
and the ``AgentTeamJob`` row (mirrors the research-graph and advisor
patterns).
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import Send
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.postgres import SessionLocal
from app.llm.client import get_chat_model
from app.llm.registry import ResolvedModel
from app.models.agent_team import AgentTeamJob, TeamStatus
from app.services.agent_team.orchestrator import (
    aggregate,
    decompose,
    finalize,
    review,
    should_dispatch_after_review,
)
from app.services.agent_team.roles import get_role, resolve_tools
from app.services.agent_team.specialist_graph import run_specialist
from app.services.agent_team.state import TeamState

log = get_logger(__name__)


# ---------- Specialist node (called via Send API) ----------


def _make_specialist_node(
    db: Session,
    job: AgentTeamJob,
    resolved_model: ResolvedModel,
    all_tools: dict[str, object],
    *,
    user_id: str,
    goal_id: str | None,
    scenario_id: str | None,
):
    """Build the specialist node function.

    The node receives a single ``SubtaskSpec`` (passed via ``Send``) and
    returns ``{"specialist_results": [result]}`` so the ``add`` reducer
    appends it to the shared state.
    """

    def specialist_node(subtask: dict[str, Any]) -> dict[str, Any]:
        """Run one specialist and return its result for the add reducer."""
        role_name = subtask.get("role", "ResearchSpecialist")
        role = get_role(role_name)
        if role is None:
            log.warning(
                "agent_team.specialist_unknown_role",
                job_id=job.id,
                subtask_id=subtask.get("subtask_id"),
                role=role_name,
            )
            return {
                "specialist_results": [
                    {
                        "subtask_id": subtask.get("subtask_id", ""),
                        "role": role_name,
                        "status": "failed",
                        "output": "",
                        "atoms": {"events": [], "assertions": [], "relationships": [], "metrics": []},
                        "sources": [],
                        "llm_calls": 0,
                        "tool_calls": 0,
                        "error": f"unknown_role: {role_name}",
                    }
                ]
            }

        tools = resolve_tools(role_name, all_tools)
        if not tools:
            log.warning(
                "agent_team.specialist_no_tools",
                job_id=job.id,
                subtask_id=subtask.get("subtask_id"),
                role=role_name,
            )

        # Update job progress for the running phase.
        job.status = TeamStatus.RUNNING.value
        job.current_step = f"Running specialist: {role_name} ({subtask.get('subtask_id', '')})"
        # Progress spans 0.15 → 0.75 across the running phase.
        existing_results = len(job.specialist_results or [])
        total_subtasks = len(job.subtasks or [])
        if total_subtasks > 0:
            job.progress = 0.15 + 0.60 * (existing_results / total_subtasks)
        db.commit()

        result = run_specialist(
            db=db,
            user_id=user_id,
            goal_id=goal_id,
            scenario_id=scenario_id,
            subtask=subtask,
            role=role,
            tools=tools,
            resolved_model=resolved_model,
            job_id=job.id,
        )

        # Persist the specialist result immediately so a soft timeout
        # leaves partial results in the DB.
        current_results = list(job.specialist_results or [])
        current_results.append(dict(result))
        job.specialist_results = current_results  # type: ignore[assignment]
        db.commit()

        return {"specialist_results": [dict(result)]}

    return specialist_node


# ---------- Dispatch node (Send API fan-out) ----------


def _make_dispatch_node(db: Session, job: AgentTeamJob):
    """Build the dispatch node.

    The dispatch node inspects ``state.subtasks`` and ``state.specialist_results``
    to find pending (undispatched) sub-tasks, then returns a list of
    ``Send("specialist", subtask)`` objects for LangGraph to fan out.

    On the first call, all subtasks are pending. On subsequent calls
    (after review adds gap-filling subtasks), only the new gap-fillers
    are pending.
    """

    def dispatch_node(state: TeamState) -> list[Send]:
        all_subtasks = state.get("subtasks", [])
        completed_ids = {
            r.get("subtask_id") for r in state.get("specialist_results", [])
        }
        pending = [s for s in all_subtasks if s.get("subtask_id") not in completed_ids]

        job.status = TeamStatus.DISPATCHING.value
        job.current_step = (
            f"Dispatching {len(pending)} specialist(s) "
            f"(iteration {state.get('iteration', 0) + 1})"
        )
        job.progress = 0.12
        db.commit()

        log.info(
            "agent_team.dispatching",
            job_id=job.id,
            pending=len(pending),
            completed=len(completed_ids),
            iteration=state.get("iteration", 0),
        )

        if not pending:
            return []

        return [Send("specialist", dict(subtask)) for subtask in pending]

    return dispatch_node


# ---------- Aggregate node wrapper ----------


def _make_aggregate_node(db: Session, job: AgentTeamJob):
    """Wrap the aggregate node to close over db + job."""

    def aggregate_node(state: TeamState) -> TeamState:
        return aggregate(db, job, state)

    return aggregate_node


# ---------- Review node wrapper ----------


def _make_review_node(db: Session, job: AgentTeamJob):
    """Wrap the review node to close over db + job."""

    def review_node(state: TeamState) -> TeamState:
        return review(db, job, state)

    return review_node


# ---------- Decompose node wrapper ----------


def _make_decompose_node(db: Session, job: AgentTeamJob):
    """Wrap the decompose node to close over db + job."""

    def decompose_node(state: TeamState) -> TeamState:
        return decompose(db, job, state)

    return decompose_node


# ---------- Finalize node wrapper ----------


def _make_finalize_node(db: Session, job: AgentTeamJob):
    """Wrap the finalize node to close over db + job."""

    def finalize_node(state: TeamState) -> TeamState:
        return finalize(db, job, state)

    return finalize_node


# ---------- Graph builder ----------


def build_team_graph(
    db: Session,
    job: AgentTeamJob,
    *,
    user_id: str,
    goal_id: str | None = None,
    scenario_id: str | None = None,
) -> Any:
    """Compile the AgentTeam StateGraph for one job.

    The graph is built per invocation because nodes close over the DB
    session, the ``AgentTeamJob`` row, and the per-request tool set.

    Args:
        db: SQLAlchemy session (shared across nodes; write tools inside
            specialists open their own short-lived sessions).
        job: The ``AgentTeamJob`` row to advance.
        user_id: The owning user (for tool context + data isolation).
        goal_id: Optional goal context for the specialist tools.
        scenario_id: Optional scenario context.

    Returns:
        A compiled LangGraph ``CompiledStateGraph`` ready to ``ainvoke``.
    """
    # Resolve the chat model for the specialists.
    resolved_model = get_chat_model()

    # Build the full advisor tool set, then prune per-specialist.
    # We import here to avoid a circular import (tools → services → ...).
    from app.services.advisor.tools import build_advisor_tools

    all_tools_list = build_advisor_tools(
        db,
        user_id=user_id,
        goal_id=goal_id,
        scenario_id=scenario_id,
        include_web_search=True,
        include_web_fetch=True,
    )
    all_tools: dict[str, object] = {t.name: t for t in all_tools_list}

    g: StateGraph = StateGraph(TeamState)

    # Add nodes.
    g.add_node("decompose", _make_decompose_node(db, job))
    g.add_node("dispatch", _make_dispatch_node(db, job))
    g.add_node(
        "specialist",
        _make_specialist_node(
            db,
            job,
            resolved_model,
            all_tools,
            user_id=user_id,
            goal_id=goal_id,
            scenario_id=scenario_id,
        ),
    )
    g.add_node("aggregate", _make_aggregate_node(db, job))
    g.add_node("review", _make_review_node(db, job))
    g.add_node("finalize", _make_finalize_node(db, job))

    # Add edges.
    g.set_entry_point("decompose")
    g.add_edge("decompose", "dispatch")
    # dispatch returns Send("specialist", ...) objects — LangGraph fans
    # them out. After all specialists complete, control flows to aggregate.
    g.add_edge("specialist", "aggregate")
    g.add_edge("aggregate", "review")
    # Conditional edge after review: loop back to dispatch (gaps found)
    # or proceed to finalize (no gaps / max iterations).
    g.add_conditional_edges(
        "review",
        should_dispatch_after_review,
        {
            "dispatch": "dispatch",
            "finalize": "finalize",
        },
    )
    g.add_edge("finalize", END)

    return g.compile()


# ---------- Synchronous runner (used by Celery) ----------


def run_agent_team(db: Session, job_id: str) -> TeamState:
    """Synchronous runner used by the Celery ``run_agent_team`` task.

    Loads the ``AgentTeamJob`` row, builds the graph, and invokes it with
    an initial state. Uses ``asyncio.run(graph.ainvoke(...))`` so the
    Send-API fan-out runs specialists in parallel via asyncio.

    On any fatal exception, the job is marked FAILED with the error
    message so the frontend can surface it.
    """
    job = db.get(AgentTeamJob, job_id)
    if job is None:
        log.error("agent_team.run_job_not_found", job_id=job_id)
        return {"error": f"AgentTeamJob {job_id} not found"}  # type: ignore[return-value]

    # Skip if already terminal (e.g. user cancelled, or task was retried
    # after a soft-timeout partial completion).
    if job.status in (
        TeamStatus.COMPLETED.value,
        TeamStatus.CANCELLED.value,
    ):
        log.info(
            "agent_team.run_skipped_terminal",
            job_id=job_id,
            status=job.status,
        )
        return {"final_output": job.final_output, "status": job.status}  # type: ignore[return-value]

    # Resolve scope for goal/scenario context.
    scope = job.scope or {}
    goal_id = scope.get("goal_id")
    scenario_id = scope.get("scenario_id")

    initial_state: TeamState = {
        "job_id": job_id,
        "user_id": job.user_id,
        "objective": job.objective,
        "scope": scope,
        "template": job.template,
        "subtasks": [],
        "specialist_results": [],
        "review_gaps": [],
        "iteration": 0,
        "llm_calls": 0,
        "failure_count": 0,
    }

    try:
        graph = build_team_graph(
            db,
            job,
            user_id=job.user_id,
            goal_id=goal_id,
            scenario_id=scenario_id,
        )

        # Use ainvoke so Send-API fan-out runs specialists concurrently.
        # The recursion_limit needs to accommodate: decompose → dispatch →
        # N specialists (each up to 2*max_tool_calls+8 super-steps) →
        # aggregate → review → (loop) → finalize. Set a generous limit.
        final_state = asyncio.run(
            graph.ainvoke(
                initial_state,
                config={
                    "recursion_limit": 200,
                },
            )
        )
        return final_state
    except Exception as exc:  # noqa: BLE001
        log.error(
            "agent_team.run_failed",
            job_id=job_id,
            error=str(exc),
            exc_info=True,
        )
        # Mark the job as FAILED.
        job = db.get(AgentTeamJob, job_id)
        if job is not None and job.status not in (
            TeamStatus.COMPLETED.value,
            TeamStatus.CANCELLED.value,
        ):
            job.status = TeamStatus.FAILED.value
            job.error = f"run_failed: {exc}"[:500]
            from datetime import datetime, timezone

            job.completed_at = datetime.now(timezone.utc)
            db.commit()

            # Publish the failure event.
            try:
                import json

                from app.db.redis import get_redis

                payload = {
                    "job_id": job.id,
                    "status": job.status,
                    "progress": job.progress,
                    "current_step": job.current_step,
                    "error": job.error,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                get_redis().publish(
                    f"lifetree:agent_team:{job.id}",
                    json.dumps(payload, default=str),
                )
            except Exception:  # noqa: BLE001
                pass

        return {"error": str(exc)}  # type: ignore[return-value]


__all__ = [
    "build_team_graph",
    "run_agent_team",
]
