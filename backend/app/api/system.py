"""System components endpoint — read-only status of docker-launched services.

Reports the connection / availability of the backing services (Postgres,
Neo4j, Redis, MinIO) the app depends on. The settings page renders these as
a read-only "系统组件" card so the user can see at a glance which services
are up and which addresses the backend is talking to.

All info is read-only; no secrets beyond what is already exposed in the
public config (host/port). Passwords / keys are masked.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/system", tags=["system"])


class SystemComponentView(BaseModel):
    """One row in the system-components table."""

    key: str  # short machine id, e.g. "postgres"
    name: str  # display name, e.g. "PostgreSQL"
    kind: str  # "database" | "graph" | "cache" | "storage"
    endpoint: str  # host:port or URL the backend connects to
    available: bool
    enabled: bool  # whether the app is wired to use it (always true for MVP)
    detail: str | None = None  # version / extra info on success
    error: str | None = None  # short error message on failure


class SystemComponentsView(BaseModel):
    components: list[SystemComponentView]


def _check_postgres() -> tuple[bool, str | None, str | None]:
    try:
        from app.db.postgres import engine
        from sqlalchemy import text

        with engine.connect() as conn:
            res = conn.execute(text("SELECT version()")).scalar_one_or_none()
            version = (res or "").split(",")[0] if res else None
            return True, version, None
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)[:200]


def _check_neo4j() -> tuple[bool, str | None, str | None]:
    try:
        from app.db.neo4j import get_neo4j_driver

        driver = get_neo4j_driver()
        driver.verify_connectivity()
        info = driver.get_server_info()
        version = getattr(info, "agent", None) or getattr(info, "version", None)
        return True, version, None
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)[:200]


def _check_redis() -> tuple[bool, str | None, str | None]:
    try:
        from app.db.redis import get_redis

        client = get_redis()
        pong = client.ping()
        ver = client.info().get("redis_version") if pong else None
        return bool(pong), f"redis {ver}" if ver else None, None
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)[:200]


def _check_minio() -> tuple[bool, str | None, str | None]:
    try:
        from app.db.minio import get_minio_client

        client = get_minio_client()
        # list_buckets is the cheapest health probe; returns a list.
        buckets = client.list_buckets()
        return True, f"{len(buckets)} bucket(s)", None
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)[:200]


@router.get("/components", response_model=SystemComponentsView)
async def get_system_components() -> SystemComponentsView:
    """Return the status of all backing services.

    Each probe runs in a short try/except so a single broken service does
    not take down the whole endpoint. Probes are run sequentially — there
    are only four and each has its own short timeout at the driver level.
    """
    s = get_settings()

    pg_ok, pg_detail, pg_err = _check_postgres()
    neo_ok, neo_detail, neo_err = _check_neo4j()
    redis_ok, redis_detail, redis_err = _check_redis()
    minio_ok, minio_detail, minio_err = _check_minio()

    components = [
        SystemComponentView(
            key="postgres",
            name="PostgreSQL",
            kind="database",
            endpoint=f"{s.postgres_host}:{s.postgres_port}/{s.postgres_db}",
            available=pg_ok,
            enabled=True,
            detail=pg_detail,
            error=pg_err,
        ),
        SystemComponentView(
            key="neo4j",
            name="Neo4j",
            kind="graph",
            endpoint=s.neo4j_uri,
            available=neo_ok,
            enabled=True,
            detail=neo_detail,
            error=neo_err,
        ),
        SystemComponentView(
            key="redis",
            name="Redis",
            kind="cache",
            endpoint=f"{s.redis_host}:{s.redis_port}",
            available=redis_ok,
            enabled=True,
            detail=redis_detail,
            error=redis_err,
        ),
        SystemComponentView(
            key="minio",
            name="MinIO",
            kind="storage",
            endpoint=s.minio_endpoint,
            available=minio_ok,
            enabled=True,
            detail=minio_detail,
            error=minio_err,
        ),
    ]
    return SystemComponentsView(components=components)
