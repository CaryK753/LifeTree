"""URL batch-extraction node (§C.2 of the spec).

Takes the top-N collected sources (sorted by score) and extracts their
full page content via ``CrawlerService.extract``. The extracted content
is capped at ``max_extract_chars`` total to keep token budgets predictable.

Each successful extraction is marked ``extracted=True`` on the source dict
and the char count is recorded so the structuring node knows how much
text is available per source.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.research import ResearchJob, ResearchStatus
from app.services.crawler import CrawlerService
from app.services.research.state import ResearchState

log = get_logger(__name__)

# Per-URL extraction cap (chars). Keeps any single source from
# monopolising the extract budget.
_PER_URL_CAP = 20000

# Batch size for parallel extract calls. Tavily extract supports up to 50
# URLs per call; smaller batches give finer-grained progress updates.
_BATCH_SIZE = 5


def extract_pages(
    db: Session,
    job: ResearchJob,
    state: ResearchState,
) -> ResearchState:
    """Extract full-page content for the top-N collected sources."""
    sources = state.get("collected_sources", [])
    if not sources:
        log.info("research.extract_no_sources", job_id=job.id)
        return state

    _update_job_status(
        job, ResearchStatus.EXTRACTING, "Extracting page contents", 0.40
    )
    db.commit()

    max_chars = state.get("max_extract_chars", 50000)
    total_chars = 0
    extracted_pages: list[dict[str, Any]] = state.get("extracted_pages", [])

    # Sort by score descending so the most relevant sources get extracted first.
    sorted_sources = sorted(sources, key=lambda s: s.get("score", 0.0), reverse=True)

    # Pick the engine to use for extraction. Prefer the engine of the
    # highest-scoring source (Tavily is the default fallback).
    extract_engine = next(
        (s.get("engine") for s in sorted_sources if s.get("engine")),
        None,
    )

    crawler = CrawlerService(engine=extract_engine) if extract_engine else CrawlerService()

    # Process in batches so a single failed batch doesn't lose everything.
    for batch_start in range(0, len(sorted_sources), _BATCH_SIZE):
        if total_chars >= max_chars:
            log.info(
                "research.extract_budget_reached",
                job_id=job.id,
                total_chars=total_chars,
                max=max_chars,
            )
            break

        batch = sorted_sources[batch_start : batch_start + _BATCH_SIZE]
        urls_to_extract = [
            s["url"]
            for s in batch
            if s.get("url") and not s.get("extracted")
        ]
        if not urls_to_extract:
            continue

        # Progress within extracting stage: 0.40 → 0.60.
        progress = 0.40 + 0.20 * (batch_start / max(1, len(sorted_sources)))
        job.progress = progress
        job.current_step = (
            f"Extracting batch {batch_start // _BATCH_SIZE + 1}"
        )
        db.commit()

        try:
            pages = asyncio.run(crawler.extract(urls_to_extract))
        except Exception as exc:  # noqa: BLE001
            log.error(
                "research.extract_batch_failed",
                job_id=job.id,
                batch_start=batch_start,
                error=str(exc),
            )
            state["failure_count"] = state.get("failure_count", 0) + 1
            continue

        for src, page in zip(batch, pages):
            if page.failed:
                log.info(
                    "research.extract_url_failed",
                    job_id=job.id,
                    url=src.get("url"),
                    error=page.error,
                )
                continue

            content = page.content or ""
            # Cap per-URL to avoid one source dominating the budget.
            capped = content[:_PER_URL_CAP]
            if len(capped) > max_chars - total_chars:
                capped = capped[: max_chars - total_chars]

            if not capped.strip():
                continue

            extracted_pages.append({
                "url": src["url"],
                "title": src.get("title") or page.url,
                "content": capped,
                "engine": src.get("engine") or page.engine,
                "published_at": src.get("published_at"),
                "sub_question": src.get("sub_question"),
                "source_id": src.get("source_id"),
            })

            src["extracted"] = True
            src["extract_chars"] = len(capped)
            total_chars += len(capped)

            if total_chars >= max_chars:
                break

        log.info(
            "research.extract_batch_done",
            job_id=job.id,
            batch_start=batch_start,
            total_chars=total_chars,
            pages_extracted=len(extracted_pages),
        )

    state["extracted_pages"] = extracted_pages
    state["collected_sources"] = sorted_sources

    job.progress = 0.60
    db.commit()

    log.info(
        "research.extract_complete",
        job_id=job.id,
        pages_extracted=len(extracted_pages),
        total_chars=total_chars,
    )
    return state


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
        from datetime import datetime, timezone

        job.started_at = datetime.now(timezone.utc)
