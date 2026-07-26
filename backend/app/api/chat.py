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
from app.core.tenant import get_default_user
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
    """Compose a compact context string for the system prompt."""
    parts: list[str] = [
        f"# User Profile",
        f"- Name: {user.display_name}",
        f"- Risk tolerance: {user.risk_tolerance}",
        f"- Priority factors: {user.priority_factors}",
        f"- Progress: {user.progress}",
    ]

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

    # Memories: surface the top ~15 by importance so the LLM has prior context
    # without bloating the prompt. The full list is still queryable via the
    # `list_memories` tool.
    mems = list(
        db.scalars(
            select(UserMemory)
            .where(UserMemory.user_id == user.id)
            .order_by(UserMemory.importance.desc(), UserMemory.created_at.desc())
            .limit(15)
        )
    )
    if mems:
        parts.append("\n# Memories (previously remembered facts about the user)")
        for m in mems:
            parts.append(
                f"- [{m.category}|imp={m.importance:.2f}|id={m.id}] {m.content}"
            )

    return "\n".join(parts)


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest, db: Session = Depends(get_db)
) -> StreamingResponse:
    """SSE stream of ChatResponseChunk JSON objects.

    Streams both model token deltas and tool-call events from the LangGraph
    advisor agent. Each SSE event is ``data: {json}\n\n``; the stream ends
    with ``data: [DONE]\n\n``.
    """
    # Verify the chat role is configured before streaming; raises
    # LLMNotConfiguredError (-> 503) if no chat model is assigned.
    get_chat_model()

    user = get_default_user(db) if not payload.user_id else db.get(UserProfile, payload.user_id)
    if user is None:
        raise HTTPException(404, "User not found")

    goal = db.get(Goal, payload.goal_id) if payload.goal_id else None
    scenario = db.get(Scenario, payload.scenario_id) if payload.scenario_id else None
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
