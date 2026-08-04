"""Deterministic guardrails for runaway advisor tool loops."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

LoopStopReason = Literal["repeated_tool_call", "tool_call_budget_exceeded"]

DEFAULT_MAX_TOOL_CALLS = 128
DEFAULT_MAX_IDENTICAL_TOOL_CALLS = 3
# A ReAct tool call normally consumes a model node and a tool node. Leave a
# small margin for the initial and terminal model passes.
ADVISOR_RECURSION_LIMIT = DEFAULT_MAX_TOOL_CALLS * 2 + 8

TOOL_LOOP_MESSAGE = (
    "检测到工具调用没有收敛，已停止本轮自动调用。"
    "请明确要操作的目标、路径或情景后重试。"
)
RECURSION_LIMIT_MESSAGE = (
    "本轮分析经过多次工具调用后仍未收敛，系统已安全停止。"
    "已有的成功操作不会重复执行；请缩小问题范围后重试。"
)


@dataclass(slots=True)
class ToolLoopGuard:
    """Stop identical retries and cap the total tools used by one agent run."""

    max_total_calls: int = DEFAULT_MAX_TOOL_CALLS
    max_identical_calls: int = DEFAULT_MAX_IDENTICAL_TOOL_CALLS
    total_calls: int = 0
    fingerprints: Counter[str] = field(default_factory=Counter)

    def record(self, name: str, args: dict[str, Any]) -> LoopStopReason | None:
        self.total_calls += 1
        if self.total_calls > self.max_total_calls:
            return "tool_call_budget_exceeded"

        fingerprint = self._fingerprint(name, args)
        self.fingerprints[fingerprint] += 1
        if self.fingerprints[fingerprint] >= self.max_identical_calls:
            return "repeated_tool_call"
        return None

    @staticmethod
    def _fingerprint(name: str, args: dict[str, Any]) -> str:
        normalized = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
        return f"{name}:{normalized}"


__all__ = [
    "ADVISOR_RECURSION_LIMIT",
    "DEFAULT_MAX_IDENTICAL_TOOL_CALLS",
    "DEFAULT_MAX_TOOL_CALLS",
    "RECURSION_LIMIT_MESSAGE",
    "TOOL_LOOP_MESSAGE",
    "ToolLoopGuard",
]
