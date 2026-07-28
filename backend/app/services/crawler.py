"""Public-source crawler using Tavily search / extract / crawl APIs.

Per project plan §4.1, we outsource raw crawling to Tavily rather than
building bespoke scrapers. User-defined sources are ingested via the
structuring pipeline (`IngestTextRequest`).

Three endpoints are exposed:
- ``search``: keyword search, returns snippets + url
- ``extract``: full-page content for one or more URLs (markdown)
- ``crawl``: graph-based crawl from a base URL, returns many pages
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.core.logging import get_logger
from app.llm.registry import get_tavily_key

log = get_logger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
TAVILY_CRAWL_URL = "https://api.tavily.com/crawl"


@dataclass(slots=True)
class CrawlResult:
    title: str
    url: str
    content: str
    score: float
    published_at: str | None = None


@dataclass(slots=True)
class ExtractResult:
    url: str
    content: str
    images: list[str] = field(default_factory=list)
    favicon: str | None = None
    failed: bool = False
    error: str | None = None


class CrawlerService:
    """Thin wrapper around the Tavily search / extract / crawl APIs."""

    def __init__(self, api_key: str | None = None) -> None:
        # Read the key fresh on each construction so settings updates in the
        # UI take effect without a process restart. CrawlerService instances
        # are short-lived (one per request) so this is cheap.
        self._api_key = api_key if api_key is not None else get_tavily_key()

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        topic: str = "general",
        region: str | None = None,
        days: int | None = None,
    ) -> list[CrawlResult]:
        """Run an async Tavily search and return normalized results."""
        if not self.available:
            log.warning("crawler.no_api_key")
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
            log.error("crawler.search_failed", error=str(exc), query=query)
            return []

        results: list[CrawlResult] = []
        for item in data.get("results", []):
            results.append(
                CrawlResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    score=float(item.get("score", 0.0)),
                    published_at=item.get("published_date"),
                )
            )
        log.info("crawler.search_ok", query=query, n=len(results))
        return results

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
    ) -> list[ExtractResult]:
        """Extract full page content from one or more URLs via Tavily Extract.

        Use this when ``search`` returned only a snippet and the user wants
        the full article text. Returns markdown by default.
        """
        if not self.available:
            log.warning("crawler.no_api_key")
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
            log.error("crawler.extract_failed", error=str(exc))
            return []

        out: list[ExtractResult] = []
        for item in data.get("results", []):
            out.append(
                ExtractResult(
                    url=item.get("url", ""),
                    content=item.get("raw_content", "") or "",
                    images=item.get("images", []) or [],
                    favicon=item.get("favicon"),
                )
            )
        for item in data.get("failed_results", []):
            out.append(
                ExtractResult(
                    url=item.get("url", ""),
                    content="",
                    failed=True,
                    error=item.get("error"),
                )
            )
        log.info("crawler.extract_ok", n_ok=sum(1 for r in out if not r.failed), n_fail=sum(1 for r in out if r.failed))
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
    ) -> list[ExtractResult]:
        """Graph-based crawl from a base URL. Returns many pages.

        Use this when you need broad coverage of a documentation site or
        similar. For a single page, prefer ``extract``.
        """
        if not self.available:
            log.warning("crawler.no_api_key")
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
            # Crawl can take a while — give it 150s to match Tavily's max.
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(TAVILY_CRAWL_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.error("crawler.crawl_failed", error=str(exc), url=base_url)
            return []

        out: list[ExtractResult] = []
        for item in data.get("results", []):
            out.append(
                ExtractResult(
                    url=item.get("url", ""),
                    content=item.get("raw_content", "") or "",
                    favicon=item.get("favicon"),
                )
            )
        log.info("crawler.crawl_ok", url=base_url, n=len(out))
        return out
