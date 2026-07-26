"""Typed state schema for the AI advisor LangGraph.

Holds the conversation messages, the immutable user/goal/scenario context,
and a log of tool calls made during the run (so the API layer can stream
them to the frontend alongside model deltas).
"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import BaseMessage


class AdvisorState(TypedDict, total=False):
    """Input/output state for the advisor graph.

    - ``messages``: the running conversation (system + user + assistant + tool).
    - ``goal_id`` / ``scenario_id``: routing keys for tool calls.
    - ``tool_calls``: append-only audit trail; each entry is
      ``{"name": str, "args": dict, "result": dict}``.
    - ``context_block``: pre-rendered context string folded into the system
      message; produced by the API layer from the DB before invoking the graph.
    """

    messages: list[BaseMessage]
    goal_id: str | None
    scenario_id: str | None
    context_block: str
    tool_calls: list[dict[str, Any]]
