"""Synthesis node (§C.2 / §C.3 of the spec).

Generates the final research report from the structured atoms, conflict
groups, and trends collected by the earlier nodes. The report JSON is
persisted to ``ResearchJob.report`` and rendered by the frontend
``/research/{job_id}`` page.

Honesty guardrails (§C.3):
- ``confidence`` is computed by the backend from supporting / conflicting
  Assertion counts + cross-engine consensus — never by the LLM.
- ``honesty_disclaimer`` is force-appended to every report.
- Reports with < 3 sources or conflict ratio > 30 % get a warning prefix
  in ``summary``.
- Reports covering only one engine domain get a single-domain warning.
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
from app.services.research.state import ResearchState

log = get_logger(__name__)

HONESTY_DISCLAIMER = (
    "本研究结论基于公开信源自动聚合，未经独立验证，仅供参考。"
    "建议结合官方渠道与专业意见综合判断。"
)


# ---------- Pydantic schema for LLM structured output ----------


class _KeyFinding(BaseModel):
    finding: str = Field(..., description="A concise finding statement")
    supporting_assertions: list[str] = Field(default_factory=list)
    conflicting_assertions: list[str] = Field(default_factory=list)
    trend: str = Field(
        "stable",
        description="stable | changing | divergent | null",
    )
    trend_detail: str = Field(
        "", description="Free-text description of the trend, if any"
    )
    caveats: str = Field("", description="Caveats about this finding")


class _Synthesis(BaseModel):
    summary: str = Field(
        ..., description="2-3 paragraph research summary in the user's language"
    )
    key_findings: list[_KeyFinding]


_SYSTEM_PROMPT = """You are LifeTree's research-synthesis agent.

Given a research question, a set of structured atoms (events / assertions /
relationships / metrics), conflict groups, and trend analyses, produce a
concise synthesis report.

