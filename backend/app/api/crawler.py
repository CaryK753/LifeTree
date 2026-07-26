"""Public-source crawler endpoint (Tavily search / extract / crawl)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.crawler import CrawlerService

router = APIRouter(prefix="/crawler", tags=["crawler"])
_service = CrawlerService()


@router.get("/search")
async def search(
    q: str,
    max_results: int = 10,
    topic: str = "general",
    region: str | None = None,
    days: int | None = None,
) -> list[dict]:
    """Run a Tavily search and return normalized results."""
    if not _service.available:
        return []
    results = await _service.search(
        q, max_results=max_results, topic=topic, region=region, days=days
    )
    return [r.__dict__ for r in results]


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


@router.post("/extract")
async def extract(body: ExtractRequest) -> list[dict]:
    """Extract full page content for one or more URLs.

    Use this when ``/search`` returned only a snippet and the user wants the
    full article text.
    """
    if not _service.available:
        raise HTTPException(503, "Tavily API key not configured")
    results = await _service.extract(
        body.urls,
        query=body.query,
        extract_depth=body.extract_depth,
        chunks_per_source=body.chunks_per_source,
        include_images=body.include_images,
        format=body.format,
        timeout=body.timeout,
    )
    return [r.__dict__ for r in results]


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


@router.post("/crawl")
async def crawl(body: CrawlRequest) -> list[dict]:
    """Graph-based crawl from a base URL. Returns many pages."""
    if not _service.available:
        raise HTTPException(503, "Tavily API key not configured")
    results = await _service.crawl(
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
    return [r.__dict__ for r in results]
