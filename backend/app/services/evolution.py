"""Pathway self-evolution service.

Per project plan §5 "自演化": given a pathway + its requirements/
risk_factors + long-term accumulated user data (profile, memories, events),
invoke the chat-role LLM with a structured-output schema to project a
timeline of likely future events (milestones, risks, opportunities,
decisions) for the next 24 months.

The LLM returns a Pydantic-validated ``EvolutionProjection`` which the
frontend renders as timeline nodes alongside the existing scenario tree.

Storage (v0.4.0): the projection's numerical outputs are cached directly
on ``Pathway`` (success_probability / risk_score / key_risk_factors /
computed_at). The full projection dict is persisted on ``ScenarioRun.result``
for audit. For backward compat, if a linked ``Scenario`` exists, the
same outputs are also mirrored onto the Scenario (so old GET endpoints
and the frontend scenario-comparison overlay still work).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import LLMNotConfiguredError
from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import SessionLocal
from app.llm.client import get_instructor_sync
from app.models.event import Event
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.models.memory import UserMemory
from app.models.scenario import Scenario, ScenarioRun, ScenarioStatus
from app.models.user import UserProfile
from app.services.risk_scope import risk_scope_clause
# 保留 resolve_scenario_pathway 用于向后兼容入口（evolve_scenario_async）
from app.services.scenario_pathway import resolve_scenario_pathway

log = get_logger(__name__)


# ---------------- Pydantic schemas for structured output ----------------


class ProjectedEvent(BaseModel):
    """A single future event projected by the LLM along the timeline."""

    month: int = Field(
        ...,
        ge=1,
        le=36,
        description="Months from now when this event is expected to occur (1-36).",
    )
    title: str = Field(
        ..., max_length=80, description="Short title for this event (e.g. 'Language test deadline')."
    )
    type: Literal["milestone", "risk", "opportunity", "decision"] = Field(
        ..., description="Event category driving the node color in the UI."
    )
    description: str = Field(
        ...,
        max_length=300,
        description="One-sentence explanation of what this event is and why it matters.",
    )
    probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Likelihood of this event occurring (0-1).",
    )
    impact: float = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="Impact on success probability if it occurs. Positive = helps, negative = hurts.",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Titles of other projected events that must happen first.",
    )


class EvolutionProjection(BaseModel):
    """Structured LLM output for scenario self-evolution."""

    summary: str = Field(
        ...,
        max_length=500,
        description="A 2-3 sentence overview of how this scenario is expected to unfold.",
    )
    events: list[ProjectedEvent] = Field(
        ...,
        min_length=3,
        max_length=20,
        description="Chronologically ordered list of projected events (3-20 events).",
    )
    final_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Estimated success probability at the end of the projection horizon.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="How confident the LLM is in this projection overall (0-1).",
    )


# ---------------- Service ----------------


class EvolutionService:
    """LLM-driven pathway timeline projection."""

    HORIZON_MONTHS = 24
    MAX_MEMORIES = 15
    MAX_EVENTS = 10
    MAX_REQUIREMENTS = 12

    def __init__(self, db: Session) -> None:
        self.db = db

    def evolve(self, pathway: Pathway, user: CurrentUser) -> dict[str, Any]:
        """Project the next 24 months of events for ``pathway``.

        Returns a dict with ``projection`` (the LLM output) and ``trajectory``
        (a month-by-month success probability list derived from the events).

        v0.4.0：直接读写 Pathway 上的 success_probability / risk_score /
        key_risk_factors / computed_at。如果存在关联的 Scenario，会同时把
        数值镜像写回 Scenario 以保持向后兼容（老的前端 GET 端点和
        scenario-comparison overlay 仍能工作）。
        """
        t0 = time.perf_counter()
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        # 查找关联的 Scenario（向后兼容：审计记录与缓存仍需要 scenario_id）
        scenario = self._resolve_linked_scenario(pathway)

        # ScenarioRun.scenario_id 是 NOT NULL 的外键，所以只有当存在关联
        # Scenario 时才写审计记录。
        run: ScenarioRun | None = None
        if scenario is not None:
            run = ScenarioRun(
                id=run_id,
                scenario_id=scenario.id,
                engine="evolution",
                status="running",
                started_at=started_at,
            )
            self.db.add(run)
            self.db.commit()

        try:
            context = self._build_context(pathway, user)
            prompt_messages = self._build_prompt(pathway, context)

            try:
                instructor = get_instructor_sync()
            except LLMNotConfiguredError:
                raise  # propagate as 503 to the client

            # Instructor enforces the Pydantic schema — if the LLM returns
            # malformed JSON or missing fields, it retries automatically
            # (default max_retries=3).
            try:
                projection: EvolutionProjection = instructor.chat.completions.create(
                    model=context["model_name"],
                    messages=prompt_messages,
                    response_model=EvolutionProjection,
                    temperature=0.5,
                    max_tokens=2400,
                    max_retries=2,
                )
            except Exception as llm_exc:
                from app.core.exceptions import ExternalServiceError

                raise ExternalServiceError(
                    f"LLM call failed during evolution: {llm_exc}",
                    details={"provider_error": str(llm_exc)[:500]},
                ) from llm_exc

            trajectory = self._compute_trajectory(
                base_p=context["base_p50"],
                events=projection.events,
            )

            # 反馈持久化（EvolutionFeedbackService 仍需要 Scenario）。
            # 没有关联 Scenario 时跳过 —— milestone/counterfactual 反馈留空。
            feedback: dict[str, Any] = {"milestones_created": 0, "branches_created": 0}
            if scenario is not None:
                from app.services.evolution_feedback import EvolutionFeedbackService

                feedback = EvolutionFeedbackService(self.db).persist_projection(
                    scenario, user.id, projection.events
                )

            result: dict[str, Any] = {
                "projection": projection.model_dump(),
                "trajectory": trajectory,
                "context_summary": context["summary"],
                "horizon_months": self.HORIZON_MONTHS,
                "feedback": feedback,
            }

            # ---- v0.4.0：写入 Pathway（单一来源） ----
            # success_probability: 合并 p50 = projection.final_probability，
            # 保留已有的 p10/p90（如果有）。
            sp = dict(pathway.success_probability or {})
            sp["p50"] = projection.final_probability
            pathway.success_probability = sp
            # risk_score: 用风险类事件的累计期望负面影响作为启发式（0-1）
            pathway.risk_score = self._derive_risk_score(projection.events)
            # key_risk_factors: 抽取风险类事件，便于前端直接渲染
            pathway.key_risk_factors = [
                {
                    "title": e.title,
                    "description": e.description,
                    "probability": e.probability,
                    "impact": e.impact,
                    "month": e.month,
                }
                for e in projection.events
                if e.type == "risk"
            ]
            pathway.computed_at = datetime.now(timezone.utc)
            self.db.add(pathway)

            # ---- 向后兼容：把数值镜像写回关联 Scenario ----
            # 这样老的 GET /scenarios/{id}/evolve 端点（读 scenario.meta）
            # 和 scenario-comparison overlay（读 scenario.success_probability）
            # 仍能正常工作。
            if scenario is not None:
                scenario.success_probability = sp
                scenario.risk_score = pathway.risk_score
                scenario.key_risk_factors = pathway.key_risk_factors
                scenario.computed_at = pathway.computed_at
                meta = dict(scenario.meta or {})
                meta["evolution"] = {
                    "projected_events": [e.model_dump() for e in projection.events],
                    "trajectory": trajectory,
                    "summary": projection.summary,
                    "final_probability": projection.final_probability,
                    "confidence": projection.confidence,
                    "evolved_at": started_at.isoformat(),
                    "model": context["model_name"],
                }
                scenario.meta = meta
                self.db.add(scenario)

            if run is not None:
                run.status = "completed"
                run.result = result
                run.iterations = 1
                run.completed_at = datetime.now(timezone.utc)
                run.duration_ms = int((time.perf_counter() - t0) * 1000)
                self.db.add(run)

            self.db.commit()

            log.info(
                "evolution.completed",
                pathway_id=pathway.id,
                scenario_id=scenario.id if scenario else None,
                events=len(projection.events),
                ms=run.duration_ms if run else int((time.perf_counter() - t0) * 1000),
            )
            return result

        except Exception as exc:  # noqa: BLE001
            log.error(
                "evolution.failed",
                pathway_id=pathway.id,
                scenario_id=scenario.id if scenario else None,
                error=str(exc),
            )
            if run is not None:
                run.status = "failed"
                run.error = str(exc)
                run.completed_at = datetime.now(timezone.utc)
                run.duration_ms = int((time.perf_counter() - t0) * 1000)
                self.db.add(run)
                self.db.commit()
            raise

    # ---------------- Scenario 反查（向后兼容） ----------------

    def _resolve_linked_scenario(self, pathway: Pathway) -> Scenario | None:
        """查找 Pathway 关联的 Scenario（向后兼容用）。

        优先使用 ``pathway.scenario_id``；找不到则按 ``scenarios.pathway_id``
        反查最新的活跃/草稿 Scenario。两者都找不到时返回 None（此时跳过
        ScenarioRun 审计记录与 scenario.meta 缓存写入）。
        """
        if pathway.scenario_id:
            sc = self.db.get(Scenario, pathway.scenario_id)
            if sc is not None and sc.goal_id == pathway.goal_id:
                return sc
        sc = self.db.scalar(
            select(Scenario)
            .where(
                Scenario.pathway_id == pathway.id,
                Scenario.goal_id == pathway.goal_id,
                Scenario.status.in_(
                    [ScenarioStatus.ACTIVE.value, ScenarioStatus.DRAFT.value]
                ),
            )
            .order_by(Scenario.created_at.desc())
        )
        return sc

    # ---------------- Context loading ----------------

    def _build_context(self, pathway: Pathway, user: CurrentUser) -> dict[str, Any]:
        """Load all long-term accumulated data that informs the projection.

        v0.4.0：直接使用传入的 Pathway，不再通过 resolve_scenario_pathway
        解析。基线 P50 优先读 Pathway.success_probability；如果 Pathway 上
        没有数据，回退到关联 Scenario 的 success_probability（向后兼容）。
        """
        goal = self.db.get(Goal, pathway.goal_id)
        if goal is None:
            raise RuntimeError("pathway's goal not found")

        # §11.3: Use M2M table, fall back to legacy pathway_id
        from app.models.goal import pathway_requirements, pathway_risk_factors

        requirements: list[Requirement] = []
        requirements = list(
            self.db.scalars(
                select(Requirement)
                .join(pathway_requirements, pathway_requirements.c.requirement_id == Requirement.id)
                .where(pathway_requirements.c.pathway_id == pathway.id)
                .order_by(Requirement.weight.desc())
                .limit(self.MAX_REQUIREMENTS)
            )
        )
        if not requirements:
            requirements = list(
                self.db.scalars(
                    select(Requirement)
                    .where(Requirement.pathway_id == pathway.id)
                    .order_by(Requirement.weight.desc())
                    .limit(self.MAX_REQUIREMENTS)
                )
            )

        # Risk factors are explicit per-pathway associations. Inferring by
        # region makes sibling pathways consume identical, unrelated risks.
        risk_factors: list[RiskFactor] = []
        risk_factors = list(
            self.db.scalars(
                select(RiskFactor)
                .join(pathway_risk_factors, pathway_risk_factors.c.risk_factor_id == RiskFactor.id)
                .where(
                    pathway_risk_factors.c.pathway_id == pathway.id,
                    RiskFactor.deleted_at.is_(None),
                    risk_scope_clause(goal.user_id),
                )
                .order_by(RiskFactor.level.desc())
                .limit(10)
            )
        )

        # User profile + memories — the "long-term accumulated data" that
        # makes the projection personal rather than generic.
        profile = self.db.get(UserProfile, user.id)
        memories = list(
            self.db.scalars(
                select(UserMemory)
                .where(UserMemory.user_id == user.id)
                .order_by(UserMemory.importance.desc())
                .limit(self.MAX_MEMORIES)
            )
        )

        # Recent events from the structuring pipeline (news, uploads, etc.)
        recent_events = list(
            self.db.scalars(
                select(Event)
                .where(Event.user_id == user.id)
                .order_by(Event.created_at.desc())
                .limit(self.MAX_EVENTS)
            )
        )

        # Resolve the model name for the instructor call (needed because
        # instructor.chat.completions.create requires the model name
        # explicitly).
        from app.llm.client import get_chat_model
        try:
            model_name = get_chat_model().model.name
        except LLMNotConfiguredError:
            model_name = "gpt-4o-mini"  # fallback; instructor will raise anyway

        # 基线 P50：优先读 Pathway.success_probability
        pathway_sp = pathway.success_probability or {}
        if isinstance(pathway_sp, dict) and pathway_sp:
            base_p50 = float(pathway_sp.get("p50", 0.5))
        else:
            # 向后兼容：Pathway 上没有数据时回退到关联 Scenario
            scenario = self._resolve_linked_scenario(pathway)
            if scenario is not None:
                base_p50 = float((scenario.success_probability or {}).get("p50", 0.5))
            else:
                base_p50 = 0.5

        return {
            "goal": goal,
            "pathway": pathway,
            "requirements": requirements,
            "risk_factors": risk_factors,
            "profile": profile,
            "memories": memories,
            "recent_events": recent_events,
            "model_name": model_name,
            "base_p50": base_p50,
            "summary": self._summarize_context(
                goal, pathway, requirements, risk_factors, profile, memories, recent_events
            ),
        }

    @staticmethod
    def _summarize_context(
        goal: Goal,
        pathway: Pathway | None,
        requirements: list[Requirement],
        risk_factors: list[RiskFactor],
        profile: UserProfile | None,
        memories: list[UserMemory],
        recent_events: list[Event],
    ) -> str:
        parts: list[str] = []
        parts.append(f"Goal: {goal.title}")
        if goal.description:
            parts.append(f"Goal description: {goal.description[:200]}")
        if pathway:
            parts.append(f"Pathway: {pathway.name} (region={pathway.region or 'global'})")
        if requirements:
            req_lines = [
                f"  - {r.name} [{r.gap_status}] (weight={r.weight:.1f})"
                for r in requirements[:8]
            ]
            parts.append("Top requirements:\n" + "\n".join(req_lines))
        if risk_factors:
            rf_lines = [
                f"  - {rf.name} [{rf.level}] (type={rf.type})"
                for rf in risk_factors[:6]
            ]
            parts.append("Key risk factors:\n" + "\n".join(rf_lines))
        if profile:
            parts.append(f"User: {profile.display_name}, risk_tolerance={profile.risk_tolerance}")
            if profile.demographics:
                parts.append(f"Demographics: {dict(profile.demographics)}")
        if memories:
            mem_lines = [f"  - [{m.category}] {m.content}" for m in memories[:10]]
            parts.append("Long-term memories:\n" + "\n".join(mem_lines))
        if recent_events:
            ev_lines = [
                f"  - {e.subject} {e.action}" + (f" {e.object}" if e.object else "")
                for e in recent_events[:5]
            ]
            parts.append("Recent events:\n" + "\n".join(ev_lines))
        return "\n".join(parts)

    # ---------------- Prompt construction ----------------

    def _build_prompt(self, pathway: Pathway, context: dict[str, Any]) -> list[dict[str, str]]:
        system = (
            "You are a strategic foresight assistant inside LifeTree, a life-decision "
            "support platform. Your task is to project how the user's scenario will "
            "unfold over the next 24 months based on their long-term accumulated data.\n\n"
            "You MUST respond with a single valid JSON object conforming EXACTLY to this "
            "schema (no markdown fences, no commentary, no prose outside the JSON):\n"
            "{\n"
            '  "summary": "<2-3 sentence string>",\n'
            '  "projected_events": [\n'
            "    {\n"
            '      "month": <int 1-36>,\n'
            '      "title": "<string, max 80 chars>",\n'
            '      "type": "<one of: milestone | risk | opportunity | decision>",\n'
            '      "description": "<string, max 300 chars>",\n'
            '      "probability": <float 0-1>,\n'
            '      "impact": <float -1 to +1>,\n'
            '      "dependencies": ["<title of another event in this list>", ...]\n'
            "    }\n"
            "  ],\n"
            '  "final_probability": <float 0-1>,\n'
            '  "confidence": <float 0-1>\n'
            "}\n\n"
            "Field requirements:\n"
            "- summary: 2-3 sentences describing how this scenario is expected to evolve.\n"
            "- projected_events: chronologically ordered list of 3-20 future events.\n"
            "  - month: integer 1-36 (months from now). Spread across the full horizon.\n"
            "  - title: short label, max 80 chars.\n"
            "  - type: one of 'milestone' (positive checkpoint), 'risk' (potential "
            "threat), 'opportunity' (external chance), 'decision' (user must choose).\n"
            "  - description: one sentence, max 300 chars.\n"
            "  - probability: float 0-1 likelihood of occurring.\n"
            "  - impact: float -1 to +1 effect on success probability if it occurs.\n"
            "  - dependencies: array of titles of other events in this list that must "
            "happen first. Use an empty array if there are none.\n"
            "- final_probability: overall success probability at month 24, float 0-1.\n"
            "- confidence: how confident you are in this projection, float 0-1.\n\n"
            "Output rules:\n"
            "- Return ONLY the JSON object. No markdown, no code fences, no prefix/suffix text.\n"
            "- All keys must be present; use empty arrays for dependencies when applicable.\n"
            "- Do not invent fields beyond the schema above.\n\n"
            "Guidelines:\n"
            "- Ground events in the user's actual requirements, risk factors, and memories.\n"
            "- Be specific (e.g. 'Submit IELTS results' not 'Take a test').\n"
            "- Spread events across the full horizon, not clustered in month 1.\n"
            "- Use 'decision' events when the user faces a meaningful choice.\n"
            "- The final_probability should reflect the cumulative effect of the events."
        )

        user_msg = (
            f"Pathway: {pathway.name}\n"
            f"Description: {pathway.description or 'N/A'}\n"
            f"Current success probability (P50): {context['base_p50']:.1%}\n\n"
            f"Context:\n{context['summary']}\n\n"
            f"Project the next {self.HORIZON_MONTHS} months for this pathway. "
            f"Respond with only the JSON object described in the system prompt."
        )

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

    # ---------------- Trajectory computation ----------------

    def _compute_trajectory(
        self, base_p: float, events: list[ProjectedEvent]
    ) -> list[dict[str, Any]]:
        """Derive a month-by-month success-probability trajectory.

        For each month 0..HORIZON, start from ``base_p`` and apply the
        expected impact of events that have occurred by that month
        (impact * probability). Clamp to [0, 1].
        """
        trajectory: list[dict[str, Any]] = []
        for month in range(0, self.HORIZON_MONTHS + 1):
            p = base_p
            for ev in events:
                if ev.month <= month:
                    # Expected impact = P(event) * impact
                    p += ev.probability * ev.impact * 0.3  # dampen so a single event doesn't dominate
            p = max(0.0, min(1.0, p))
            trajectory.append({"month": month, "p": round(p, 4)})
        return trajectory

    @staticmethod
    def _derive_risk_score(events: list[ProjectedEvent]) -> float:
        """根据 LLM 投射的事件列表推导 risk_score（0-1）。

        启发式：risk_score = Σ P(risk_event) * |impact|，clamp 到 [0, 1]。
        只统计 type=='risk' 的事件，避免把正向机会/里程碑算进风险分。
        """
        total = 0.0
        for e in events:
            if e.type == "risk":
                total += float(e.probability) * abs(float(e.impact))
        return max(0.0, min(1.0, total))


def evolve_scenario_async(scenario_id: str, user_id: str) -> dict[str, Any]:
    """向后兼容入口：通过 scenario_id 解析关联 Pathway 再调用 evolve(pathway)。

    供 Celery / 非请求上下文调用。优先使用 scenario.pathway_id；否则用
    resolve_scenario_pathway 反查。两者都找不到时报错。
    """
    with SessionLocal() as db:
        scenario = db.get(Scenario, scenario_id)
        if scenario is None:
            raise RuntimeError(f"Scenario {scenario_id} not found")
        # 解析关联 Pathway —— 优先用显式的 pathway_id，再回退到反查
        pathway: Pathway | None = None
        if scenario.pathway_id:
            pathway = db.get(Pathway, scenario.pathway_id)
        if pathway is None:
            pathway = resolve_scenario_pathway(db, scenario)
        if pathway is None:
            raise RuntimeError(
                f"Scenario {scenario_id} has no linked Pathway; cannot evolve"
            )
        # Build a minimal CurrentUser-like object — EvolutionService only
        # needs .id for memory/event scoping.
        user = type("U", (), {"id": user_id, "role": "user"})()
        return EvolutionService(db).evolve(pathway, user)


def evolve_pathway_async(pathway_id: str, user_id: str) -> dict[str, Any]:
    """直接通过 pathway_id 调用 evolve 的异步入口（供 Celery / 新调度用）。

    Opens its own DB session and resolves the user from ``user_id``.
    """
    with SessionLocal() as db:
        pathway = db.get(Pathway, pathway_id)
        if pathway is None:
            raise RuntimeError(f"Pathway {pathway_id} not found")
        user = type("U", (), {"id": user_id, "role": "user"})()
        return EvolutionService(db).evolve(pathway, user)
