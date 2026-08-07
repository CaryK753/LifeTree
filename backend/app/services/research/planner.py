"""Research planning node (§C.2 of the spec).

Calls the LLM to decompose the user's research question into sub-questions,
each annotated with the engines to query and expected domains. The plan is
persisted to ``ResearchJob.plan`` so the user can preview it on the
``/research/{job_id}`` page before / while the rest of the pipeline runs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.exceptions import LLMNotConfiguredError
from app.core.logging import get_logger
from app.llm.client import get_chat_model, get_instructor_sync
from app.models.research import ResearchJob, ResearchStatus
from app.services.research.state import ResearchPlan, ResearchState

log = get_logger(__name__)


# ---------- Default budget ----------

DEFAULT_MAX_SUB_QUESTIONS = 5
DEFAULT_MAX_TOTAL_SOURCES = 30
DEFAULT_MAX_EXTRACT_CHARS = 50000
DEFAULT_MAX_LLM_CALLS = 20


# ---------- Pydantic schema for LLM structured output ----------


class _SubQuestion(BaseModel):
    q: str = Field(..., description="A focused sub-question")
    engines: list[str] = Field(
        default_factory=list,
        description="Engines to query (subset of configured engines)",
    )
    max_sources: int = Field(3, description="Max URLs to collect for this sub-question")
    expected_domains: list[str] = Field(
        default_factory=list,
        description="Expected domains (e.g. policy, academic, news)",
    )


class _Plan(BaseModel):
    sub_questions: list[_SubQuestion]
    rationale: str = Field("", description="Why this decomposition was chosen")
    expected_domains: list[str] = Field(
        default_factory=list, description="Union of all sub-question domains"
    )


_SYSTEM_PROMPT = """You are LifeTree's research-planning agent.

Given a research question, a scope, and a list of available search engines,
decompose the question into focused sub-questions. Each sub-question should:
- Be answerable from public web sources.
- Have a clear expected domain (policy / academic / news / forum / vertical).
- Map to 1-3 engines best suited for that domain.

Engine domain strengths:
- tavily: general, official, news (English-language official sources)
- exa: academic, semantic, technical (papers, research, technical docs)
- bocha: chinese_news, china_policy, forum (Chinese-language sources)
- anysearch: vertical, structured, batch (structured domain-specific data)

Rules:
- Decompose into 2-N sub-questions (N = max_sub_questions).
- Prefer cross-engine coverage for fact-type sub-questions (so cross-
  validation can vote across domains).
- For trend-type sub-questions, suggest multiple engines for time-window
  comparison.
- If only one engine is available, route all sub-questions to it.
- Return ONLY the JSON object — no markdown, no commentary.
"""


def _build_user_prompt(
    question: str,
    scope: dict[str, Any],
    engines: list[str],
    max_sub_questions: int,
) -> str:
    scope_summary = json.dumps(scope, ensure_ascii=False, default=str)
    engines_str = ", ".join(engines) if engines else "(none configured)"
    return (
        f"Research question: {question}\n"
        f"Scope: {scope_summary}\n"
        f"Available engines: [{engines_str}]\n"
        f"Max sub-questions: {max_sub_questions}\n\n"
        f"Decompose into focused sub-questions."
    )


def plan_research(
    db: Session,
    job: ResearchJob,
    state: ResearchState,
) -> ResearchState:
    """Generate the research plan via LLM and persist it to the job row.

    On LLM failure (or no chat model configured), falls back to a trivial
    single-question plan that re-queries the original question with each
    configured engine. The job continues — a missing plan must not abort
    the whole pipeline.
    """
    # Resolve budget from scope overrides or defaults.
    scope = job.scope or {}
    max_sub_questions = int(
        scope.get("max_sub_questions", DEFAULT_MAX_SUB_QUESTIONS)
    )
    max_total_sources = int(
        scope.get("max_total_sources", DEFAULT_MAX_TOTAL_SOURCES)
    )
    max_extract_chars = int(
        scope.get("max_extract_chars", DEFAULT_MAX_EXTRACT_CHARS)
    )
    max_llm_calls = int(scope.get("max_llm_calls", DEFAULT_MAX_LLM_CALLS))

    state.update(
        {
            "max_sub_questions": max_sub_questions,
            "max_total_sources": max_total_sources,
            "max_extract_chars": max_extract_chars,
            "max_llm_calls": max_llm_calls,
            "llm_calls": state.get("llm_calls", 0),
            "failure_count": state.get("failure_count", 0),
            "collected_sources": [],
            "extracted_pages": [],
            "structured_atoms": {
                "events": [],
                "assertions": [],
                "relationships": [],
                "metrics": [],
            },
            "conflict_groups": [],
            "trends": [],
        }
    )

    # Mark the job as planning.
    _update_job_status(job, ResearchStatus.PLANNING, "Generating research plan", 0.05)
    db.commit()

    engines = job.engines or []
    plan_dict: ResearchPlan

    try:
        client = get_instructor_sync()
        model_name = get_chat_model().model.name
        plan = client.chat.completions.create(
            model=model_name,
            response_model=_Plan,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_prompt(
                        job.question, scope, engines, max_sub_questions
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        plan_dict = {
            "sub_questions": [sq.model_dump() for sq in plan.sub_questions],
            "rationale": plan.rationale,
            "expected_domains": plan.expected_domains,
        }
        state["llm_calls"] = state.get("llm_calls", 0) + 1
    except LLMNotConfiguredError:
        log.warning("research.planner_llm_not_configured", job_id=job.id)
        plan_dict = _fallback_plan(job.question, engines, max_sub_questions)
        state["failure_count"] = state.get("failure_count", 0) + 1
    except Exception as exc:  # noqa: BLE001
        log.error("research.planner_failed", job_id=job.id, error=str(exc))
        plan_dict = _fallback_plan(job.question, engines, max_sub_questions)
        state["failure_count"] = state.get("failure_count", 0) + 1

    # Cap sub-questions at the budget.
    if len(plan_dict.get("sub_questions", [])) > max_sub_questions:
        plan_dict["sub_questions"] = plan_dict["sub_questions"][:max_sub_questions]

    state["plan"] = plan_dict
    job.plan = dict(plan_dict)  # type: ignore[assignment]
    db.commit()

    log.info(
        "research.plan_generated",
        job_id=job.id,
        sub_questions=len(plan_dict.get("sub_questions", [])),
    )
    return state


def _fallback_plan(
    question: str, engines: list[str], max_sub_questions: int
) -> ResearchPlan:
    """Trivial single-question plan used when the LLM is unavailable."""
    sub_q: dict[str, Any] = {
        "q": question,
        "engines": engines[:3] if engines else [],
        "max_sources": 5,
        "expected_domains": ["general"],
    }
    return {
        "sub_questions": [sub_q][:max_sub_questions],
        "rationale": "fallback: LLM unavailable, using the original question",
        "expected_domains": ["general"],
    }


def _update_job_status(
    job: ResearchJob,
    status: ResearchStatus,
    current_step: str,
    progress: float,
) -> None:
    job.status = status.value
    job.current_step = current_step
    job.progress = max(0.0, min(1.0, progress))
    if status == ResearchStatus.PLANNING and job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
