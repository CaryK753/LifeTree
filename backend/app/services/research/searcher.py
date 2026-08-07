"""Multi-source search node (§C.2 of the spec).

Executes the research plan: for each sub-question, queries the planned
engines in parallel via ``CrawlerService.search_multi``, dedupes the
results by URL, and accumulates them in ``ResearchState.collected_sources``.

Respects the budget: stops once ``max_total_sources`` is reached. Each
collected source is tagged with its engine so the cross-validation layer
can later compute ``cross_engine_consensus``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.research import ResearchJob, ResearchStatus
from app.services.crawler import CrawlerService
from app.services.research.state import ResearchState

log = get_logger(__name__)


def search_sources(
    db: Session,
    job: ResearchJob,
    state: ResearchState,
) -> ResearchState:
    """Run multi-source search for each sub-question in the plan."""
    plan = state.get("plan") or {}
    sub_questions = plan.get("sub_questions", [])
    if not sub_questions:
        log.warning("research.search_no_subquestions", job_id=job.id)
        return state

    _update_job_status(
        job, ResearchStatus.SEARCHING, "Searching multiple sources", 0.15
    )
    db.commit()

    max_total = state.get("max_total_sources", 30)
    collected: list[dict[str, Any]] = state.get("collected_sources", [])
    seen_urls: set[str] = {c.get("url", "") for c in collected}

    for idx, sq in enumerate(sub_questions):
        if len(collected) >= max_total:
            log.info(
                "research.search_budget_reached",
                job_id=job.id,
                collected=len(collected),
                max=max_total,
            )
            break

        query = sq.get("q", "")
        if not query:
            continue

        engines = sq.get("engines") or job.engines or []
        max_sources = min(
            int(sq.get("max_sources", 5)),
            max_total - len(collected),
        )
        if max_sources <= 0:
            break

        # Progress within searching stage: 0.15 → 0.35.
        progress = 0.15 + 0.20 * (idx / max(1, len(sub_questions)))
        job.progress = progress
        job.current_step = f"Searching sub-question {idx + 1}/{len(sub_questions)}"
        db.commit()

        try:
            hits = _run_search(query, engines, max_sources)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "research.search_failed",
                job_id=job.id,
                sub_question=query,
                error=str(exc),
            )
            state["failure_count"] = state.get("failure_count", 0) + 1
            continue

        for hit in hits:
            url = hit.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            hit["sub_question"] = query
            hit["extracted"] = False
            hit["extract_chars"] = 0
            hit["source_id"] = None
            collected.append(hit)
            if len(collected) >= max_total:
                break

        log.info(
            "research.sub_question_searched",
            job_id=job.id,
            sub_question=query,
            engines=engines,
            hits=len(hits),
            total_collected=len(collected),
        )

    state["collected_sources"] = collected
    job.progress = 0.35
    db.commit()
    return state


def _run_search(
    query: str, engines: list[str], max_results: int
) -> list[dict[str, Any]]:
    """Run a single multi-engine search and return normalized hits.

    If multiple engines are configured, uses ``search_multi`` for parallel
    cross-engine retrieval. Falls back to single-engine search otherwise.
    """
    if not engines:
        # No engines specified — use the default engine.
        crawler = CrawlerService()
        if not crawler.available:
            return []
        results = asyncio.run(crawler.search(query, max_results=max_results))
        return [_crawl_result_to_dict(r) for r in results]

    # Filter to engines with configured keys.
    available_engines = [e for e in engines if _engine_has_key(e)]
    if not available_engines:
        log.warning("research.search_no_engines_with_keys", engines=engines)
        return []

    crawler = CrawlerService(engine=available_engines[0])
    if len(available_engines) == 1:
        results = asyncio.run(crawler.search(query, max_results=max_results))
        return [_crawl_result_to_dict(r) for r in results]

    results = asyncio.run(
        crawler.search_multi(
            query, engines=available_engines, max_results=max_results
        )
    )
    return [_crawl_result_to_dict(r) for r in results]


def _engine_has_key(engine_name: str) -> bool:
    """Check whether an engine has a configured API key."""
    try:
        from app.llm.registry import (
            get_anysearch_key,
            get_bocha_key,
            get_exa_key,
            get_tavily_key,
        )

        key_getters = {
            "tavily": get_tavily_key,
            "exa": get_exa_key,
            "bocha": get_bocha_key,
            "anysearch": get_anysearch_key,
        }
        getter = key_getters.get(engine_name)
        return bool(getter and getter())
    except Exception:  # noqa: BLE001
        return False


def _crawl_result_to_dict(result: Any) -> dict[str, Any]:
    """Convert a CrawlResult dataclass to a plain dict for state storage."""
    return {
        "url": getattr(result, "url", ""),
        "title": getattr(result, "title", ""),
        "snippet": getattr(result, "content", ""),
        "score": float(getattr(result, "score", 0.0)),
        "engine": getattr(result, "engine", ""),
        "published_at": getattr(result, "published_at", None),
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
    if job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
