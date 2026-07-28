"""intelligent assistant service backed by LangGraph.

Public surface:
- ``build_advisor_graph``: compile a per-request ReAct agent
- ``build_advisor_tools``: build tools bound to a DB session + context
- ``messages_to_langchain``: convert OpenAI-style message dicts
- ``AdvisorState``: typed state schema
"""

from .graph import SYSTEM_PROMPT, build_advisor_graph, messages_to_langchain
from .state import AdvisorState
from .tools import build_advisor_tools

__all__ = [
    "AdvisorState",
    "SYSTEM_PROMPT",
    "build_advisor_graph",
    "build_advisor_tools",
    "messages_to_langchain",
]
