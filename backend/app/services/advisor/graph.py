"""LangGraph advisor: a ReAct agent over the LifeTree ontology.

We use ``langgraph.prebuilt.create_react_agent`` which gives us:
- LLM-driven tool calling (OpenAI-compatible function calling)
- Automatic tool execution loop with message history
- Streaming of both model tokens and tool-call events

The graph is rebuilt per request because tools close over the per-request
DB session and user/goal/scenario context. This is the recommended pattern
for request-scoped LangGraph agents in a FastAPI app.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.core.logging import get_logger
from app.llm.client import get_chat_model

from .state import AdvisorState

log = get_logger(__name__)


SYSTEM_PROMPT = """You are LifeTree's AI decision advisor.

Your role:
- Help the user reason about long-horizon life decisions (immigration, study,
  career transition, retirement, etc.).
- Ground your answers in the user's profile, goals, pathways, requirements,
  risk factors, recent events, AND memories provided in the context block.
- When uncertainty exists, suggest creating a scenario branch to compare.
- Always end complex answers with a single concrete "无悔行动"
  (no-regret next action) recommendation.
- Be transparent about confidence and cite the factors you considered.
- Never fabricate facts. If you don't know, say so and suggest ingesting
  fresh information via the /ingest/text endpoint.

## Tools

You have access to four classes of tools:

1. **Query tools** — call these before guessing about specifics:
   - `list_pathways`, `list_requirements`, `list_risk_factors`,
     `list_recent_events`, `get_scenario_summary`, `run_scenario_reasoning`
   - `list_memories` — call at the start of a conversation to load what you
     already know about this user.

2. **Write tools** — when the user expresses a new intent or concern, USE
   these to capture it directly into the ontology. Don't just talk about it:
   - `create_goal` — when the user mentions a new long-horizon intent.
   - `create_pathway` — when the user mentions a candidate route (use
     `parent_pathway_id` for sub-branches of an existing pathway).
   - `create_requirement` — when the user mentions a specific eligibility
     criterion (e.g. IELTS 6.0, proof of funds).
   - `create_risk_factor` — when the user mentions a risk to watch.

3. **Memory tools** — the user's profile holds only typed fields; the
   unbounded "remember this" channel is the memory system. USE it liberally:
   - `remember(content, category, importance)` — call this whenever the user
     shares personal context that would help future conversations: family
     situation, health, finances, deadlines, constraints, strong preferences.
     Don't remember trivial small talk. If a similar memory exists, say so
     and either skip or update.
   - `forget(memory_id)` — when the user says 'forget that' or corrects a
     previous statement.
   Categories: family, career, health, finance, education, location,
   preference, goal, constraint, other.
   Importance: >=0.8 for hard constraints (legal status, deadline),
   0.3..0.7 for context (job, family), <0.3 for trivia.

4. **Web tools** — when local data is insufficient or the user asks about
   current events / fresh facts outside the knowledge graph:
   - `web_search(query, max_results)` — search the web via Tavily. Always
     prefer this for recent events, news, or facts outside the knowledge
     graph.
   - `web_fetch(urls)` — extract clean text from specific URLs. Use after
     `web_search` to read full articles, or when the user provides a URL.
   Web tools require a Tavily API key. If unavailable, inform the user to
   configure it in Settings.

After calling a write tool, briefly tell the user what you created ("I've
added a new goal: X — want me to flesh out pathways?") so they can confirm
or correct.

Style: concise, structured, and empathetic. Use short paragraphs and
bullet points. Avoid filler.
"""


def _build_llm() -> ChatOpenAI:
    """Construct the ChatOpenAI model from the configured chat role."""
    resolved = get_chat_model()
    return ChatOpenAI(
        model=resolved.model.name,
        api_key=resolved.provider.api_key or "missing",
        base_url=resolved.provider.base_url or None,
        temperature=0.4,
        streaming=True,
    )


def build_advisor_graph(
    *,
    tools: list[BaseTool],
    context_block: str,
) -> Any:
    """Build a per-request ReAct agent.

    Args:
        tools: Tools bound to the per-request DB session (from
            ``build_advisor_tools``).
        context_block: Pre-rendered user/goal/scenario context to fold into
            the system message.

    Returns:
        A compiled LangGraph ``CompiledStateGraph`` ready to ``ainvoke`` or
        ``astream``.
    """
    llm = _build_llm()
    system_content = f"{SYSTEM_PROMPT}\n\n# Context\n{context_block}"

    # create_react_agent accepts a system message via the ``prompt`` kwarg
    # (str | SystemMessage). We pass a SystemMessage so the content is treated
    # as immutable system context, not a turn in the conversation.
    graph = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SystemMessage(content=system_content),
    )
    return graph


def messages_to_langchain(
    history: list[dict[str, Any]],
) -> list[BaseMessage]:
    """Convert OpenAI-style message dicts to langchain message objects."""
    out: list[BaseMessage] = []
    for m in history:
        role = m.get("role")
        content = m.get("content", "")
        name = m.get("name")
        if role == "user":
            out.append(HumanMessage(content=content, name=name))
        elif role == "assistant":
            out.append(AIMessage(content=content, name=name))
        elif role == "system":
            out.append(SystemMessage(content=content))
        # tool messages are re-emitted by LangGraph itself during tool execution
    return out


__all__ = [
    "AdvisorState",
    "build_advisor_graph",
    "messages_to_langchain",
    "SYSTEM_PROMPT",
]
