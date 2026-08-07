"""博查 (Bocha) search engine implementation.

博查 excels at Chinese-language news, domestic policy, and forum content.
API docs: https://open.bochaai.com/docs
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.search_engines.base import ExtractedPage, SearchEngine, SearchHit

log = get_logger(__name__)

BOCHA_SEARCH_URL = "https://api.bochaai.com/v1/web-search"


class BochaEngine(SearchEngine):
    """博查 — Chinese news, domestic policy, forums."""

    name = "bocha"
    domain_strengths = ["chinese_news", "china_policy", "forum"]

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
            log.warning("bocha.no_api_key")
            return []

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, object] = {
            "query": query,
            "count": max_results,
            "summary": True,
        }
        if region:
            payload["region"] = region
        if days is not None:
            payload["freshness"] = f"oneMonth" if days <= 30 else "oneYear"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(BOCHA_SEARCH_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.error("bocha.search_failed", error=str(exc), query=query)
            return []

        # 博查 response: {"data": {"webPages": {"value": [...]}}}
        # Each item fields: name, url, summary, snippet, dateLastCrawled,
        # siteName, isFamilyFriendly, language. (No native score field —
        # we default to 0 and let cross-engine voting decide relevance.)
        web_pages = data.get("data", {}).get("webPages", {}).get("value", [])
        results: list[SearchHit] = []
        for item in web_pages:
            results.append(
                SearchHit(
                    title=item.get("name", ""),
                    url=item.get("url", ""),
                    snippet=item.get("summary", "") or item.get("snippet", ""),
                    score=float(item.get("score", 0.0)),
                    published_at=item.get("dateLastCrawled") or item.get("datePublished"),
                    engine="bocha",
                )
            )
        log.info("bocha.search_ok", query=query, n=len(results))
        return results

    async def extract(
        self,
        urls: str | list[str],
        *,
        query: str | None = None,
        extract_depth: str = "basic",
        **kwargs: Any,
    ) -> list[ExtractedPage]:
        """博查 has no native extract API — return failed markers.

        Callers should fall back to TavilyEngine.extract via the CrawlerService
        facade (which handles this gracefully).
        """
        url_list = [urls] if isinstance(urls, str) else urls
        log.warning("bocha.extract_unsupported")
        return [
            ExtractedPage(
                url=u,
                content="",
                failed=True,
                error="bocha extract unsupported, tavily not configured",
                engine="bocha",
            )
            for u in url_list
        ]

    async def crawl(
        self,
        base_url: str,
        *,
        limit: int = 50,
        **kwargs: Any,
    ) -> list[ExtractedPage]:
        """博查 has no native crawl — degrade to multiple searches."""
        if not self.available:
            return []
        log.warning("bocha.crawl_unsupported_degraded_to_search")
        # Degrade: search the base URL's domain
        hits = await self.search(base_url, max_results=min(limit, 20))
        return [
            ExtractedPage(url=h.url, content=h.snippet, title=h.title, engine="bocha")
            for h in hits
        ]
