from types import SimpleNamespace

from app.api.chat import _build_context_block
from app.llm.registry import Model, Provider, ResolvedModel
from app.models.goal import Goal, Pathway
from app.models.user_runtime import UserServiceConfig
from app.services.advisor.graph import SYSTEM_PROMPT, build_advisor_graph
from app.services.advisor.tools import build_advisor_tools
from app.services.scenarios import ScenarioService


class _ToolFactorySession:
    def get(self, model, _object_id):
        if model is UserServiceConfig:
            return None
        return None


class _ContextSession:
    def __init__(self, scalar_results):
        self.scalar_results = iter(scalar_results)

    def scalars(self, _statement):
        return iter(next(self.scalar_results))


def test_all_builtin_tools_have_unique_valid_schemas() -> None:
    tools = build_advisor_tools(
        _ToolFactorySession(),
        user_id="user-1",
        goal_id="goal-1",
        scenario_id="scenario-1",
        include_web_search=True,
        include_web_fetch=True,
    )
    names = [item.name for item in tools]

    assert len(names) == len(set(names))
    assert {
        "list_goals",
        "list_pathways",
        "create_scenario_branch",
        "run_scenario_reasoning",
        "list_action_calendar",
        "update_action_calendar",
        "evolve_tree",
        "web_search",
        "web_fetch",
    }.issubset(names)
    for item in tools:
        assert item.args_schema is not None
        item.args_schema.model_json_schema()

    resolved = ResolvedModel(
        model=Model(
            id="model-1",
            provider_id="provider-1",
            name="test-model",
            display_name="Test model",
            capabilities=["chat"],
        ),
        provider=Provider(
            id="provider-1",
            name="Test provider",
            base_url="http://localhost:1/v1",
            api_key="test-key",
        ),
    )
    assert build_advisor_graph(
        tools=tools,
        context_block="test context",
        resolved_model=resolved,
    )


def test_advisor_prompt_matches_current_scenario_contract() -> None:
    assert "Scenario (what-if sandbox, linked by pathway_id)" in SYSTEM_PROMPT
    assert "scenario_id ──> Scenario" not in SYSTEM_PROMPT
    assert "Call one tool at a time" in SYSTEM_PROMPT
    assert "`pathway_id` is required when the goal has" in SYSTEM_PROMPT


def test_context_exposes_ids_required_by_tools() -> None:
    goal = SimpleNamespace(
        id="goal-1",
        user_id="user-1",
        title="Move abroad",
        scenario="generic",
        status="active",
        target_date=None,
        success_probability={},
    )
    pathway = SimpleNamespace(
        id="pathway-1",
        name="Skilled route",
        status="candidate",
    )
    requirement = SimpleNamespace(
        id="requirement-1",
        name="Language score",
        type="language",
        threshold={"score": 7},
        current_value={"score": 6},
        gap_status="partial",
    )
    risk = SimpleNamespace(
        id="risk-1",
        name="Policy change",
        type="policy",
        level="medium",
        urgency="normal",
    )
    scenario = SimpleNamespace(
        id="scenario-1",
        pathway_id="pathway-1",
        name="Higher score",
        assumptions={},
        success_probability={},
    )
    user = SimpleNamespace(
        id="user-1",
        primary_goal_id="goal-1",
        display_name="Test",
        risk_tolerance="medium",
        priority_factors=[],
        progress={},
        lifecycle_stage="planning",
        cruising_mode=False,
        demographics={},
        implicit_tags=[],
    )
    db = _ContextSession([[pathway], [requirement], [risk], []])

    context = _build_context_block(db, user, goal, scenario)

    assert "Goal: Move abroad [id=goal-1]" in context
    assert "Pathway: Skilled route (candidate) [id=pathway-1]" in context
    assert "Requirement: Language score (language) [id=requirement-1]" in context
    assert "Policy change [policy|id=risk-1]" in context
    assert "Active Scenario: Higher score [id=scenario-1]" in context


def test_scenario_tool_auto_binds_the_only_pathway(monkeypatch) -> None:
    goal = SimpleNamespace(id="goal-1", user_id="user-1")
    pathway = SimpleNamespace(id="pathway-1", goal_id="goal-1", deleted_at=None)

    class _WriteSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, model, object_id):
            if model is Goal and object_id == goal.id:
                return goal
            if model is Pathway and object_id == pathway.id:
                return pathway
            return None

        def scalars(self, _statement):
            return iter([pathway])

    captured = {}

    def create_branch(_service, **fields):
        captured.update(fields)
        return SimpleNamespace(id="scenario-new", **fields)

    monkeypatch.setattr(
        "app.services.advisor.tools.SessionLocal",
        lambda: _WriteSession(),
    )
    monkeypatch.setattr(ScenarioService, "create_branch", create_branch)
    monkeypatch.setattr(ScenarioService, "count_active_branches", lambda *_args: 1)

    built = build_advisor_tools(
        _ToolFactorySession(),
        user_id="user-1",
        goal_id="goal-1",
    )
    scenario_tool = next(item for item in built if item.name == "create_scenario_branch")
    result = scenario_tool.invoke({"name": "Higher score"})

    assert captured["pathway_id"] == "pathway-1"
    assert result["scenario_id"] == "scenario-new"
    assert result["pathway_id"] == "pathway-1"
