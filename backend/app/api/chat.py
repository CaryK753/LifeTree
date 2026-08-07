"""intelligent assistant chat endpoint with SSE streaming + LangGraph tool dispatch.

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

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphRecursionError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import SessionLocal, get_db
from app.models.chat_stream import ChatStream
from app.models.goal import Goal, Pathway, Requirement, RiskFactor, pathway_requirements
from app.models.memory import UserMemory
from app.models.scenario import Scenario
from app.models.user import UserProfile
from app.schemas.api import ChatRequest, ChatResponseChunk
from app.services.advisor import (
    build_advisor_graph,
    build_advisor_tools,
    messages_to_langchain,
)
from app.services.advisor.context_compression import (
    compress_history_on_error,
    is_context_length_error,
    maybe_compress_history,
)
from app.services.advisor.loop_guard import (
    ADVISOR_RECURSION_LIMIT,
    RECURSION_LIMIT_MESSAGE,
    TOOL_LOOP_MESSAGE,
    ToolLoopGuard,
)
from app.services.risk_scope import risk_scope_clause
from app.services.user_extensions import build_mcp_tools, skill_context
from app.services.user_runtime import resolve_user_model

log = get_logger(__name__)

# ---------- Background task registry ----------
#
# Keep strong references to running asyncio.Tasks so they aren't GC'd
# when the HTTP request that spawned them returns. Tasks remove themselves
# on completion via a done-callback.
_active_chat_tasks: dict[str, asyncio.Task[None]] = {}

# How many events to buffer before flushing to DB.
_EVENT_FLUSH_BATCH = 5
# Max seconds between DB flushes (ensures low latency for short responses).
_EVENT_FLUSH_INTERVAL = 2.0
# Maximum number of events to retain in the events array. Once exceeded,
# oldest events are trimmed (the accumulated content is in result_content
# on terminal flush). This caps memory + JSONB column size for very long
# responses. The SSE reconnection endpoint uses last_seq indexing, so
# trimming old events only affects clients that reconnect after a very
# long delay — they'll get the result via getChatStream instead.
_EVENT_MAX_RETAINED = 2000

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
        "# User Profile",
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
        parts.append(f"\n# Goal: {goal.title} [id={goal.id}]")
        parts.append(f"- Scenario: {goal.scenario}")
        parts.append(f"- Status: {goal.status}")
        if goal.target_date:
            parts.append(f"- Target date: {goal.target_date}")
        if goal.success_probability:
            parts.append(f"- Success probability: {goal.success_probability}")

        pathways = list(db.scalars(select(Pathway).where(Pathway.goal_id == goal.id)))
        for p in pathways[:3]:
            parts.append(f"\n## Pathway: {p.name} ({p.status}) [id={p.id}]")
            reqs = list(
                db.scalars(
                    select(Requirement)
                    .join(
                        pathway_requirements,
                        pathway_requirements.c.requirement_id == Requirement.id,
                    )
                    .where(pathway_requirements.c.pathway_id == p.id)
                    .order_by(Requirement.weight.desc())
                    .limit(10)
                )
            )
            if not reqs:
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
                    f"  - Requirement: {r.name} ({r.type}) [id={r.id}] "
                    f"threshold={r.threshold} current={r.current_value} "
                    f"gap={r.gap_status}"
                )

    risk_owner_id = goal.user_id if goal is not None else user.id
    rfs = list(
        db.scalars(
            select(RiskFactor)
            .where(
                RiskFactor.deleted_at.is_(None),
                risk_scope_clause(risk_owner_id),
            )
            .order_by(RiskFactor.level.desc())
            .limit(8)
        )
    )
    if rfs:
        parts.append("\n# Top Risk Factors")
        for rf in rfs:
            parts.append(
                f"- {rf.name} [{rf.type}|id={rf.id}] "
                f"level={rf.level} urgency={rf.urgency}"
            )

    if scenario is not None:
        parts.append(f"\n# Active Scenario: {scenario.name} [id={scenario.id}]")
        if scenario.pathway_id:
            parts.append(f"- Pathway ID: {scenario.pathway_id}")
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


# ---------- Background agent execution ----------


def _parse_tool_output(raw_output: Any) -> Any:
    """Extract a JSON-serializable result from a LangGraph tool output."""
    try:
        if hasattr(raw_output, "content"):
            content = raw_output.content
            if isinstance(content, str):
                try:
                    return json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    return content
            elif isinstance(content, (dict, list)):
                return content
            else:
                return {"value": str(raw_output)}
        elif isinstance(raw_output, dict):
            return raw_output
        elif isinstance(raw_output, str):
            try:
                return json.loads(raw_output)
            except (json.JSONDecodeError, TypeError):
                return raw_output
        else:
            return {"value": str(raw_output)}
    except Exception:  # noqa: BLE001
        return {"value": str(raw_output)}


async def _run_agent_background(
    stream_id: str,
    graph: Any,
    lc_messages: Any,
    history_dicts: list[dict[str, Any]] | None = None,
) -> None:
    """Run the advisor agent in the background, persisting SSE events to DB.

    Spawned as an ``asyncio.Task`` by ``chat_stream``. Runs independently
    of the SSE connection — if the client disconnects, the task continues
    and the frontend can reconnect via ``GET /chat/stream/{stream_id}/events``.

    ``history_dicts`` is the original conversation history in plain-dict
    form. It's retained so that if the LLM returns a context-length-exceeded
    error, we can compress the history (via the chat model) and retry
    without needing the caller to pass the history again.
    """
    events: list[dict[str, Any]] = []
    full_content: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    seq = 0
    last_flush = datetime.now(timezone.utc)
    loop_guard = ToolLoopGuard()
    # Track whether we've already attempted a compression-retry to avoid
    # infinite loops if the compressed history still exceeds the limit.
    _compression_attempted = False

    async def _run_stream(msgs: Any) -> None:
        """Stream graph events to the SSE buffer + DB.

        Raises on error — the caller decides whether to retry (after
        compression) or surface the error to the user.
        """
        nonlocal seq, last_flush
        async for event in graph.astream_events(
            {"messages": msgs},
            version="v2",
            config={"max_concurrency": 1, "recursion_limit": ADVISOR_RECURSION_LIMIT},
        ):
            kind = event.get("event")
            sse_data: dict[str, Any] | None = None

            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk is None:
                    continue
                delta = getattr(chunk, "content", "") or ""
                if isinstance(delta, list):
                    delta = "".join(
                        b.get("text", "") for b in delta if isinstance(b, dict)
                    )
                reasoning_delta = ""
                additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
                reasoning_content = additional_kwargs.get("reasoning_content")
                if reasoning_content:
                    if isinstance(reasoning_content, str):
                        reasoning_delta = reasoning_content
                    elif isinstance(reasoning_content, list):
                        reasoning_delta = "".join(
                            b.get("text", "") for b in reasoning_content if isinstance(b, dict)
                        )
                if not reasoning_delta:
                    response_metadata = getattr(chunk, "response_metadata", {}) or {}
                    reasoning_meta = response_metadata.get("reasoning_content") or response_metadata.get("reasoning")
                    if isinstance(reasoning_meta, str):
                        reasoning_delta = reasoning_meta

                if not delta and not reasoning_delta:
                    continue
                if delta:
                    full_content.append(delta)
                sse_data = {"delta": delta, "reasoning_delta": reasoning_delta or None}

            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                run_id = event.get("run_id", "")
                raw_args = event.get("data", {}).get("input", {})
                args = raw_args if isinstance(raw_args, dict) else {}
                stop_reason = loop_guard.record(tool_name, args)
                if stop_reason is not None:
                    log.warning(
                        "chat.tool_loop_stopped",
                        reason=stop_reason, tool=tool_name, total_calls=loop_guard.total_calls,
                    )
                    events.append({"seq": seq, "data": {"delta": f"\n\n{TOOL_LOOP_MESSAGE}", "finish_reason": "tool_loop"}})
                    seq += 1
                    events.append({"seq": seq, "data": "[DONE]"})
                    _flush(
                        status="completed",
                        result_content="".join(full_content) + f"\n\n{TOOL_LOOP_MESSAGE}",
                        result_tool_calls=tool_calls or None,
                    )
                    return
                sse_data = {"delta": "", "tool_call": {"name": tool_name, "args": args, "result": None, "id": run_id}}

            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                run_id = event.get("run_id", "")
                raw_output = event.get("data", {}).get("output")
                result = _parse_tool_output(raw_output)
                tool_calls.append({"name": tool_name, "result": result, "id": run_id})
                sse_data = {"delta": "", "tool_call": {"name": tool_name, "args": {}, "result": result, "id": run_id}}

            elif kind == "on_tool_error":
                tool_name = event.get("name", "")
                run_id = event.get("run_id", "")
                err_obj = event.get("data", {}).get("error") or event.get("data", {})
                result = {"error": str(err_obj)}
                sse_data = {"delta": "", "tool_call": {"name": tool_name, "args": {}, "result": result, "id": run_id}}

            if sse_data is not None:
                events.append({"seq": seq, "data": sse_data})
                seq += 1
                now = datetime.now(timezone.utc)
                if seq % _EVENT_FLUSH_BATCH == 0 or (now - last_flush).total_seconds() >= _EVENT_FLUSH_INTERVAL:
                    _flush()
                    last_flush = now

        # Final done event
        events.append({"seq": seq, "data": {"delta": "", "finish_reason": "stop"}})
        seq += 1
        events.append({"seq": seq, "data": "[DONE]"})
        _flush(
            status="completed",
            result_content="".join(full_content),
            result_tool_calls=tool_calls or None,
        )

    def _flush(status: str = "running", **extra: Any) -> None:
        """Batch-write accumulated events + status to DB.

        On terminal states (completed/failed/cancelled) we clear the
        events array to free space — the final result is in
        ``result_content`` / ``result_tool_calls``, and the frontend
        uses ``GET /chat/stream/{id}`` (not event replay) to restore
        a completed stream. This prevents the JSONB column from growing
        unboundedly for long conversations.
        """
        try:
            with SessionLocal() as session:
                stream = session.get(ChatStream, stream_id)
                if stream is None:
                    return
                if status == "running":
                    # Cap retained events to prevent unbounded JSONB growth.
                    # If we exceed the cap, trim oldest events — the SSE
                    # reader tracks by index, so it will just see fewer
                    # historical events on reconnect (the accumulated text
                    # is safe in full_content and will be in result_content
                    # once the stream completes).
                    if len(events) > _EVENT_MAX_RETAINED:
                        del events[: len(events) - _EVENT_MAX_RETAINED]
                    stream.events = list(events)
                else:
                    # Terminal: clear events to free space. The final
                    # result is in result_content / result_tool_calls.
                    stream.events = []
                    stream.status = status
                    stream.completed_at = datetime.now(timezone.utc)
                for k, v in extra.items():
                    setattr(stream, k, v)
                session.commit()
        except Exception as exc:  # noqa: BLE001
            log.error("chat.flush_failed", stream_id=stream_id, error=str(exc))

    try:
        await _run_stream(lc_messages)
        log.info("chat.background_completed", stream_id=stream_id, events=seq)

    except GraphRecursionError:
        log.warning("chat.background_recursion_stopped", stream_id=stream_id, total_calls=loop_guard.total_calls)
        events.append({"seq": seq, "data": {"delta": f"\n\n{RECURSION_LIMIT_MESSAGE}", "finish_reason": "tool_loop"}})
        seq += 1
        events.append({"seq": seq, "data": "[DONE]"})
        _flush(
            status="completed",
            result_content="".join(full_content) + f"\n\n{RECURSION_LIMIT_MESSAGE}",
            result_tool_calls=tool_calls or None,
        )
    except asyncio.CancelledError:
        # Task was cancelled (DELETE /chat/stream/{id} or process shutdown).
        log.info("chat.background_cancelled", stream_id=stream_id)
        events.append({"seq": seq, "data": "[DONE]"})
        _flush(
            status="cancelled",
            result_content="".join(full_content),
            result_tool_calls=tool_calls or None,
        )
        raise  # Re-raise so the asyncio.Task is properly marked as cancelled.
    except Exception as exc:  # noqa: BLE001
        # Context-length-exceeded → compress history and retry once.
        if (
            is_context_length_error(exc)
            and not _compression_attempted
            and history_dicts
        ):
            log.warning(
                "chat.context_length_exceeded",
                stream_id=stream_id,
                error=str(exc)[:200],
            )
            _compression_attempted = True

            compressed = await compress_history_on_error(history_dicts)
            new_lc_messages = messages_to_langchain(compressed)

            # Reset state for the retry.
            events.clear()
            full_content.clear()
            tool_calls.clear()
            seq = 0
            last_flush = datetime.now(timezone.utc)
            loop_guard = ToolLoopGuard()

            # Notify the frontend that context was compressed.
            events.append({
                "seq": seq,
                "data": {
                    "delta": "\n\n[Context automatically compressed to fit the model's context window.]\n\n",
                    "finish_reason": None,
                },
            })
            seq += 1
            _flush()

            try:
                await _run_stream(new_lc_messages)
                log.info(
                    "chat.background_completed_after_compression",
                    stream_id=stream_id,
                    events=seq,
                )
                return
            except Exception as retry_exc:  # noqa: BLE001
                import traceback
                log.error(
                    "chat.background_failed_after_compression",
                    stream_id=stream_id,
                    error=str(retry_exc),
                    traceback=traceback.format_exc(),
                )
                events.append({"seq": seq, "data": {"delta": f"\n\n[stream error after compression: {retry_exc}]", "finish_reason": "error"}})
                seq += 1
                events.append({"seq": seq, "data": "[DONE]"})
                _flush(
                    status="failed",
                    error=str(retry_exc)[:1000],
                    result_content="".join(full_content),
                    result_tool_calls=tool_calls or None,
                )
                return

        import traceback
        log.error("chat.background_failed", stream_id=stream_id, error=str(exc), traceback=traceback.format_exc())
        events.append({"seq": seq, "data": {"delta": f"\n\n[stream error: {exc}]", "finish_reason": "error"}})
        seq += 1
        events.append({"seq": seq, "data": "[DONE]"})
        _flush(
            status="failed",
            error=str(exc)[:1000],
            result_content="".join(full_content),
            result_tool_calls=tool_calls or None,
        )


# ---------- Chat stream endpoints ----------


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest, current_user: CurrentUser, db: Session = Depends(get_db)
) -> StreamingResponse:
    """SSE stream of ChatResponseChunk JSON objects.

    Creates a ``ChatStream`` record, launches the agent in a background
    ``asyncio.Task`` (so it survives client disconnects), then streams
    events from the DB to the SSE client. The first event carries the
    ``stream_id`` so the frontend can reconnect via
    ``GET /chat/stream/{stream_id}/events`` if the connection drops.
    """
    user = current_user
    resolved_model = resolve_user_model(db, user.id, "chat", payload.model_id)
    if resolved_model is None:
        raise HTTPException(400, "Selected model is unavailable or cannot serve chat")

    goal = db.get(Goal, payload.goal_id) if payload.goal_id else None
    if goal is not None and goal.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this goal")

    scenario = db.get(Scenario, payload.scenario_id) if payload.scenario_id else None
    if scenario is not None:
        scenario_goal = db.get(Goal, scenario.goal_id)
        if scenario_goal is None or (
            scenario_goal.user_id != user.id and user.role != "admin"
        ):
            raise HTTPException(403, "You do not have access to this scenario")

    context_block = _build_context_block(db, user, goal, scenario)
    user_skills = skill_context(db, user.id, payload.enabled_skills)
    if user_skills:
        context_block = f"{context_block}\n\n{user_skills}"

    tools = build_advisor_tools(
        db,
        user_id=user.id,
        goal_id=payload.goal_id,
        scenario_id=payload.scenario_id,
        include_web_search=payload.web_search,
        include_web_fetch=payload.web_search,
    )
    if payload.enabled_mcp_servers is not None:
        mcp_tools = build_mcp_tools(db, user.id, payload.enabled_mcp_servers)
    else:
        mcp_tools = build_mcp_tools(db, user.id)
    tools.extend(mcp_tools)

    graph = build_advisor_graph(
        tools=tools,
        context_block=context_block,
        resolved_model=resolved_model,
    )

    history = [m.model_dump() for m in payload.messages if m.role != "system"]
    # Proactive compression: if the conversation is long enough to
    # approach the model's context window, summarise older turns using
    # the configured chat model. Falls back to simple truncation if the
    # chat model isn't configured or summarisation fails.
    history = await maybe_compress_history(history)
    lc_messages = messages_to_langchain(history)

    # Extract user's last message for preview
    user_msg_preview = ""
    for m in reversed(payload.messages):
        if m.role == "user":
            user_msg_preview = (m.content or "")[:200]
            break

    # ---- Ephemeral mode (persist=False) ----
    #
    # For ephemeral calls like title generation, we skip ChatStream
    # creation and stream directly from the agent. No reconnection
    # support, but no DB overhead either — avoids accumulating
    # hundreds of throw-away ChatStream rows.
    if not payload.persist:
        async def ephemeral_generator():
            loop_guard = ToolLoopGuard()
            try:
                async for event in graph.astream_events(
                    {"messages": lc_messages},
                    version="v2",
                    config={"max_concurrency": 1, "recursion_limit": ADVISOR_RECURSION_LIMIT},
                ):
                    kind = event.get("event")
                    sse_data: dict[str, Any] | None = None
                    if kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk is None:
                            continue
                        delta = getattr(chunk, "content", "") or ""
                        if isinstance(delta, list):
                            delta = "".join(
                                b.get("text", "") for b in delta if isinstance(b, dict)
                            )
                        if not delta:
                            continue
                        sse_data = {"delta": delta}
                    elif kind == "on_tool_start":
                        tool_name = event.get("name", "")
                        run_id = event.get("run_id", "")
                        raw_args = event.get("data", {}).get("input", {})
                        args = raw_args if isinstance(raw_args, dict) else {}
                        stop_reason = loop_guard.record(tool_name, args)
                        if stop_reason is not None:
                            yield f"data: {json.dumps({'delta': TOOL_LOOP_MESSAGE, 'finish_reason': 'tool_loop'})}\n\n"
                            yield "data: [DONE]\n\n"
                            return
                        sse_data = {"delta": "", "tool_call": {"name": tool_name, "args": args, "result": None, "id": run_id}}
                    elif kind == "on_tool_end":
                        tool_name = event.get("name", "")
                        run_id = event.get("run_id", "")
                        raw_output = event.get("data", {}).get("output")
                        result = _parse_tool_output(raw_output)
                        sse_data = {"delta": "", "tool_call": {"name": tool_name, "args": {}, "result": result, "id": run_id}}
                    if sse_data is not None:
                        yield f"data: {json.dumps(sse_data, default=str)}\n\n"
                yield f"data: {json.dumps({'delta': '', 'finish_reason': 'stop'})}\n\n"
                yield "data: [DONE]\n\n"
            except GraphRecursionError:
                yield f"data: {json.dumps({'delta': RECURSION_LIMIT_MESSAGE, 'finish_reason': 'tool_loop'})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:  # noqa: BLE001
                yield f"data: {json.dumps({'delta': f'[stream error: {exc}]', 'finish_reason': 'error'})}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            ephemeral_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ---- Persistent mode (persist=True, default) ----
    #
    # Create a ChatStream record, launch the agent in a background
    # asyncio.Task (so it survives client disconnects), then stream
    # events from the DB to the SSE client.
    stream = ChatStream(
        user_id=user.id,
        status="running",
        goal_id=str(payload.goal_id) if payload.goal_id else None,
        scenario_id=str(payload.scenario_id) if payload.scenario_id else None,
        model_id=str(payload.model_id) if payload.model_id else None,
        user_message_preview=user_msg_preview,
        events=[],
        started_at=datetime.now(timezone.utc),
    )
    db.add(stream)
    db.commit()
    db.refresh(stream)

    # Launch background task (survives client disconnect)
    task = asyncio.create_task(
        _run_agent_background(stream.id, graph, lc_messages, history_dicts=history)
    )
    _active_chat_tasks[stream.id] = task
    task.add_done_callback(lambda t: _active_chat_tasks.pop(stream.id, None))

    stream_id = stream.id

    async def event_generator():
        try:
            # First event: stream_id for reconnection
            yield f"data: {json.dumps({'stream_id': stream_id})}\n\n"

            last_seq = 0
            while True:
                # Expire all cached objects so db.get() reads fresh data
                # from the DB. The background task writes via its own
                # SessionLocal(), so without this the request's session
                # would return a stale cached ChatStream with the old
                # events list, and the SSE reader would never see new tokens.
                db.expire_all()
                fresh = db.get(ChatStream, stream_id)
                if fresh is None:
                    yield "data: [DONE]\n\n"
                    return

                events_list = fresh.events or []
                for i in range(last_seq, len(events_list)):
                    evt = events_list[i]
                    data = evt.get("data")
                    if data == "[DONE]":
                        yield "data: [DONE]\n\n"
                        return
                    yield f"data: {json.dumps(data, default=str)}\n\n"
                last_seq = len(events_list)

                if fresh.status in ("completed", "failed", "cancelled"):
                    yield "data: [DONE]\n\n"
                    return

                await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            # Client disconnected — background task continues
            log.info("chat.sse.client_disconnected", stream_id=stream_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream/{stream_id}/events")
async def reconnect_stream(
    stream_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
    last_seq: int = Query(0, ge=0, description="Resume from this event index"),
) -> StreamingResponse:
    """Reconnect to a chat stream after a connection drop or page reload.

    Replays events starting from ``last_seq`` (0 = from the beginning),
    then continues streaming live events until the stream reaches a
    terminal state. The client passes the index of the last event it
    successfully consumed so it doesn't receive duplicates.
    """
    stream = db.get(ChatStream, stream_id)
    if stream is None or stream.user_id != user.id:
        raise HTTPException(status_code=404, detail="chat_stream_not_found")

    sid = stream.id

    async def event_generator():
        cursor = last_seq
        while True:
            # expire_all() forces fresh DB reads (see chat_stream for details)
            db.expire_all()
            fresh = db.get(ChatStream, sid)
            if fresh is None:
                yield "data: [DONE]\n\n"
                return

            events_list = fresh.events or []
            for i in range(cursor, len(events_list)):
                evt = events_list[i]
                data = evt.get("data")
                if data == "[DONE]":
                    yield "data: [DONE]\n\n"
                    return
                yield f"data: {json.dumps(data, default=str)}\n\n"
            cursor = len(events_list)

            if fresh.status in ("completed", "failed", "cancelled"):
                yield "data: [DONE]\n\n"
                return

            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream/{stream_id}")
def get_stream(
    stream_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    """Get a chat stream's current state (for restore without SSE)."""
    stream = db.get(ChatStream, stream_id)
    if stream is None or stream.user_id != user.id:
        raise HTTPException(status_code=404, detail="chat_stream_not_found")
    return {
        "id": stream.id,
        "status": stream.status,
        "result_content": stream.result_content,
        "result_tool_calls": stream.result_tool_calls,
        "error": stream.error,
        "started_at": stream.started_at.isoformat() if stream.started_at else None,
        "completed_at": stream.completed_at.isoformat() if stream.completed_at else None,
        "event_count": len(stream.events or []),
    }


@router.get("/streams")
def list_streams(
    user: CurrentUser,
    db: Session = Depends(get_db),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    """List the current user's chat streams (newest first)."""
    stmt = (
        select(ChatStream)
        .where(ChatStream.user_id == user.id)
        .order_by(ChatStream.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status:
        stmt = stmt.where(ChatStream.status == status)
    streams = list(db.scalars(stmt))
    return [
        {
            "id": s.id,
            "status": s.status,
            "user_message_preview": s.user_message_preview[:100],
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in streams
    ]


@router.delete("/stream/{stream_id}", status_code=204)
def delete_stream(
    stream_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> None:
    """Delete a chat stream."""
    stream = db.get(ChatStream, stream_id)
    if stream is None or stream.user_id != user.id:
        raise HTTPException(status_code=404, detail="chat_stream_not_found")

    # Cancel background task if still running
    task = _active_chat_tasks.pop(stream_id, None)
    if task and not task.done():
        task.cancel()

    db.delete(stream)
    db.commit()
    log.info("chat.stream_deleted", stream_id=stream_id, user_id=user.id)
