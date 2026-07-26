"""Neo4j driver singleton."""

from __future__ import annotations

from functools import lru_cache

from neo4j import Driver, GraphDatabase

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def get_neo4j_driver() -> Driver:
    """Return a singleton Neo4j driver.

    Uses lru_cache so the same driver is reused across requests/workers.
    """
    s = get_settings()
    log.info(
        "neo4j.connecting",
        uri=s.neo4j_uri,
        user=s.neo4j_user,
    )
    return GraphDatabase.driver(
        s.neo4j_uri,
        auth=(s.neo4j_user, s.neo4j_password.get_secret_value()),
    )


def close_neo4j_driver() -> None:
    """Close the cached driver (called on application shutdown)."""
    if get_neo4j_driver.cache_info().currsize > 0:
        get_neo4j_driver().close()
        get_neo4j_driver.cache_clear()
