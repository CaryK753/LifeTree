"""AI advisor chat endpoint with SSE streaming + LangGraph tool dispatch.

Per project plan §5 + §7.3. The endpoint builds a per-request LangGraph
ReAct agent (``create_react_agent``) with tools bound to the request's DB
session and user/goal/scenario context, then streams LangGraph events to
the frontend as SSE chunks.

Streaming protocol (SSE):
- ``data: {delta, finish_reason?}\n\n`` — model token deltas
- ``data: {tool_call: {name, args, result}}\n\n`` — tool execution trace
- ``data: [DONE]\n\n`` — terminal sentinel

If the LLM is not configured, returns a 503 (``LLMNotConfiguredError``).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import LLMNotConfiguredError
from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.llm.client import get_chat_model
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.models.memory import UserMemory
from app.models.scenario import Scenario
from app.models.user import UserProfile
from app.schemas.api import ChatRequest, ChatResponseChunk
from app.services.advisor import (
    build_advisor_graph,
    build_advisor_tools,
    messages_to_langchain,
)

log = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def _build_context_block(
    db: Session, user: UserProfile, goal: Goal | None, scenario: Scenario | None
) -> str:
    """Compose a compact context string for the system prompt.

    Note: profile fields (demographics, priority_factors, risk_tolerance,
    primary_goal_id, implicit_tags) are injected directly here rather than
    being mirrored into the UserMemory table. The memory channel is for
    free-form facts the LLM discovers in conversation; structured profile
    fields belong in the system prompt so the LLM always sees the latest
    values without a tool round-trip.
    """
    parts: list[str] = [
        f"# User Profile",
        f"- Name: {user.display_name}",
        f"- Risk tolerance: {user.risk_tolerance}",
        f"- Priority factors: {user.priority_factors}",
        f"- Progress: {user.progress}",
        f"- Lifecycle stage: {user.lifecycle_stage}",
        f"- Cruising mode: {'on' if user.cruising_mode else 'off'}",
    ]

    # Demographics hold the user's core "who am I" facts: age, nationality,
    # education, language scores, fund range, location, family, joint
    # profiles, etc. Surface them as a compact JSON so the LLM can ground
    # its advice in the user's actual situation.
    if user.demographics:
        parts.append(
            f"- Demographics: {json.dumps(user.demographics, ensure_ascii=False)}"
        )

    # Implicit tags are behavior-derived labels (e.g. "risk-averse",
    # "detail-oriented") that help the LLM tailor tone.
    if user.implicit_tags:
        parts.append(
            f"- Implicit tags: {json.dumps(user.implicit_tags, ensure_ascii=False)}"
        )

    # If the client didn't pass a goal_id, fall back to the user's primary
    # goal so the LLM always has goal context. This is the common case —
    # the chat panel rarely sends goal_id explicitly.
    if goal is None and user.primary_goal_id:
        goal = db.get(Goal, user.primary_goal_id)

    if goal is not None:
        parts.append(f"\n# Goal: {goal.title}")
        parts.append(f"- Scenario: {goal.scenario}")
        parts.append(f"- Status: {goal.status}")
        if goal.target_date:
            parts.append(f"- Target date: {goal.target_date}")
        if goal.success_probability:
            parts.append(f"- Success probability: {goal.success_probability}")

        pathways = list(db.scalars(select(Pathway).where(Pathway.goal_id == goal.id)))
        for p in pathways[:3]:
            parts.append(f"\n## Pathway: {p.name} ({p.status})")
            reqs = list(
                db.scalars(
                    select(Requirement)
                    .where(Requirement.pathway_id == p.id)
                    .order_by(Requirement.weight.desc())
                    .limit(10)
                )
            )
            for r in reqs:
                parts.append(
                    f"  - Requirement: {r.name} ({r.type}) "
                    f"threshold={r.threshold} current={r.current_value} "
                    f"gap={r.gap_status}"
                )

    rfs = list(
        db.scalars(select(RiskFactor).order_by(RiskFactor.level.desc()).limit(8))
    )
    if rfs:
        parts.append("\n# Top Risk Factors")
        for rf in rfs:
            parts.append(
                f"- {rf.name} [{rf.type}] level={rf.level} urgency={rf.urgency}"
            )

    if scenario is not None:
        parts.append(f"\n# Active Scenario: {scenario.name}")
        parts.append(
            f"- Assumptions: {json.dumps(scenario.assumptions, ensure_ascii=False)}"
        )
        if scenario.success_probability:
            parts.append(f"- Computed probability: {scenario.success_probability}")

    # Memories: surface a diverse, recency-weighted set so the LLM has prior
    # context without bloating the prompt. The full list is still queryable
    # via the `list_memories` tool.
    #
    # Selection strategy (avoids the failure mode where 15 memories all come
    # from the same category, which would starve the model of broader context):
    #   1. Pull a candidate pool (top ~60 by importance, then recency).
    #   2. Score each memory by a blended score:
    #        0.6 * importance + 0.4 * recency_norm
    #      where recency_norm is in [0, 1] (1 = newest in the pool).
    #   3. Greedily pick memories, capping per-category diversity so no single
    #      category dominates the final 15.
    mems = _select_memories_for_context(db, user.id, limit=15)
    if mems:
        parts.append("\n# Memories (previously remembered facts about the user)")
        for m in mems:
            parts.append(
                f"- [{m.category}|imp={m.importance:.2f}|id={m.id}] {m.content}"
            )

    return "\n".join(parts)


def _select_memories_for_context(
    db: Session, user_id: str, *, limit: int = 15, pool_size: int = 60
) -> list[UserMemory]:
    """Select a diverse, recency-weighted set of memories for the system prompt.

    Pulls a candidate pool ordered by importance then recency, scores each
    memory as ``0.6 * importance + 0.4 * recency_norm`` (recency_norm in
    [0, 1], 1 = newest in the pool), and greedily picks the highest-scoring
    memories while enforcing a per-category cap so no single category
    dominates. Falls back to plain importance ordering if the pool is small.
    """
    pool = list(
        db.scalars(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.importance.desc(), UserMemory.created_at.desc())
            .limit(pool_size)
        )
    )
    if not pool:
        return []
    if len(pool) <= limit:
        return pool

    # Compute recency_norm: newest memory → 1.0, oldest in pool → ~0.0.
    timestamps = [m.created_at for m in pool if m.created_at is not None]
    if not timestamps:
        # No timestamps available — fall back to importance-only ordering.
        return pool[:limit]
    ts_min = min(timestamps)
    ts_max = max(timestamps)
    span = (ts_max - ts_min).total_seconds() or 1.0

    def score(m: UserMemory) -> float:
        recency_norm = (
            (m.created_at - ts_min).total_seconds() / span
            if m.created_at is not None
            else 0.0
        )
        return 0.6 * float(m.importance) + 0.4 * recency_norm

    # Sort the pool by blended score descending, then greedily pick while
    # enforcing per-category diversity. The cap is ``ceil(limit / 4)`` so
    # no single category can take more than ~25% of the slots — this keeps
    # any one category (e.g. 'career') from crowding out family / health /
    # finance context.
    per_category_cap = max(2, (limit + 3) // 4)
    category_counts: dict[str, int] = {}
    selected: list[UserMemory] = []
    for m in sorted(pool, key=score, reverse=True):
        if len(selected) >= limit:
            break
        cnt = category_counts.get(m.category, 0)
        if cnt >= per_category_cap:
            continue
        selected.append(m)
        category_counts[m.category] = cnt + 1

    # If we still have slots (because some categories were thin), fill from
    # the remaining highest-scored memories ignoring the cap.
    if len(selected) < limit:
        chosen_ids = {m.id for m in selected}
        for m in sorted(pool, key=score, reverse=True):
            if len(selected) >= limit:
                break
            if m.id in chosen_ids:
                continue
            selected.append(m)
            chosen_ids.add(m.id)

    return selected


# Token budget for conversation history. Leaves room for the system prompt
# (with context block) + tools + the model's response. Most modern chat
# models support 128k+ tokens; 100k is a safe upper bound that leaves
# ~28k tokens of headroom.
_CONVERSATION_TOKEN_BUDGET = 100_000


def _estimate_tokens(text: str) -> int:
    """Rough per-message token estimate.

    Uses ``len(text) * 0.5`` as a blended estimate between English
    (~``len/3`` tokens/char) and Chinese (~``len/1.5``). Conservative on
    purpose — over-estimating slightly just truncates a bit earlier, which
    is safer than under-estimating and blowing the context window.
    """
    if not text:
        return 0
    return int(len(text) * 0.5)


def _truncate_to_token_budget(
    history: list[dict[str, Any]],
    *,
    budget: int = _CONVERSATION_TOKEN_BUDGET,
) -> list[dict[str, Any]]:
    """Truncate conversation history to fit within a token budget.

    If the total exceeds ``budget``, drops the oldest messages while:
      - Always keeping the first user message (so the model retains the
        original ask).
      - Keeping each "assistant + immediately following tool messages"
        group atomic — a tool result without its preceding assistant
        tool_call would cause the model to error.

    Inserts a system note ``[Earlier conversation history truncated]`` at
    the truncation point so the model knows context was dropped.
    """
    if not history:
        return []

    # Group messages into atomic units: an assistant message followed by
    # any number of tool messages forms one group; everything else is its
    # own group. This keeps a tool result tied to its preceding assistant
    # tool_call (dropping one without the other would corrupt the message
    # stream the model sees).
    groups: list[list[dict[str, Any]]] = []
    for m in history:
        role = m.get("role")
        if (
            role == "tool"
            and groups
            and groups[-1][-1].get("role") in ("assistant", "tool")
        ):
            groups[-1].append(m)
        else:
            groups.append([m])

    def group_tokens(group: list[dict[str, Any]]) -> int:
        total = 0
        for m in group:
            content = m.get("content") or ""
            if isinstance(content, str):
                total += _estimate_tokens(content)
            # tool_calls add a small overhead; estimate from json length.
            for tc in m.get("tool_calls") or []:
                try:
                    total += _estimate_tokens(json.dumps(tc, ensure_ascii=False))
                except (TypeError, ValueError):
                    pass
        return total

    total_tokens = sum(group_tokens(g) for g in groups)
    if total_tokens <= budget:
        return history

    # Always keep the first user-message group (the original ask).
    first_user_idx = next(
        (i for i, g in enumerate(groups) if g[0].get("role") == "user"),
        None,
    )

    # Walk from the most recent group backwards, accumulating tokens until
    # the budget is exhausted.
    kept_indices: set[int] = set()
    running = 0
    for i in range(len(groups) - 1, -1, -1):
        g_tokens = group_tokens(groups[i])
        if running + g_tokens > budget:
            break
        running += g_tokens
        kept_indices.add(i)

    # Force-include the first user group, even if it overshoots the budget
    # — losing the original ask would leave the model without context.
    if first_user_idx is not None:
        kept_indices.add(first_user_idx)

    # Build the final list, inserting a truncation marker at any gap so
    # the model knows older turns were elided.
    sorted_kept = sorted(kept_indices)
    out: list[dict[str, Any]] = []
    prev_idx = None
    for idx in sorted_kept:
        if prev_idx is not None and idx > prev_idx + 1:
            out.append(
                {
                    "role": "system",
                    "content": "[Earlier conversation history truncated]",
                }
            )
        out.extend(groups[idx])
        prev_idx = idx

    return out


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest, current_user: CurrentUser, db: Session = Depends(get_db)
) -> StreamingResponse:
    """SSE stream of ChatResponseChunk JSON objects.

    Streams both model token deltas and tool-call events from the LangGraph
    advisor agent. Each SSE event is ``data: {json}\n\n``; the stream ends
    with ``data: [DONE]\n\n``.
    """
    # Verify the chat role is configured before streaming; raises
    # LLMNotConfiguredError (-> 503) if no chat model is assigned.
    get_chat_model()

    # Use the authenticated user, ignoring any client-supplied user_id to
    # prevent cross-user memory/profile exfiltration. In single-user mode
    # CurrentUser falls back to the default user, so behavior is unchanged.
    user = current_user

    goal = db.get(Goal, payload.goal_id) if payload.goal_id else None
    # Verify goal ownership (admin can read any goal).
    if goal is not None and goal.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this goal")

    scenario = db.get(Scenario, payload.scenario_id) if payload.scenario_id else None
    # Verify scenario ownership via its parent goal.
    if scenario is not None:
        scenario_goal = db.get(Goal, scenario.goal_id)
        if scenario_goal is None or (
            scenario_goal.user_id != user.id and user.role != "admin"
        ):
            raise HTTPException(403, "You do not have access to this scenario")

    context_block = _build_context_block(db, user, goal, scenario)

    # Build per-request tools + graph. The tools close over `db` so the agent
    # can read the latest ontology state on every tool call.
    tools = build_advisor_tools(
        db,
        goal_id=payload.goal_id,
        scenario_id=payload.scenario_id,
    )
    graph = build_advisor_graph(tools=tools, context_block=context_block)

    # Convert OpenAI-style message history to langchain messages. The system
    # prompt is owned by the graph (via ``prompt=``), so we drop any system
    # messages from the client.
    history = [m.model_dump() for m in payload.messages if m.role != "system"]
    # Cap conversation history to a token budget so long chats don't exceed
    # the model's context window. The budget leaves room for the system
    # prompt (with context block) + tools + the model's response.
    history = _truncate_to_token_budget(history, budget=100_000)
    lc_messages = messages_to_langchain(history)

    async def event_generator():
        try:
            # ``astream`` yields LangGraph stream events. We care about:
            #   - ``on_chat_model_stream``: token deltas from the LLM
            #   - ``on_tool_start`` / ``on_tool_end``: tool call trace
            async for event in graph.astream_events(
                {"messages": lc_messages},
                version="v2",
            ):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk is None:
                        continue
                    delta = getattr(chunk, "content", "") or ""
                    if isinstance(delta, list):
                        # Some providers return content blocks; extract text
                        delta = "".join(
                            b.get("text", "") for b in delta if isinstance(b, dict)
                        )
                    if not delta:
                        continue
                    out = ChatResponseChunk(delta=delta)
                    yield f"data: {out.model_dump_json()}\n\n"

                elif kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    raw_args = event.get("data", {}).get("input", {})
                    args = raw_args if isinstance(raw_args, dict) else {}
                    out = ChatResponseChunk(
                        delta="",
                        tool_call={"name": tool_name, "args": args, "result": None},
                    )
                    yield f"data: {out.model_dump_json()}\n\n"

                elif kind == "on_tool_end":
                    tool_name = event.get("name", "")
                    raw_output = event.get("data", {}).get("output")
                    try:
                        if hasattr(raw_output, "content"):
                            result = json.loads(raw_output.content)
                        elif isinstance(raw_output, dict):
                            result = raw_output
                        else:
                            result = {"value": str(raw_output)}
                    except Exception:  # noqa: BLE001
                        result = {"value": str(raw_output)}
                    out = ChatResponseChunk(
                        delta="",
                        tool_call={"name": tool_name, "args": {}, "result": result},
                    )
                    yield f"data: {out.model_dump_json()}\n\n"

            # Final chunk with finish_reason so the client can close cleanly.
            done = ChatResponseChunk(delta="", finish_reason="stop")
            yield f"data: {done.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:  # noqa: BLE001
            log.error("chat.stream_failed", error=str(exc))
            err = ChatResponseChunk(
                delta=f"\n\n[stream error: {exc}]",
                finish_reason="error",
            )
            yield f"data: {err.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
