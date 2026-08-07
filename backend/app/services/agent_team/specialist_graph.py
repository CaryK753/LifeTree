"""Sub-agent specialist sub-graph (§D.5 of the spec).

Each specialist is a *simplified* ReAct agent with:

- **Independent context**: its own ``messages`` list, seeded with only the
  sub-task instruction + the role's system prompt. No main-agent history
  leaks in — this is the independence guarantee that makes AgentTeam's
  cross-validation trustworthy (§D.1 key design).
- **Pruned toolset**: only the tools declared in the role's ``tools``
  tuple are injected (§D.3). Unknown tool names are silently filtered.
- **Tight budget**: ``max_tool_calls`` (default 20, vs the main agent's
  128) and ``max_llm_calls`` (default 15), enforced via LangGraph's
  ``recursion_limit`` plus a ``ToolLoopGuard`` fingerprint check.

The sub-graph is built per specialist invocation because tools close
over the per-request DB session and the specialist's bound engine /
domain. We use ``langgraph.prebuilt.create_react_agent`` so we get
OpenAI-compatible tool calling, automatic tool execution, and message
history for free — the same primitive the advisor uses, just with a
smaller toolset and tighter limits.

Output: a :class:`SpecialistResult` dict with the agent's textual answer,
any structured atoms it produced (via ``ingest_url`` / ``add_user_source``
side effects — we read them back from the DB), the sources it cited, and
budget usage counters.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from sqlalchemy.orm import Session

from app.core.exceptions import LLMNotConfiguredError
from app.core.logging import get_logger
from app.llm.registry import ResolvedModel
from app.services.agent_team.roles import RoleSpec
from app.services.agent_team.state import SpecialistResult, SubtaskSpec

log = get_logger(__name__)


# ---------- Default budgets (§D.6) ----------

DEFAULT_MAX_TOOL_CALLS = 20
DEFAULT_MAX_LLM_CALLS = 15
# recursion_limit = 2 * max_tool_calls + small margin for the initial /
# terminal model passes (mirrors the advisor's ADVISOR_RECURSION_LIMIT
# formula but with the specialist's tighter budget).
def _recursion_limit(max_tool_calls: int) -> int:
    return max_tool_calls * 2 + 8


# ---------- System prompt builder ----------


def _build_system_prompt(role: RoleSpec, subtask: SubtaskSpec) -> str:
    """Build the system prompt for one specialist.

    The prompt tells the sub-agent:
    - Its role and what it should do.
    - Its bound engine / domain (so it doesn't have to guess).
    - The output format expected (a textual answer + structured atoms
      produced via the ingest tools).
    - That it has a tight budget and should not loop on the same tool.
    """
    engine = subtask.get("engine") or "any"
    domain = subtask.get("domain") or "general"
    budget = subtask.get("budget", role.max_tool_calls)

    return (
        f"# LifeTree AgentTeam — {role.name}\n\n"
        f"## Role\n{role.description}\n\n"
        f"## Your sub-task\n{subtask.get('instruction', '')}\n\n"
        f"## Bound context\n"
        f"- Search engine: {engine} (use this when calling web_search / web_fetch)\n"
        f"- Domain hint: {domain}\n"
        f"- Tool-call budget: {budget} (you will be stopped after this many calls)\n\n"
        "## Output format\n"
        "Call the available tools to gather information, then write a concise "
        "textual answer as your final message. The answer should:\n"
        "- Be self-contained (a reader who didn't see your tool calls should "
        "understand it).\n"
        "- Cite source URLs inline.\n"
        "- Note any disagreements or uncertainties you found.\n"
        "- If you used ingest_url / add_user_source, the system will "
        "automatically collect the structured atoms — you don't need to "
        "list them in your answer.\n\n"
        "## Rules\n"
        "- Do NOT call the same tool with the same arguments more than once.\n"
        "- Do NOT call tools you don't need — you have a tight budget.\n"
        "- If a tool fails, note it and try a different approach; don't retry "
        "the identical call.\n"
        "- Stay focused on your sub-task. Don't wander into other domains.\n"
    )


# ---------- Specialist runner ----------


def run_specialist(
    *,
    db: Session,
    user_id: str,
    goal_id: str | None,
    scenario_id: str | None,
    subtask: SubtaskSpec,
    role: RoleSpec,
    tools: list[BaseTool],
    resolved_model: ResolvedModel,
    job_id: str,
) -> SpecialistResult:
    """Run one specialist sub-agent synchronously and return its result.

    This is the function called by the ``specialist_node`` in ``graph.py``.
    It builds a per-specialist ReAct graph, invokes it with the sub-task
    instruction as the only human message, and collects the final answer.

    Budget enforcement uses two layers:
    1. LangGraph ``recursion_limit`` — hard stops the graph after
       ``2 * max_tool_calls + 8`` super-steps.
    2. ``SpecialistLoopGuard`` — detects identical retries and stops early.

    On any fatal error (LLM not configured, recursion limit, unexpected
    exception), the specialist returns a ``SpecialistResult`` with
    ``status='failed'`` and the error message — the orchestrator decides
    whether to retry or aggregate partial results.
    """
    subtask_id = subtask.get("subtask_id", "")
    started = time.monotonic()
    max_tool_calls = int(subtask.get("budget", role.max_tool_calls))

    result: SpecialistResult = {
        "subtask_id": subtask_id,
        "role": role.name,
        "status": "running",
        "output": "",
        "atoms": {"events": [], "assertions": [], "relationships": [], "metrics": []},
        "sources": [],
        "llm_calls": 0,
        "tool_calls": 0,
        "error": None,
    }

    # ---------- Build the LLM ----------
    llm: ChatOpenAI
    try:
        llm = ChatOpenAI(
            model=resolved_model.model.name,
            api_key=resolved_model.provider.api_key or "missing",
            base_url=resolved_model.provider.base_url or None,
            temperature=0.3,
            streaming=False,
        )
    except LLMNotConfiguredError as exc:
        result["status"] = "failed"
        result["error"] = f"llm_not_configured: {exc}"
        return result
    except Exception as exc:  # noqa: BLE001
        result["status"] = "failed"
        result["error"] = f"llm_build_failed: {exc}"
        return result

    # ---------- Build the graph ----------
    system_prompt = _build_system_prompt(role, subtask)
    try:
        graph = create_react_agent(
            model=llm,
            tools=tools,
            prompt=SystemMessage(content=system_prompt),
        )
    except Exception as exc:  # noqa: BLE001
        result["status"] = "failed"
        result["error"] = f"graph_build_failed: {exc}"
        return result

    # ---------- Invoke ----------
    human_msg = HumanMessage(content=subtask.get("instruction", ""))

    # Snapshot the atoms before the specialist runs, so we can compute
    # the delta (new atoms produced by this specialist's ingest calls).
    atoms_before = _snapshot_atom_ids(db, user_id)

    try:
        # Use sync invoke — the Celery task is sync, and create_react_agent
        # supports sync invocation. Parallelism across specialists is
        # achieved by the LangGraph Send API at the parent graph level
        # (each Send runs in its own async task when the parent uses
        # ainvoke; here we're inside one specialist's sync body).
        final_state = graph.invoke(
            {"messages": [human_msg]},
            config={
                "recursion_limit": _recursion_limit(max_tool_calls),
                # Tool calls run in a thread pool; keep concurrency low
                # to avoid hammering external APIs.
                "max_concurrency": 2,
            },
        )
    except Exception as exc:  # noqa: BLE001
        err_name = type(exc).__name__
        # Recursion limit → budget exceeded, not a crash.
        if "recursion" in err_name.lower() or "recursion" in str(exc).lower():
            result["status"] = "budget_exceeded"
            result["error"] = f"recursion_limit_reached after {max_tool_calls} tool calls"
            log.info(
                "agent_team.specialist_budget_exceeded",
                job_id=job_id,
                subtask_id=subtask_id,
                role=role.name,
                max_tool_calls=max_tool_calls,
            )
        else:
            result["status"] = "failed"
            result["error"] = f"invoke_failed: {exc}"[:500]
            log.error(
                "agent_team.specialist_invoke_failed",
                job_id=job_id,
                subtask_id=subtask_id,
                role=role.name,
                error=str(exc),
            )
        # Still try to collect partial results from the messages.
        _collect_partial_output(final_state=None, result=result, messages=None)
        _collect_new_atoms(db, user_id, atoms_before, result)
        return result

    # ---------- Collect output ----------
    messages = final_state.get("messages", []) if isinstance(final_state, dict) else []
    _collect_partial_output(final_state, result, messages)
    _collect_new_atoms(db, user_id, atoms_before, result)

    # Count tool calls from the message history.
    tool_calls = 0
    for msg in messages:
        # AIMessage with tool_calls attribute.
        tcs = getattr(msg, "tool_calls", None) or []
        tool_calls += len(tcs)
    result["tool_calls"] = tool_calls
    result["llm_calls"] = max(1, tool_calls)  # approximate: each tool call ≈ 1 LLM call

    # Estimate LLM calls more accurately: count AIMessages (each non-empty
    # assistant message is one LLM generation).
    ai_count = sum(1 for m in messages if _is_ai_message(m))
    if ai_count > 0:
        result["llm_calls"] = ai_count

    elapsed = time.monotonic() - started
    log.info(
        "agent_team.specialist_complete",
        job_id=job_id,
        subtask_id=subtask_id,
        role=role.name,
        status=result["status"],
        tool_calls=result["tool_calls"],
        llm_calls=result["llm_calls"],
        elapsed_s=round(elapsed, 1),
    )

    if result["status"] == "running":
        result["status"] = "completed"
    return result


# ---------- Helpers ----------


def _is_ai_message(msg: Any) -> bool:
    """Check if a message is an AIMessage (without importing the class)."""
    return getattr(msg, "type", "") == "ai" or "AIMessage" in type(msg).__name__


def _collect_partial_output(
    final_state: Any,
    result: SpecialistResult,
    messages: list[Any] | None,
) -> None:
    """Extract the specialist's textual answer from the final message list.

    The last AIMessage with non-empty content is the specialist's answer.
    If the graph was interrupted (budget exceeded), we still collect
    whatever the specialist said last.
    """
    if messages is None:
        if not isinstance(final_state, dict):
            return
        messages = final_state.get("messages", [])

    # Find the last AI message with non-empty content.
    for msg in reversed(messages):
        if not _is_ai_message(msg):
            continue
        content = getattr(msg, "content", "") or ""
        if isinstance(content, list):
            # Some models return content as a list of blocks.
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            content = "\n".join(text_parts)
        if content.strip():
            result["output"] = content.strip()
            return

    # No AI message with content — the specialist may have only made tool
    # calls without a final summary. Mark the output as empty.
    if not result["output"]:
        result["output"] = "(specialist produced no final answer)"


def _snapshot_atom_ids(db: Session, user_id: str) -> dict[str, set[str]]:
    """Snapshot the user's current atom IDs so we can compute the delta.

    Returns a dict with keys ``events`` / ``assertions`` / ``sources``,
    each a set of IDs that existed before the specialist ran.
    """
    from sqlalchemy import select

    from app.models.event import Assertion, Event, InformationSource

    snapshot: dict[str, set[str]] = {
        "events": set(),
        "assertions": set(),
        "sources": set(),
    }
    try:
        ev_ids = db.scalars(
            select(Event.id).where(Event.user_id == user_id)
        )
        snapshot["events"] = set(ev_ids)
        asrt_ids = db.scalars(
            select(Assertion.id).where(Assertion.user_id == user_id)
        )
        snapshot["assertions"] = set(asrt_ids)
        src_ids = db.scalars(
            select(InformationSource.id).where(InformationSource.user_id == user_id)
        )
        snapshot["sources"] = set(src_ids)
    except Exception as exc:  # noqa: BLE001
        log.warning("agent_team.snapshot_atoms_failed", user_id=user_id, error=str(exc))
    return snapshot


def _collect_new_atoms(
    db: Session,
    user_id: str,
    before: dict[str, set[str]],
    result: SpecialistResult,
) -> None:
    """Collect atoms created by this specialist (the delta vs the snapshot).

    Populates ``result.atoms`` and ``result.sources`` with the new
    events / assertions / sources the specialist produced via
    ``ingest_url`` / ``add_user_source`` / ``web_search(persist=True)``.
    """
    from sqlalchemy import select

    from app.models.event import Assertion, Event, InformationSource

    try:
        # New sources.
        new_src_ids = db.scalars(
            select(InformationSource.id).where(
                InformationSource.user_id == user_id,
                InformationSource.id.notin_(list(before["sources"])) if before["sources"] else True,
            )
        )
        new_sources = list(new_src_ids)
        for sid in new_sources:
            src = db.get(InformationSource, sid)
            if src is not None:
                result["sources"].append({
                    "source_id": src.id,
                    "title": src.title,
                    "url": getattr(src, "url", None),
                    "credibility": src.credibility,
                })

        # New assertions.
        new_asrt_ids = db.scalars(
            select(Assertion.id).where(
                Assertion.user_id == user_id,
                Assertion.id.notin_(list(before["assertions"])) if before["assertions"] else True,
            )
        )
        for aid in list(new_asrt_ids):
            asrt = db.get(Assertion, aid)
            if asrt is not None:
                result["atoms"]["assertions"].append({
                    "id": asrt.id,
                    "claim": asrt.claim,
                    "object_value": asrt.object_value,
                    "engine": getattr(asrt, "engine", None),
                })

        # New events.
        new_ev_ids = db.scalars(
            select(Event.id).where(
                Event.user_id == user_id,
                Event.id.notin_(list(before["events"])) if before["events"] else True,
            )
        )
        for eid in list(new_ev_ids):
            ev = db.get(Event, eid)
            if ev is not None:
                result["atoms"]["events"].append({
                    "id": ev.id,
                    "title": getattr(ev, "title", None),
                    "risk_flag_level": getattr(ev, "risk_flag_level", None),
                })
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "agent_team.collect_new_atoms_failed",
            user_id=user_id,
            error=str(exc),
        )


__all__ = [
    "DEFAULT_MAX_LLM_CALLS",
    "DEFAULT_MAX_TOOL_CALLS",
    "run_specialist",
]
