from app.services.advisor.graph import SYSTEM_PROMPT
from app.services.advisor.loop_guard import (
    ADVISOR_RECURSION_LIMIT,
    DEFAULT_MAX_TOOL_CALLS,
    ToolLoopGuard,
)


def test_default_budget_allows_128_tool_calls() -> None:
    guard = ToolLoopGuard(max_identical_calls=65)

    for index in range(DEFAULT_MAX_TOOL_CALLS):
        assert guard.record("search", {"page": index}) is None
    assert guard.record("search", {"page": 65}) == "tool_call_budget_exceeded"
    assert ADVISOR_RECURSION_LIMIT > DEFAULT_MAX_TOOL_CALLS * 2


def test_identical_tool_call_stops_before_third_execution() -> None:
    guard = ToolLoopGuard(max_identical_calls=3)

    assert guard.record("list_goals", {"status": "active"}) is None
    assert guard.record("list_goals", {"status": "active"}) is None
    assert (
        guard.record("list_goals", {"status": "active"})
        == "repeated_tool_call"
    )


def test_argument_order_does_not_bypass_repeat_detection() -> None:
    guard = ToolLoopGuard(max_identical_calls=2)

    assert guard.record("update_goal", {"goal_id": "g1", "status": "active"}) is None
    assert (
        guard.record("update_goal", {"status": "active", "goal_id": "g1"})
        == "repeated_tool_call"
    )


def test_total_tool_budget_stops_varied_calls() -> None:
    guard = ToolLoopGuard(max_total_calls=2, max_identical_calls=5)

    assert guard.record("list_goals", {}) is None
    assert guard.record("list_pathways", {"goal_id": "g1"}) is None
    assert guard.record("list_memories", {}) == "tool_call_budget_exceeded"


def test_prompt_forbids_blind_tool_retries() -> None:
    assert "Never retry an identical tool call" in SYSTEM_PROMPT
    assert "reused=true" in SYSTEM_PROMPT
