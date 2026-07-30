from types import SimpleNamespace

from app.schemas.entities import GoalCreate, PathwayCreate, PathwayUpdate
from app.services.advisor.calendar_tools import build_action_calendar_tools
from app.services.goal_identity import find_equivalent_goal, normalize_goal_title
from app.services.reasoning.action_persistence import persist_recommended_actions


class _ScalarSession:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self, _statement):
        return iter(self.rows)


class _ActionSession(_ScalarSession):
    def __init__(self):
        super().__init__([])
        self.added = []
        self.flushed = False

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flushed = True


def test_equivalent_goal_title_reuses_existing_goal() -> None:
    existing = SimpleNamespace(
        id="goal-1",
        title="  Learn Python by 2027 ",
        status="active",
    )

    assert normalize_goal_title("LEARN_python-by 2027!") == "learnpythonby2027"
    assert (
        find_equivalent_goal(_ScalarSession([existing]), "user-1", "Learn Python by 2027")
        is existing
    )


def test_new_goal_defaults_to_active() -> None:
    assert GoalCreate(title="Learn Python").status == "active"


def test_pathway_schemas_accept_decision_tree_statuses() -> None:
    assert PathwayCreate(name="AI branch", status="predicted").status == "predicted"
    assert PathwayUpdate(status="in_progress").status == "in_progress"


def test_calendar_tools_are_registered() -> None:
    names = {
        tool.name
        for tool in build_action_calendar_tools(user_id="user-1", goal_id_context="goal-1")
    }
    assert names == {"list_action_calendar", "update_action_calendar"}


def test_structured_recommendation_is_persisted_without_string_coercion_error() -> None:
    db = _ActionSession()
    requirement = SimpleNamespace(id="req-1", name="Language score", gap_delta=0.4)
    created = persist_recommended_actions(
        db,
        goal=SimpleNamespace(id="goal-1", user_id="user-1"),
        pathway=SimpleNamespace(id="path-1"),
        scenario=SimpleNamespace(id="scenario-1"),
        run_id="run-1",
        recommendations=[
            {
                "requirement_id": "req-1",
                "name": "Language score",
                "action": "Book the language test",
            }
        ],
        requirements=[requirement],
    )

    assert len(created) == 1
    assert created[0].title == "Book the language test"
    assert created[0].requirement_id == "req-1"
    assert db.flushed