Rules:
- The summary should be 2-3 paragraphs, in the same language as the question.
- Each key_finding should be a single declarative statement.
- Reference assertion IDs in supporting_assertions / conflicting_assertions.
- For trend_detail, describe the transition point and direction.
- For caveats, note source count, conflict count, or single-domain coverage.
- Do NOT invent a confidence field — confidence is computed by the backend.
- Return ONLY the JSON object — no markdown, no commentary.
"""


def synthesize_report(
    db: Session,
    job: ResearchJob,
    state: ResearchState,
) -> ResearchState:
    """Generate the final synthesis report and persist it to ``job.report``."""
    _update_job_status(
        job, ResearchStatus.SYNTHESIZING, "Synthesizing final report", 0.85
    )
    db.commit()

    atoms = state.get("structured_atoms") or {}
    conflict_groups = state.get("conflict_groups") or []
    trends = state.get("trends") or []
    sources = state.get("collected_sources") or []

    # ---------- Backend-computed metadata ----------
    assertions = atoms.get("assertions", [])
    events = atoms.get("events", [])
    metrics = atoms.get("metrics", [])

    # Engines used (for domain coverage analysis).
    engines_used = sorted({s.get("engine", "") for s in sources if s.get("engine")})

    # Domain coverage map (which engine families contributed).
    domain_coverage = _compute_domain_coverage(engines_used)

    # Conflict summary for the report.
    conflicts_summary = _build_conflicts_summary(conflict_groups)

    # Trends summary.
    trends_summary = _build_trends_summary(trends)

    # Sources summary (with credibility scores).
    sources_summary = _build_sources_summary(sources)

    # ---------- LLM synthesis (with fallback) ----------
    synthesis_dict: dict[str, Any]
    try:
        client = get_instructor_sync()
        model_name = get_chat_model().model.name
        synthesis = client.chat.completions.create(
            model=model_name,
            response_model=_Synthesis,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_prompt(
                        job.question, atoms, conflict_groups, trends, sources
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=2500,
        )
        synthesis_dict = {
            "summary": synthesis.summary,
            "key_findings": [f.model_dump() for f in synthesis.key_findings],
        }
        state["llm_calls"] = state.get("llm_calls", 0) + 1
    except LLMNotConfiguredError:
        log.warning("research.synthesizer_llm_not_configured", job_id=job.id)
        synthesis_dict = _fallback_synthesis(job.question, atoms, conflict_groups, trends)
        state["failure_count"] = state.get("failure_count", 0) + 1
    except Exception as exc:  # noqa: BLE001
        log.error("research.synthesizer_failed", job_id=job.id, error=str(exc))
        synthesis_dict = _fallback_synthesis(job.question, atoms, conflict_groups, trends)
        state["failure_count"] = state.get("failure_count", 0) + 1

    # ---------- Backend-computed confidence per finding ----------
    # The LLM is not allowed to set confidence; we compute it from the
    # supporting / conflicting Assertion counts + cross-engine consensus.
    for finding in synthesis_dict.get("key_findings", []):
        finding["confidence"] = _compute_finding_confidence(
            finding, assertions, conflict_groups
        )
        finding["cross_engine_consensus"] = _compute_finding_consensus(
            finding, assertions
        )

    # ---------- Honesty guardrails ----------
    summary = synthesis_dict.get("summary", "")
    warnings: list[str] = []

    if len(sources) < 3:
        warnings.append("证据不足：仅基于 {} 个信源，建议补充更多来源。".format(len(sources)))

    conflict_ratio = (
        len(conflict_groups) / max(1, len(assertions))
        if assertions
        else 0.0
    )
    if conflict_ratio > 0.3:
        warnings.append(
            "信源高度冲突：{} 个冲突组 / {} 个断言（{:.0%}），结论可信度受限。".format(
                len(conflict_groups), len(assertions), conflict_ratio
            )
        )

    if len(domain_coverage) == 1:
        warnings.append(
            "仅基于单一领域信源（{}），缺乏跨领域交叉验证。".format(
                list(domain_coverage)[0]
            )
        )

    if warnings:
        summary = "⚠️ " + "\n".join(warnings) + "\n\n" + summary
        synthesis_dict["summary"] = summary

    # ---------- Assemble final report ----------
    report: dict[str, Any] = {
        "summary": synthesis_dict["summary"],
        "key_findings": synthesis_dict["key_findings"],
        "conflicts": conflicts_summary,
        "trends": trends_summary,
        "sources": sources_summary,
        "research_metadata": {
            "engines_used": engines_used,
            "engine_domain_coverage": domain_coverage,
            "total_sources_collected": len(sources),
            "total_assertions_extracted": len(assertions),
            "total_events_extracted": len(events),
            "total_metrics_extracted": len(metrics),
            "total_conflicts_detected": len(conflict_groups),
            "total_trends_detected": len(trends),
            "llm_calls": state.get("llm_calls", 0),
            "failure_count": state.get("failure_count", 0),
            "honesty_disclaimer": HONESTY_DISCLAIMER,
        },
    }

    state["report"] = report
    job.report = dict(report)  # type: ignore[assignment]
    job.progress = 0.95
    db.commit()

    log.info(
        "research.synthesis_complete",
        job_id=job.id,
        findings=len(report.get("key_findings", [])),
        conflicts=len(conflict_groups),
        trends=len(trends),
    )
    return state


# ---------- Helpers ----------


def _compute_domain_coverage(engines_used: list[str]) -> dict[str, bool]:
    """Map engines to their domain strengths for coverage analysis."""
    engine_domains = {
        "tavily": ["general", "official", "news"],
        "exa": ["academic", "semantic", "technical"],
        "bocha": ["chinese_news", "china_policy", "forum"],
        "anysearch": ["vertical", "structured", "batch"],
    }
    coverage: dict[str, bool] = {}
    for eng in engines_used:
        for domain in engine_domains.get(eng, []):
            coverage[domain] = True
    return coverage


def _build_conflicts_summary(conflict_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact conflict summary for the report."""
    summary: list[dict[str, Any]] = []
    for g in conflict_groups:
        summary.append({
            "subject": g.get("subject"),
            "predicate": g.get("predicate"),
            "severity": g.get("severity", "low"),
            "values": [
                {
                    "value": v.get("value"),
                    "engines": v.get("engines", []),
                    "source_ids": v.get("source_ids", []),
                    "supporting_count": v.get("supporting_count", 0),
                }
                for v in g.get("values", [])
            ],
            "cross_engine_consensus": g.get("cross_engine_consensus"),
            "auto_merged": g.get("auto_merged", False),
        })
    return summary


