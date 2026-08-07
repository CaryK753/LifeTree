"""Public-source crawler endpoint (multi-engine search / extract / crawl).

Originally a Tavily-only endpoint, now supports the configured default
engine plus optional ``engine`` / ``engines`` query parameters to select
a specific engine or run multi-engine parallel search. See
docs/specs/2026-08-07-cross-validation-deep-research-multi-source-search.md §A.
"""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.crawler import CrawlerService
from app.services.search_engines import ALL_ENGINE_NAMES, get_default_search_engine

router = APIRouter(prefix="/crawler", tags=["crawler"])


@router.get("/search")
async def search(
    q: str,
    max_results: int = 10,
    topic: str = "general",
    region: str | None = None,
    days: int | None = None,
    engine: str | None = None,
    engines: str | None = None,
    domain: str | None = None,
) -> list[dict]:
    """Run a search and return normalized results.

    Args:
        q: Search query.
        max_results: Max results per engine (default 10).
        topic: Tavily topic hint ("general"/"news").
        region: Region filter (e.g. "us", "cn").
        days: Limit to results published within N days.
        engine: Single engine to use ("tavily"/"exa"/"bocha"/"anysearch").
            Omit to use the configured default engine.
        engines: Comma-separated list of engines for multi-engine parallel
            search (e.g. "tavily,exa,bocha"). Results are merged and
            deduped by URL, tagged with their source engine. Takes
            precedence over ``engine``.
        domain: Vertical domain hint (consumed by AnySearch, ignored by
            other engines).

    Returns:
        List of normalized result dicts. Each includes an ``engine`` field
        indicating which engine produced it.
    """
    # Multi-engine parallel search
    if engines:
        engine_list = [e.strip() for e in engines.split(",") if e.strip()]
        invalid = [e for e in engine_list if e not in ALL_ENGINE_NAMES]
        if invalid:
            raise HTTPException(
                400,
                f"Unknown engines: {invalid}. Valid: {ALL_ENGINE_NAMES}",
            )
        if not engine_list:
            raise HTTPException(400, "engines parameter is empty after parsing")
        service = CrawlerService()
        results = await service.search_multi(
            q,
            engines=engine_list,
            max_results=max_results,
            domain=domain,
            topic=topic,
            region=region,
            days=days,
        )
        return [dataclasses.asdict(r) for r in results]

    # Single-engine search (explicit or default)
    chosen = engine or get_default_search_engine()
    if chosen not in ALL_ENGINE_NAMES:
        raise HTTPException(
            400,
            f"Unknown engine: {chosen!r}. Valid: {ALL_ENGINE_NAMES}",
        )
    service = CrawlerService(engine=chosen)
    if not service.available:
        return []
    results = await service.search(
        q,
        max_results=max_results,
        topic=topic,
        region=region,
        days=days,
        domain=domain,
    )
    return [dataclasses.asdict(r) for r in results]


class ExtractRequest(BaseModel):
    """Body for POST /crawler/extract."""

    urls: str | list[str] = Field(
        ...,
        description="A single URL or a list of URLs to extract full content from.",
    )
    query: str | None = Field(
        default=None,
        description="Optional user-intent query for reranking extracted chunks.",
    )
    extract_depth: str = Field(
        default="basic", description="'basic' or 'advanced' (tables/embeds)."
    )
    chunks_per_source: int = Field(
        default=3, ge=1, le=5, description="Chunks per source (1-5), only with query."
    )
    include_images: bool = False
    format: str = Field(default="markdown", description="'markdown' or 'text'.")
    timeout: float | None = Field(default=None, ge=1.0, le=60.0)
    engine: str | None = Field(
        default=None,
        description='Optional engine override ("tavily"/"exa"/"bocha"/"anysearch"). '
        "Omit to use the configured default.",
    )


@router.post("/extract")
async def extract(body: ExtractRequest) -> list[dict]:
    """Extract full page content for one or more URLs.

    Use this when ``/search`` returned only a snippet and the user wants the
    full article text. If the chosen engine doesn't support extract (e.g.
    Bocha), the service transparently falls back to Tavily extract when a
    Tavily key is configured.
    """
    chosen = body.engine or get_default_search_engine()
    if chosen not in ALL_ENGINE_NAMES:
        raise HTTPException(
            400,
            f"Unknown engine: {chosen!r}. Valid: {ALL_ENGINE_NAMES}",
        )
    service = CrawlerService(engine=chosen)
    if not service.available:
        raise HTTPException(503, f"Search engine {chosen!r} API key not configured")
    results = await service.extract(
        body.urls,
        query=body.query,
        extract_depth=body.extract_depth,
        chunks_per_source=body.chunks_per_source,
        include_images=body.include_images,
        format=body.format,
        timeout=body.timeout,
    )
    return [dataclasses.asdict(r) for r in results]


class CrawlRequest(BaseModel):
    """Body for POST /crawler/crawl."""

    url: str = Field(..., description="Root URL to begin the crawl.")
    instructions: str | None = None
    max_depth: int = Field(default=1, ge=1, le=5)
    max_breadth: int = Field(default=20, ge=1, le=500)
    limit: int = Field(default=50, ge=1)
    extract_depth: str = "basic"
    format: str = "markdown"
    select_paths: list[str] | None = None
    exclude_paths: list[str] | None = None
    timeout: float | None = Field(default=None, ge=10.0, le=150.0)
    engine: str | None = Field(
        default=None,
        description='Optional engine override. Omit to use the configured default.',
    )


@router.post("/crawl")
async def crawl(body: CrawlRequest) -> list[dict]:
    """Graph-based crawl from a base URL. Returns many pages."""
    chosen = body.engine or get_default_search_engine()
    if chosen not in ALL_ENGINE_NAMES:
        raise HTTPException(
            400,
            f"Unknown engine: {chosen!r}. Valid: {ALL_ENGINE_NAMES}",
        )
    service = CrawlerService(engine=chosen)
    if not service.available:
        raise HTTPException(503, f"Search engine {chosen!r} API key not configured")
    results = await service.crawl(
        body.url,
        instructions=body.instructions,
        max_depth=body.max_depth,
        max_breadth=body.max_breadth,
        limit=body.limit,
        extract_depth=body.extract_depth,
        format=body.format,
        select_paths=body.select_paths,
        exclude_paths=body.exclude_paths,
        timeout=body.timeout,
    )
    return [dataclasses.asdict(r) for r in results]
