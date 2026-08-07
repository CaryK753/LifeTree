"""Sub-agent role definitions and toolset pruning (§D.3 of the spec).

Each role declares:
- ``name``: the role identifier used in team templates.
- ``description``: human-readable summary shown to the main agent during
  decomposition.
- ``tools``: the tool names this role is allowed to use. The specialist
  sub-graph only injects these tools into the LLM's tool list, keeping
  the sub-agent focused and reducing tool-selection confusion.
- ``max_tool_calls``: per-sub-agent budget cap (enforced by the
  specialist sub-graph's ``ToolLoopGuard``).

The tool names here MUST match the names registered in
``services/advisor/tools.py`` (via ``@tool("name", ...)``). Unknown names
are silently filtered out at runtime so a missing tool doesn't crash the
whole team.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoleSpec:
    """Static spec for one sub-agent role."""

    name: str
    description: str
    tools: tuple[str, ...]
    max_tool_calls: int = 20
    max_llm_calls: int = 15


# ---------- Role definitions ----------
#
# Tool names must match the @tool("name", ...) registrations in
# services/advisor/tools.py. See build_advisor_tools() for the full list.

RESEARCH_SPECIALIST = RoleSpec(
    name="ResearchSpecialist",
    description=(
        "Bound to a specific search engine + domain. Retrieves, fetches, "
        "and structures information into atoms. Independent context "
        "ensures unbiased parallel research."
    ),
    tools=(
        "web_search",
        "web_fetch",
        "ingest_url",
        "global_search",
    ),
    max_tool_calls=20,
    max_llm_calls=15,
)

VALIDATION_SPECIALIST = RoleSpec(
    name="ValidationSpecialist",
    description=(
        "Independently verifies a given fact from a specific angle or "
        "engine. Produces a verdict (confirmed / refuted / uncertain) "
        "with supporting evidence."
    ),
    tools=(
        "web_search",
        "web_fetch",
        "list_assertions",
        "get_source_credibility",
    ),
    max_tool_calls=15,
    max_llm_calls=12,
)

SYNTHESIS_SPECIALIST = RoleSpec(
    name="SynthesisSpecialist",
    description=(
        "Aggregates multiple sub-agent results into a structured output. "
        "Does not search — only reads existing atoms and conflicts."
    ),
    tools=(
        "global_search",
        "list_assertions",
        "list_conflicts",
        "detect_trends",
    ),
    max_tool_calls=10,
    max_llm_calls=8,
)

DOMAIN_ANALYST = RoleSpec(
    name="DomainAnalyst",
    description=(
        "Deep analysis of a specific domain (policy / economy / security / "
        "society). Can search the web and ingest URLs, and has read access "
        "to the user's pathways and risk factors for context."
    ),
    tools=(
        "web_search",
        "web_fetch",
        "ingest_url",
        "list_pathways",
        "list_risk_factors",
        "discover_risks",
    ),
    max_tool_calls=20,
    max_llm_calls=15,
)

SCENARIO_EXPLORER = RoleSpec(
    name="ScenarioExplorer",
    description=(
        "Evolves a specific Pathway/Scenario forward in time. Uses the "
        "reasoning engine to project outcomes and compare alternatives."
    ),
    tools=(
        "run_scenario_reasoning",
        "compare_scenarios",
        "list_decision_tree",
    ),
    max_tool_calls=10,
    max_llm_calls=8,
)


# Registry: role name → spec. The orchestrator looks up roles by name
# when dispatching subtasks.
ROLES: dict[str, RoleSpec] = {
    spec.name: spec
    for spec in (
        RESEARCH_SPECIALIST,
        VALIDATION_SPECIALIST,
        SYNTHESIS_SPECIALIST,
        DOMAIN_ANALYST,
        SCENARIO_EXPLORER,
    )
}


def get_role(name: str) -> RoleSpec | None:
    """Look up a role spec by name. Returns None if unknown."""
    return ROLES.get(name)


def resolve_tools(role_name: str, all_tools: dict[str, object]) -> list[object]:
    """Return the pruned tool list for a role.

    ``all_tools`` is the full name→tool dict from ``build_advisor_tools``.
    Only tools whose names appear in the role's ``tools`` tuple are
    returned, and only if they actually exist in ``all_tools`` (unknown
    names are silently dropped so a missing tool doesn't crash the team).
    """
    spec = get_role(role_name)
    if spec is None:
        return []
    return [all_tools[name] for name in spec.tools if name in all_tools]
