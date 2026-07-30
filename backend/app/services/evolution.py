"""Scenario self-evolution service.

Per project plan §5 "自演化": given a scenario + its pathway/requirements/
risk_factors + long-term accumulated user data (profile, memories, events),
invoke the chat-role LLM with a structured-output schema to project a
timeline of likely future events (milestones, risks, opportunities,
decisions) for the next 24 months.

The LLM returns a Pydantic-validated ``EvolutionProjection`` which the
frontend renders as timeline nodes alongside the existing scenario tree.

Storage: the projection is cached on ``scenario.meta["evolution"]`` and a
``ScenarioRun(engine="evolution")`` audit record is persisted so the
run history page can show evolution runs alongside reasoning runs.
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
from app.models.scenario import Scenario, ScenarioRun
from app.models.user import UserProfile
from app.services.risk_scope import risk_scope_clause
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
    """LLM-driven scenario timeline projection."""

    HORIZON_MONTHS = 24
    MAX_MEMORIES = 15
    MAX_EVENTS = 10
    MAX_REQUIREMENTS = 12

    def __init__(self, db: Session) -> None:
        self.db = db

    def evolve(self, scenario: Scenario, user: CurrentUser) -> dict[str, Any]:
        """Project the next 24 months of events for ``scenario``.

        Returns a dict with ``projection`` (the LLM output) and ``trajectory``
        (a month-by-month success probability list derived from the events).
        """
        t0 = time.perf_counter()
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        # Persist an audit record up-front so partial failures are still
        # visible in the run history (mirrors ReasoningEngine.run_full).
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
            context = self._build_context(scenario, user)
            prompt_messages = self._build_prompt(scenario, context)

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

            # Cache on scenario.meta so subsequent GETs don't need to hit
            # the ScenarioRun table. Using meta (not assumptions) keeps the
            # LLM projection separate from user-defined assumptions that
            # actually feed the Bayesian reasoning.
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

            run.status = "completed"
            run.result = result
            run.iterations = 1
            run.completed_at = datetime.now(timezone.utc)
            run.duration_ms = int((time.perf_counter() - t0) * 1000)
            self.db.add(run)
            self.db.commit()

            log.info(
                "evolution.completed",
                scenario_id=scenario.id,
                events=len(projection.events),
                ms=run.duration_ms,
            )
            return result

        except Exception as exc:  # noqa: BLE001
            log.error("evolution.failed", scenario_id=scenario.id, error=str(exc))
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            run.duration_ms = int((time.perf_counter() - t0) * 1000)
            self.db.add(run)
            self.db.commit()
            raise

    # ---------------- Context loading ----------------

    def _build_context(self, scenario: Scenario, user: CurrentUser) -> dict[str, Any]:
        """Load all long-term accumulated data that informs the projection."""
        goal = self.db.get(Goal, scenario.goal_id)
        if goal is None:
            raise RuntimeError("scenario's goal not found")

        # Pathway + requirements + risk_factors — reuse the same region-aware
        # loading logic as ReasoningEngine._load_context so the evolution
        # prompt sees the same filtered risk set as the Bayesian reasoning.
        pathway = resolve_scenario_pathway(self.db, scenario)

        requirements: list[Requirement] = []
        if pathway is not None:
            # §11.3: Use M2M table, fall back to legacy pathway_id
            from app.models.goal import pathway_requirements, pathway_risk_factors

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
        if pathway is not None:
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

        base_p50 = float(
            (scenario.success_probability or {}).get("p50", 0.5)
        )

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

    def _build_prompt(self, scenario: Scenario, context: dict[str, Any]) -> list[dict[str, str]]:
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
            f"Scenario: {scenario.name}\n"
            f"Description: {scenario.description or 'N/A'}\n"
            f"Current success probability (P50): {context['base_p50']:.1%}\n\n"
            f"Context:\n{context['summary']}\n\n"
            f"Project the next {self.HORIZON_MONTHS} months for this scenario. "
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


def evolve_scenario_async(scenario_id: str, user_id: str) -> dict[str, Any]:
    """Standalone entry point for non-request-scoped callers (e.g. Celery).

    Opens its own DB session and resolves the user from ``user_id``.
    """
    with SessionLocal() as db:
        scenario = db.get(Scenario, scenario_id)
        if scenario is None:
            raise RuntimeError(f"Scenario {scenario_id} not found")
        # Build a minimal CurrentUser-like object — EvolutionService only
        # needs .id for memory/event scoping.
        user = type("U", (), {"id": user_id, "role": "user"})()
        return EvolutionService(db).evolve(scenario, user)