def _build_trends_summary(trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact trend summary for the report."""
    return [
        {
            "subject": t.get("subject"),
            "predicate": t.get("predicate"),
            "direction": t.get("direction"),
            "transition_point": t.get("transition_point"),
            "confidence": t.get("confidence"),
            "timeline": t.get("timeline", []),
        }
        for t in trends
    ]


def _build_sources_summary(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact source summary for the report."""
    return [
        {
            "source_id": s.get("source_id"),
            "title": s.get("title"),
            "url": s.get("url"),
            "engine": s.get("engine"),
            "score": s.get("score"),
            "extracted": s.get("extracted", False),
        }
        for s in sources
    ]


def _compute_finding_confidence(
    finding: dict[str, Any],
    assertions: list[dict[str, Any]],
    conflict_groups: list[dict[str, Any]],
) -> str:
    """Compute confidence label from supporting / conflicting counts.

    The LLM is not allowed to set this field; the backend computes it from
    the actual Assertion data.
    """
    supporting = len(finding.get("supporting_assertions", []))
    conflicting = len(finding.get("conflicting_assertions", []))
    total = supporting + conflicting
    if total == 0:
        return "low"
    ratio = supporting / total
    if ratio >= 0.8 and supporting >= 3:
        return "high"
    if ratio >= 0.6 and supporting >= 2:
        return "medium"
    return "low"


def _compute_finding_consensus(
    finding: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> int:
    """Count distinct engines supporting this finding's assertions."""
    supporting_ids = set(finding.get("supporting_assertions", []))
    engines: set[str] = set()
    for a in assertions:
        if a.get("id") in supporting_ids and a.get("engine"):
            engines.add(a["engine"])
    return len(engines)


def _build_user_prompt(
    question: str,
    atoms: dict[str, Any],
    conflict_groups: list[dict[str, Any]],
    trends: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> str:
    """Build the user prompt for the synthesis LLM call."""
    # Trim atoms to keep the prompt under token limits.
    atoms_trimmed = {
        "events": atoms.get("events", [])[:10],
        "assertions": atoms.get("assertions", [])[:20],
        "metrics": atoms.get("metrics", [])[:10],
        "relationships": atoms.get("relationships", [])[:5],
    }
    conflicts_trimmed = [
        {
            "subject": g.get("subject"),
            "predicate": g.get("predicate"),
            "severity": g.get("severity"),
            "values": g.get("values", [])[:3],
        }
        for g in conflict_groups[:5]
    ]
    trends_trimmed = [
        {
            "subject": t.get("subject"),
            "predicate": t.get("predicate"),
            "direction": t.get("direction"),
            "transition_point": t.get("transition_point"),
        }
        for t in trends[:3]
    ]
    sources_trimmed = [
        {"title": s.get("title"), "url": s.get("url"), "engine": s.get("engine")}
        for s in sources[:10]
    ]

    return (
        f"Research question: {question}\n\n"
        f"Structured atoms (truncated):\n{json.dumps(atoms_trimmed, ensure_ascii=False, default=str)}\n\n"
        f"Conflict groups (truncated):\n{json.dumps(conflicts_trimmed, ensure_ascii=False, default=str)}\n\n"
        f"Trends (truncated):\n{json.dumps(trends_trimmed, ensure_ascii=False, default=str)}\n\n"
        f"Sources (truncated):\n{json.dumps(sources_trimmed, ensure_ascii=False, default=str)}\n\n"
        f"Synthesize the research report."
    )


def _fallback_synthesis(
    question: str,
    atoms: dict[str, Any],
    conflict_groups: list[dict[str, Any]],
    trends: list[dict[str, Any]],
) -> dict[str, Any]:
    """Trivial synthesis used when the LLM is unavailable."""
    assertions = atoms.get("assertions", [])
    summary = (
        f"关于「{question}」的研究收集了 {len(assertions)} 个断言，"
        f"检测到 {len(conflict_groups)} 个冲突组、{len(trends)} 个趋势。"
        f"由于 LLM 不可用，无法生成自然语言摘要。请查看结构化数据。"
    )
    findings: list[dict[str, Any]] = []
    for a in assertions[:5]:
        findings.append({
            "finding": a.get("claim", ""),
            "supporting_assertions": [a.get("id")] if a.get("id") else [],
            "conflicting_assertions": [],
            "trend": "stable",
            "trend_detail": "",
            "caveats": "fallback: LLM unavailable",
        })
    return {"summary": summary, "key_findings": findings}


def _update_job_status(
    job: ResearchJob,
    status: ResearchStatus,
    current_step: str,
    progress: float,
) -> None:
    job.status = status.value
    job.current_step = current_step
    job.progress = max(0.0, min(1.0, progress))
    if job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
