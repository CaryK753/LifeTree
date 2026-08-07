"""Exa search engine implementation.

Exa excels at semantic search, academic papers, and technical documentation.
API docs: https://docs.exa.ai/reference
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.search_engines.base import ExtractedPage, SearchEngine, SearchHit

log = get_logger(__name__)

EXA_SEARCH_URL = "https://api.exa.ai/search"
EXA_CONTENTS_URL = "https://api.exa.ai/contents"


class ExaEngine(SearchEngine):
    """Exa — semantic search, academic/technical content."""

    name = "exa"
    domain_strengths = ["academic", "semantic", "technical"]

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
            log.warning("exa.no_api_key")
            return []

        headers = {"x-api-key": self._api_key, "Content-Type": "application/json"}
        payload: dict[str, object] = {
            "query": query,
            "numResults": max_results,
            "type": "auto",
        }
        # Map domain hints to Exa categories
        if domain == "academic":
            payload["category"] = "research paper"
        elif domain == "technical":
            payload["category"] = "github"
        if days is not None:
            payload["startPublishedDate"] = f"{days}d"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(EXA_SEARCH_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.error("exa.search_failed", error=str(exc), query=query)
            return []

        results: list[SearchHit] = []
        for item in data.get("results", []):
            results.append(
                SearchHit(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("text", "") or item.get("highlights", ""),
                    score=float(item.get("score", 0.0)),
                    published_at=item.get("publishedDate"),
                    engine="exa",
                )
            )
        log.info("exa.search_ok", query=query, n=len(results))
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
            log.warning("exa.no_api_key")
            return []

        url_list = [urls] if isinstance(urls, str) else urls
        headers = {"x-api-key": self._api_key, "Content-Type": "application/json"}
        # Exa contents API takes `urls` (NOT `ids`) per the official docs
        # at https://docs.exa.ai/reference/get-contents. Response items
        # return the page URL as both `id` and `url`.
        payload: dict[str, object] = {"urls": url_list, "text": True}

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(EXA_CONTENTS_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.error("exa.extract_failed", error=str(exc))
            return []

        out: list[ExtractedPage] = []
        for item in data.get("results", []):
            out.append(
                ExtractedPage(
                    url=item.get("id", ""),
                    content=item.get("text", "") or "",
                    title=item.get("title"),
                    engine="exa",
                )
            )
        log.info("exa.extract_ok", n=len(out))
        return out

    async def crawl(
        self,
        base_url: str,
        *,
        instructions: str | None = None,
        max_depth: int = 1,
        max_breadth: int = 20,
        limit: int = 50,
        **kwargs: Any,
    ) -> list[ExtractedPage]:
        """Exa has no native crawl — use findSimilar as a fallback."""
        if not self.available:
            return []

        headers = {"x-api-key": self._api_key, "Content-Type": "application/json"}
        payload: dict[str, object] = {
            "url": base_url,
            "numResults": min(limit, 50),
            "text": True,
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.exa.ai/findSimilar", json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.error("exa.crawl_failed", error=str(exc), url=base_url)
            return []

        out: list[ExtractedPage] = []
        for item in data.get("results", []):
            out.append(
                ExtractedPage(
                    url=item.get("url", ""),
                    content=item.get("text", "") or "",
                    title=item.get("title"),
                    engine="exa",
                )
            )
        log.info("exa.crawl_ok", url=base_url, n=len(out))
        return out
