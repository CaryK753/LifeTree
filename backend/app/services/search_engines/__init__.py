"""Search engine factory and public API.

Provides ``get_engine`` to create engine instances by name, and
``get_default_search_engine`` to read the configured default.
"""

from __future__ import annotations

from app.services.search_engines.base import ExtractedPage, SearchEngine, SearchHit
from app.services.search_engines.bocha_engine import BochaEngine
from app.services.search_engines.domain_router import (
    detect_domains,
    recommend_engines,
)
from app.services.search_engines.exa_engine import ExaEngine
from app.services.search_engines.tavily_engine import TavilyEngine
from app.services.search_engines.anysearch_engine import AnySearchEngine

_ENGINE_CLASSES: dict[str, type[SearchEngine]] = {
    "tavily": TavilyEngine,
    "exa": ExaEngine,
    "bocha": BochaEngine,
    "anysearch": AnySearchEngine,
}

ALL_ENGINE_NAMES = list(_ENGINE_CLASSES.keys())


def get_engine(
    engine: str | None = None,
    *,
    api_key: str | None = None,
) -> SearchEngine:
    """Create a search engine instance.

    Args:
        engine: Engine name ("tavily"/"exa"/"bocha"/"anysearch").
                None uses the configured default.
        api_key: API key for the engine. If None, the engine will have
                 ``available=False`` until a key is provided.

    Returns:
        A concrete SearchEngine instance.
    """
    name = engine or get_default_search_engine()
    cls = _ENGINE_CLASSES.get(name, TavilyEngine)
    return cls(api_key=api_key)


def get_default_search_engine() -> str:
    """Read the default search engine from registry config."""
    try:
        from app.llm.registry import get_search_default_engine

        return get_search_default_engine() or "tavily"
    except Exception:
        return "tavily"


def get_engine_domain_strengths(engine: str) -> list[str]:
    """Return the domain strengths declared by an engine."""
    cls = _ENGINE_CLASSES.get(engine)
    return list(cls.domain_strengths) if cls else []


__all__ = [
    "ALL_ENGINE_NAMES",
    "ExtractedPage",
    "SearchEngine",
    "SearchHit",
    "detect_domains",
    "get_default_search_engine",
    "get_engine",
    "get_engine_domain_strengths",
    "recommend_engines",
]
