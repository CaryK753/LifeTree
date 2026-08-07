"""Public-source crawler — facade over pluggable search engines.

Originally a thin Tavily wrapper, now delegates to :mod:`app.services.search_engines`
which supports Tavily, Exa, 博查, and AnySearch. The facade preserves the
original ``CrawlResult`` / ``ExtractResult`` data classes and method signatures
so existing callers (``api/crawler.py``, ``advisor/tools.py``, ``workers/tasks.py``,
``source_discovery.py``) work without changes.

Design doc: docs/specs/2026-08-07-cross-validation-deep-research-multi-source-search.md §A
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.services.search_engines import get_engine, get_default_search_engine
from app.services.search_engines.base import ExtractedPage, SearchEngine, SearchHit

log = get_logger(__name__)


# ---------- Legacy data classes (kept for backward compatibility) ----------


@dataclass(slots=True)
class CrawlResult:
    """Normalized search result (legacy, kept for API compatibility)."""

    title: str
    url: str
    content: str
    score: float
    published_at: str | None = None
    engine: str = ""  # populated when multi-engine search is used


@dataclass(slots=True)
class ExtractResult:
    """Normalized extract result (legacy, kept for API compatibility)."""

    url: str
    content: str
    images: list[str] = field(default_factory=list)
    favicon: str | None = None
    failed: bool = False
    error: str | None = None
    engine: str = ""


# ---------- Engine key resolution ----------


def _resolve_engine_key(engine_name: str, api_key: str | None) -> str:
    """Resolve the API key for an engine.

    If ``api_key`` is provided, use it. Otherwise read from registry.
    """
    if api_key is not None:
        return api_key

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
        getter = key_getters.get(engine_name, get_tavily_key)
        return getter()
    except Exception:
        return ""


# ---------- Facade service ----------


class CrawlerService:
    """Facade over pluggable search engines.

    Delegates ``search`` / ``extract`` / ``crawl`` to a concrete
    :class:`SearchEngine` and converts results to the legacy
    ``CrawlResult`` / ``ExtractResult`` types.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        engine: str | None = None,
    ) -> None:
        # Resolve which engine to use
        self._engine_name = engine or get_default_search_engine()
        resolved_key = _resolve_engine_key(self._engine_name, api_key)
        self._engine: SearchEngine = get_engine(self._engine_name, api_key=resolved_key)

    @property
    def available(self) -> bool:
        return self._engine.available

    @property
    def engine_name(self) -> str:
        return self._engine_name

    # ---------- search ----------

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        topic: str = "general",
        region: str | None = None,
        days: int | None = None,
        domain: str | None = None,
        **kwargs: Any,
    ) -> list[CrawlResult]:
        """Run an async search and return normalized results."""
        hits = await self._engine.search(
            query,
            max_results=max_results,
            topic=topic,
            region=region,
            days=days,
            domain=domain,
            **kwargs,
        )
        return [self._hit_to_result(h) for h in hits]

    async def crawl_for_goal(
        self,
        goal_title: str,
        scenario: str,
        *,
        max_results: int = 10,
    ) -> list[CrawlResult]:
        """Build a goal-aware query and search for fresh information."""
        query = f"{goal_title} latest news policy update {scenario}".strip()
        return await self.search(query, max_results=max_results)

    # ---------- extract ----------

    async def extract(
        self,
        urls: str | list[str],
        *,
        query: str | None = None,
        extract_depth: str = "basic",
        chunks_per_source: int = 3,
        include_images: bool = False,
        format: str = "markdown",
        timeout: float | None = None,
        **kwargs: Any,
    ) -> list[ExtractResult]:
        """Extract full page content from one or more URLs."""
        pages = await self._engine.extract(
            urls,
            query=query,
            extract_depth=extract_depth,
            chunks_per_source=chunks_per_source,
            include_images=include_images,
            format=format,
            timeout=timeout,
            **kwargs,
        )
        results = [self._page_to_result(p) for p in pages]

        # Fallback: if engine returned all-failed (e.g. bocha extract unsupported),
        # try Tavily extract as a graceful degradation.
        if results and all(r.failed for r in results) and self._engine_name != "tavily":
            tavily_key = _resolve_engine_key("tavily", None)
            if tavily_key:
                log.info("crawler.extract_fallback_to_tavily", engine=self._engine_name)
                tavily_engine = get_engine("tavily", api_key=tavily_key)
                tavily_pages = await tavily_engine.extract(
                    urls,
                    query=query,
                    extract_depth=extract_depth,
                    format=format,
                )
                results = [self._page_to_result(p) for p in tavily_pages]

        return results

    # ---------- crawl ----------

    async def crawl(
        self,
        base_url: str,
        *,
        instructions: str | None = None,
        max_depth: int = 1,
        max_breadth: int = 20,
        limit: int = 50,
        extract_depth: str = "basic",
        format: str = "markdown",
        select_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> list[ExtractResult]:
        """Graph-based crawl from a base URL."""
        pages = await self._engine.crawl(
            base_url,
            instructions=instructions,
            max_depth=max_depth,
            max_breadth=max_breadth,
            limit=limit,
            extract_depth=extract_depth,
            format=format,
            select_paths=select_paths,
            exclude_paths=exclude_paths,
            timeout=timeout,
            **kwargs,
        )
        return [self._page_to_result(p) for p in pages]

    # ---------- multi-engine parallel search ----------

    async def search_multi(
        self,
        query: str,
        *,
        engines: list[str],
        max_results: int = 10,
        domain: str | None = None,
        **kwargs: Any,
    ) -> list[CrawlResult]:
        """Search across multiple engines in parallel, merge and dedupe.

        Each result is tagged with its source ``engine`` so downstream
        cross-validation can compute ``cross_engine_consensus``.
        """
        tasks: list[asyncio.Task[list[SearchHit]]] = []
        engine_names: list[str] = []
        for eng in engines:
            key = _resolve_engine_key(eng, None)
            if not key:
                log.warning("crawler.multi_engine_skip_no_key", engine=eng)
                continue
            eng_instance = get_engine(eng, api_key=key)
            task = asyncio.create_task(
                eng_instance.search(
                    query, max_results=max_results, domain=domain, **kwargs
                )
            )
            tasks.append(task)
            engine_names.append(eng)

        if not tasks:
            return []

        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_hits: list[SearchHit] = []
        for eng_name, res in zip(engine_names, results_lists):
            if isinstance(res, Exception):
                log.error("crawler.multi_engine_failed", engine=eng_name, error=str(res))
                continue
            all_hits.extend(res)

        # Dedupe by URL, keep highest-score version
        seen: dict[str, SearchHit] = {}
        for hit in all_hits:
            if hit.url not in seen or hit.score > seen[hit.url].score:
                seen[hit.url] = hit

        merged = sorted(seen.values(), key=lambda h: h.score, reverse=True)
        return [self._hit_to_result(h) for h in merged]

    # ---------- converters ----------

    @staticmethod
    def _hit_to_result(hit: SearchHit) -> CrawlResult:
        return CrawlResult(
            title=hit.title,
            url=hit.url,
            content=hit.snippet,
            score=hit.score,
            published_at=hit.published_at,
            engine=hit.engine,
        )

    @staticmethod
    def _page_to_result(page: ExtractedPage) -> ExtractResult:
        return ExtractResult(
            url=page.url,
            content=page.content,
            images=page.images,
            favicon=page.favicon,
            failed=page.failed,
            error=page.error,
            engine=page.engine,
        )
