"""Tavily search engine implementation.

Migrated from the original ``crawler.py`` — preserves the exact API
calls and response parsing so existing callers see no behaviour change.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.search_engines.base import ExtractedPage, SearchEngine, SearchHit

log = get_logger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
TAVILY_CRAWL_URL = "https://api.tavily.com/crawl"


class TavilyEngine(SearchEngine):
    """Tavily search / extract / crawl — general web, official, news."""

    name = "tavily"
    domain_strengths = ["general", "official", "news"]

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
    ) -> list[SearchHit]:
        if not self.available:
            log.warning("tavily.no_api_key")
            return []

        payload: dict[str, object] = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            "topic": topic,
            "include_answer": False,
            "include_raw_content": False,
        }
        if region:
            payload["country"] = region
        if days is not None:
            payload["days"] = days

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(TAVILY_SEARCH_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.error("tavily.search_failed", error=str(exc), query=query)
            return []

        results: list[SearchHit] = []
        for item in data.get("results", []):
            results.append(
                SearchHit(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    score=float(item.get("score", 0.0)),
                    published_at=item.get("published_date"),
                    engine="tavily",
                )
            )
        log.info("tavily.search_ok", query=query, n=len(results))
        return results

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
    ) -> list[ExtractedPage]:
        if not self.available:
            log.warning("tavily.no_api_key")
            return []

        payload: dict[str, object] = {
            "api_key": self._api_key,
            "urls": urls,
            "extract_depth": extract_depth,
            "format": format,
            "include_images": include_images,
        }
        if query:
            payload["query"] = query
            payload["chunks_per_source"] = max(1, min(5, chunks_per_source))
        if timeout is not None:
            payload["timeout"] = timeout

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(TAVILY_EXTRACT_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.error("tavily.extract_failed", error=str(exc))
            return []

        out: list[ExtractedPage] = []
        for item in data.get("results", []):
            out.append(
                ExtractedPage(
                    url=item.get("url", ""),
                    content=item.get("raw_content", "") or "",
                    images=item.get("images", []) or [],
                    favicon=item.get("favicon"),
                    engine="tavily",
                )
            )
        for item in data.get("failed_results", []):
            out.append(
                ExtractedPage(
                    url=item.get("url", ""),
                    content="",
                    failed=True,
                    error=item.get("error"),
                    engine="tavily",
                )
            )
        log.info(
            "tavily.extract_ok",
            n_ok=sum(1 for r in out if not r.failed),
            n_fail=sum(1 for r in out if r.failed),
        )
        return out

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
    ) -> list[ExtractedPage]:
        if not self.available:
            log.warning("tavily.no_api_key")
            return []

        payload: dict[str, object] = {
            "api_key": self._api_key,
            "url": base_url,
            "max_depth": max_depth,
            "max_breadth": max_breadth,
            "limit": limit,
            "extract_depth": extract_depth,
            "format": format,
            "allow_external": False,
        }
        if instructions:
            payload["instructions"] = instructions
        if select_paths:
            payload["select_paths"] = select_paths
        if exclude_paths:
            payload["exclude_paths"] = exclude_paths
        if timeout is not None:
            payload["timeout"] = timeout

        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(TAVILY_CRAWL_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.error("tavily.crawl_failed", error=str(exc), url=base_url)
            return []

        out: list[ExtractedPage] = []
        for item in data.get("results", []):
            out.append(
                ExtractedPage(
                    url=item.get("url", ""),
                    content=item.get("raw_content", "") or "",
                    favicon=item.get("favicon"),
                    engine="tavily",
                )
            )
        log.info("tavily.crawl_ok", url=base_url, n=len(out))
        return out
