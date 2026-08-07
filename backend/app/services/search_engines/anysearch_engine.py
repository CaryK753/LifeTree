"""AnySearch search engine implementation.

AnySearch is purpose-built for AI agents, with native support for vertical
domain search (domain/sub_domain) and batch parallel search.

Real API protocol (verified 2026-08-07 from the official anysearch-skill
repo at https://github.com/anysearch-ai/anysearch-skill):

  * Endpoint : POST https://api.anysearch.com/mcp
  * Protocol : JSON-RPC 2.0, method = "tools/call"
  * Auth     : Header "Authorization: Bearer <API_KEY>" (optional; anonymous
               access is supported with lower rate limits)
  * Commands : "search", "batch_search", "extract", "get_sub_domains"

Each command is invoked as a JSON-RPC tool call whose ``name`` is the
command and ``arguments`` is the command's argument object. This module
wraps that protocol behind the :class:`SearchEngine` ABC so callers can
treat AnySearch uniformly with Tavily/Exa/博查.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.search_engines.base import ExtractedPage, SearchEngine, SearchHit

log = get_logger(__name__)

ANYSEARCH_MCP_URL = "https://api.anysearch.com/mcp"

# Domains supported by AnySearch (mirrors scripts/shared/constants.json).
# Used by the domain router to decide when AnySearch is the best fit.
ANYSEARCH_DOMAINS = {
    "general", "resource", "social_media", "finance", "academic",
    "legal", "health", "business", "security", "ip", "code",
    "energy", "environment", "agriculture", "travel", "film", "gaming",
}


def _rpc(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 ``tools/call`` request body."""
    return {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
        },
    }


class AnySearchEngine(SearchEngine):
    """AnySearch — vertical domain data, parallel batch search.

    AnySearch exposes a JSON-RPC 2.0 interface at ``/mcp`` (the same
    endpoint used by its MCP/Skill clients). We adapt it to the REST-like
    :class:`SearchEngine` ABC by wrapping each call as a single JSON-RPC
    tool invocation.

    Anonymous access is supported when no API key is configured; this
    triggers lower rate limits but keeps the engine usable out-of-box.
    """

    name = "anysearch"
    domain_strengths = ["vertical", "structured", "batch"]

    @property
    def available(self) -> bool:
        # AnySearch supports anonymous access — always "available" so the
        # domain router can pick it even without an API key. The header
        # is only sent when ``self._api_key`` is non-empty.
        return True

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    async def _call(self, name: str, arguments: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any] | None:
        """Invoke a JSON-RPC tool call and return the ``result`` object.

        Returns ``None`` on transport / RPC error after logging.
        """
        body = _rpc(name, arguments)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(ANYSEARCH_MCP_URL, json=body, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.error("anysearch.rpc_failed", name=name, error=str(exc))
            return None
        if "error" in data:
            log.error(
                "anysearch.rpc_error",
                name=name,
                code=data["error"].get("code"),
                message=data["error"].get("message"),
            )
            return None
        return data.get("result") or {}

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        topic: str = "general",
        region: str | None = None,
        days: int | None = None,
        domain: str | None = None,
        sub_domain: str | None = None,
        sub_domain_params: dict[str, str] | str | None = None,
        **kwargs: Any,
    ) -> list[SearchHit]:
        # AnySearch caps at 10 results per call.
        max_results = max(1, min(10, max_results))
        arguments: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
        }
        if domain:
            arguments["domain"] = domain
        if sub_domain:
            arguments["sub_domain"] = sub_domain
        if sub_domain_params is not None:
            # AnySearch accepts either a key=value string or a JSON object.
            arguments["sub_domain_params"] = sub_domain_params
        if region:
            arguments["region"] = region
        if days is not None:
            arguments["freshness"] = days

        data = await self._call("search", arguments)
        if not data:
            return []

        items = data.get("results") or data.get("data", {}).get("results") or []
        out: list[SearchHit] = []
        for item in items:
            out.append(
                SearchHit(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", "") or item.get("snippet", "") or item.get("summary", ""),
                    score=float(item.get("score", 0.0)),
                    published_at=item.get("published_at") or item.get("publishedDate"),
                    engine="anysearch",
                )
            )
        log.info("anysearch.search_ok", query=query, n=len(out))
        return out

    async def batch_search(
        self,
        queries: list[str],
        *,
        max_results: int = 10,
        domain: str | None = None,
        **kwargs: Any,
    ) -> dict[str, list[SearchHit]]:
        """Native batch search — single JSON-RPC call for up to 5 queries."""
        if not queries:
            return {}
        # AnySearch caps batch_search at 5 queries.
        if len(queries) > 5:
            log.warning("anysearch.batch_truncated", requested=len(queries), limit=5)
            queries = queries[:5]
        max_results = max(1, min(10, max_results))
        arguments: dict[str, Any] = {
            "queries": [{"query": q} for q in queries],
            "max_results": max_results,
        }
        if domain:
            arguments["domain"] = domain

        data = await self._call("batch_search", arguments, timeout=60.0)
        if not data:
            # Fallback to sequential search.
            return await super().batch_search(queries, max_results=max_results, domain=domain, **kwargs)

        # Response may be either {query: [items]} or {results: {query: [items]}}.
        raw = data.get("results") if isinstance(data.get("results"), dict) else data
        results: dict[str, list[SearchHit]] = {}
        for q in queries:
            items = raw.get(q, []) if isinstance(raw, dict) else []
            results[q] = [
                SearchHit(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", "") or item.get("snippet", "") or item.get("summary", ""),
                    score=float(item.get("score", 0.0)),
                    published_at=item.get("published_at"),
                    engine="anysearch",
                )
                for item in items
            ]
        log.info("anysearch.batch_ok", n_queries=len(queries))
        return results

    async def extract(
        self,
        urls: str | list[str],
        *,
        query: str | None = None,
        extract_depth: str = "basic",
        **kwargs: Any,
    ) -> list[ExtractedPage]:
        # AnySearch extract only accepts a single URL per call.
        url_list = [urls] if isinstance(urls, str) else urls
        out: list[ExtractedPage] = []
        for u in url_list:
            data = await self._call("extract", {"url": u}, timeout=60.0)
            if not data:
                out.append(ExtractedPage(url=u, content="", failed=True, error="anysearch extract empty", engine="anysearch"))
                continue
            content = data.get("content", "") or data.get("markdown", "") or ""
            out.append(
                ExtractedPage(
                    url=u,
                    content=content,
                    title=data.get("title"),
                    engine="anysearch",
                )
            )
        log.info("anysearch.extract_ok", n_ok=sum(1 for r in out if not r.failed))
        return out

    async def crawl(
        self,
        base_url: str,
        *,
        limit: int = 50,
        **kwargs: Any,
    ) -> list[ExtractedPage]:
        """AnySearch has no native crawl — degrade to search + extract."""
        log.warning("anysearch.crawl_degraded_to_search_extract")
        hits = await self.search(base_url, max_results=min(limit, 10))
        if not hits:
            return []
        urls = [h.url for h in hits if h.url]
        return await self.extract(urls)
