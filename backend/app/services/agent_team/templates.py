"""Team template definitions (§D.4 of the spec).

A team template is a predefined orchestration pattern: it declares the
roles to use, the decomposition prompt for the main agent, the
aggregation prompt, and the max iteration count. The main agent can
only operate within a template's framework — it cannot invent arbitrary
roles (decision 7: "non-fully-automatic decomposition").

Five templates are defined:
- ``cross_domain_research``: N×ResearchSpecialist + SynthesisSpecialist
- ``independent_validation``: N×ValidationSpecialist + SynthesisSpecialist
- ``multi_pathway_compare``: N×ScenarioExplorer + SynthesisSpecialist
- ``risk_scan``: N×DomainAnalyst
- ``iterative_research``: ResearchSpecialist + SynthesisSpecialist (≤2 rounds)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TeamTemplate:
    """Static spec for one team template."""

    name: str
    description: str
    # Roles the main agent can assign (the main agent picks a subset
    # based on the objective — it cannot invent roles outside this set).
    allowed_roles: tuple[str, ...]
    # Prompt suffix appended to the decomposition LLM call. Tells the
    # main agent how to split the objective.
    decompose_hint: str
    # Prompt suffix appended to the aggregation LLM call.
    aggregate_hint: str
    # Max fan-out rounds. 1 = single round; 2 = iterative (review node
    # may dispatch one more round).
    max_iterations: int = 1
    # Whether a SynthesisSpecialist is always added as the final sub-agent.
    always_synthesize: bool = True


# ---------- Template definitions ----------

CROSS_DOMAIN_RESEARCH = TeamTemplate(
    name="cross_domain_research",
    description=(
        "Cross-domain deep research. Multiple ResearchSpecialists each "
        "bound to a different engine + domain research in parallel, then "
        "a SynthesisSpecialist merges the results."
    ),
    allowed_roles=("ResearchSpecialist", "SynthesisSpecialist"),
    decompose_hint=(
        "Split the objective into sub-questions, one per domain "
        "(policy / academic / news / vertical). Assign each sub-question "
        "to a ResearchSpecialist with a distinct engine and domain. "
        "Aim for 3-5 specialists covering different domains."
    ),
    aggregate_hint=(
        "Merge the specialists' findings into a coherent research "
        "report. Highlight cross-domain consensus and divergences. "
        "Flag any domain that was not covered."
    ),
    max_iterations=1,
    always_synthesize=True,
)

INDEPENDENT_VALIDATION = TeamTemplate(
    name="independent_validation",
    description=(
        "Independent fact validation. Multiple ValidationSpecialists each "
        "verify the same claim from a different angle/engine, then a "
        "SynthesisSpecialist produces a verdict."
    ),
    allowed_roles=("ValidationSpecialist", "SynthesisSpecialist"),
    decompose_hint=(
        "Identify the key claims to validate. Assign each claim to a "
        "ValidationSpecialist with a distinct verification angle "
        "(official source / academic / Chinese-language / etc.). "
        "Aim for 2-4 specialists per claim."
    ),
    aggregate_hint=(
        "Aggregate the validation verdicts. For each claim, state "
        "confirmed / refuted / uncertain based on the specialists' "
        "consensus. Highlight any claim where specialists disagreed."
    ),
    max_iterations=1,
    always_synthesize=True,
)

MULTI_PATHWAY_COMPARE = TeamTemplate(
    name="multi_pathway_compare",
    description=(
        "Multi-pathway comparison. Each ScenarioExplorer evolves one "
        "Pathway forward, then a SynthesisSpecialist produces a "
        "comparison table."
    ),
    allowed_roles=("ScenarioExplorer", "SynthesisSpecialist"),
    decompose_hint=(
        "List the user's Pathways. Assign each Pathway to a "
        "ScenarioExplorer to project its evolution. Aim for 2-5 "
        "explorers depending on the number of Pathways."
    ),
    aggregate_hint=(
        "Produce a side-by-side comparison table of the Pathways: "
        "projected outcomes, key risks, milestones, and recommended "
        "next steps. Highlight the most promising Pathway."
    ),
    max_iterations=1,
    always_synthesize=True,
)

RISK_SCAN = TeamTemplate(
    name="risk_scan",
    description=(
        "Multi-dimensional risk scan. DomainAnalysts each scan one "
        "dimension (policy / economy / security / society) for risks."
    ),
    allowed_roles=("DomainAnalyst",),
    decompose_hint=(
        "Split the objective into risk dimensions: policy, economic, "
        "security, social. Assign each to a DomainAnalyst. Aim for "
        "3-4 analysts covering distinct dimensions."
    ),
    aggregate_hint=(
        "Merge the analysts' findings into a prioritized risk list. "
        "Rate each risk by likelihood and impact. Flag any dimension "
        "that was not covered."
    ),
    max_iterations=1,
    # risk_scan's DomainAnalyst already produces structured output; no
    # separate SynthesisSpecialist is needed (the main agent aggregates).
    always_synthesize=False,
)

ITERATIVE_RESEARCH = TeamTemplate(
    name="iterative_research",
    description=(
        "Iterative research with gap-filling. ResearchSpecialists research "
        "in round 1, the SynthesisSpecialist reviews for coverage gaps, "
        "and additional ResearchSpecialists fill the gaps in round 2 "
        "(max 2 rounds)."
    ),
    allowed_roles=("ResearchSpecialist", "SynthesisSpecialist"),
    decompose_hint=(
        "Split the objective into initial sub-questions. Assign each to "
        "a ResearchSpecialist. Leave domains that are uncertain for "
        "round 2 — the review node will identify gaps."
    ),
    aggregate_hint=(
        "After round 1, review the specialists' findings for coverage "
        "gaps. If a domain is missing or shallow, dispatch a new "
        "ResearchSpecialist for it in round 2. After round 2 (or if "
        "no gaps), produce the final report."
    ),
    max_iterations=2,
    always_synthesize=True,
)


# Registry: template name → spec.
TEMPLATES: dict[str, TeamTemplate] = {
    spec.name: spec
    for spec in (
        CROSS_DOMAIN_RESEARCH,
        INDEPENDENT_VALIDATION,
        MULTI_PATHWAY_COMPARE,
        RISK_SCAN,
        ITERATIVE_RESEARCH,
    )
}


def get_template(name: str) -> TeamTemplate | None:
    """Look up a team template by name. Returns None if unknown."""
    return TEMPLATES.get(name)
