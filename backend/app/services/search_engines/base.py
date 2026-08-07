"""Search engine abstraction layer.

Defines the uniform interface that all search engines (Tavily, Exa, 博查,
AnySearch) implement. ``CrawlerService`` delegates to a concrete engine
via the factory in ``__init__.py``.

Design doc: docs/specs/2026-08-07-cross-validation-deep-research-multi-source-search.md §A
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class SearchHit:
    """A single search result from any engine."""

    title: str
    url: str
    snippet: str
    score: float  # 0..1, engine-native relevance
    published_at: str | None = None
    engine: str = ""  # "tavily" | "exa" | "bocha" | "anysearch"


@dataclass(slots=True)
class ExtractedPage:
    """Full-page content extracted from a URL."""

    url: str
    content: str  # markdown
    title: str | None = None
    images: list[str] = field(default_factory=list)
    favicon: str | None = None
    failed: bool = False
    error: str | None = None
    engine: str = ""


class SearchEngine(ABC):
    """Abstract base for all search engines.

    Subclasses must implement ``search``, ``extract``, and ``crawl``.
    Each engine declares ``domain_strengths`` for the domain router and UI hints.
    """

    name: str = ""
    domain_strengths: list[str] = []

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or ""

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    @abstractmethod
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
        """Search the web and return normalized results."""
        ...

    @abstractmethod
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
        """Extract full page content from one or more URLs."""
        ...

    @abstractmethod
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
        """Graph-based crawl from a base URL."""
        ...

    async def batch_search(
        self,
        queries: list[str],
        *,
        max_results: int = 10,
        domain: str | None = None,
        **kwargs: Any,
    ) -> dict[str, list[SearchHit]]:
        """Search multiple queries. Default: sequential search().

        Engines with native batch support (e.g. AnySearch) override this.
        """
        results: dict[str, list[SearchHit]] = {}
        for q in queries:
            results[q] = await self.search(q, max_results=max_results, domain=domain, **kwargs)
        return results
