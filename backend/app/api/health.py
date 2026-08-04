"""Lightweight component health probes for the dashboard / ops view.

Returns relational, graph, and task/cache reachability without authentication.
Local mode reports unavailable server-only enhancements as unknown instead of
attempting external connections.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


class ComponentHealth(BaseModel):
    """Single-line status for one backing service."""

    status: str  # "ok" | "error" | "unknown"


class ComponentsHealth(BaseModel):
    """Aggregate health snapshot returned by ``GET /health/components``."""

    database: ComponentHealth
    neo4j: ComponentHealth
    redis: ComponentHealth
    timestamp: str


def _check_database() -> str:
    """Return ``"ok"`` if SELECT 1 succeeds, ``"error"`` otherwise."""
    try:
        from sqlalchemy import text

        from app.db.postgres import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("health.database_check_failed", error=str(exc))
        return "error"


def _check_neo4j() -> str:
    """Return ``"ok"`` if Neo4j responds, ``"unknown"`` if not configured,
    ``"error"`` on failure.
    """
    if get_settings().lifetree_storage_mode == "local":
        return "unknown"
    try:
        from app.db.neo4j import get_neo4j_driver

        driver = get_neo4j_driver()
        driver.verify_connectivity()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        # Neo4j is optional in some deployments (e.g. dev without docker);
        # if the driver can't even be constructed we report ``unknown``
        # rather than ``error`` so the dashboard doesn't flash red.
        msg = str(exc).lower()
        if "could not connect" in msg or "connection" in msg or "auth" in msg:
            return "error"
        return "unknown"


def _check_redis() -> str:
    """Return ``"ok"`` if Redis PING succeeds, ``"unknown"`` if not
    configured, ``"error"`` on failure.
    """
    if get_settings().lifetree_storage_mode == "local":
        return "unknown"
    try:
        from app.db.redis import get_redis

        client = get_redis()
        if client.ping():
            return "ok"
        return "error"
    except Exception as exc:  # noqa: BLE001
        log.warning("health.redis_check_failed", error=str(exc))
        return "unknown"


@router.get("/components", response_model=ComponentsHealth)
def get_components_health() -> ComponentsHealth:
    """Return the status of database / Neo4j / Redis.

    Each probe is isolated so one failure never crashes the endpoint.
    No auth required — only reachability info, no topology or secrets.
    """
    db_status = _check_database()
    neo4j_status = _check_neo4j()
    redis_status = _check_redis()

    return ComponentsHealth(
        database=ComponentHealth(status=db_status),
        neo4j=ComponentHealth(status=neo4j_status),
        redis=ComponentHealth(status=redis_status),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
