"""FastAPI application entrypoint.

Wires routers, exception handlers, startup/shutdown lifecycle for DB drivers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import get_settings
from app.core.desktop_security import DesktopTokenMiddleware
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.neo4j import close_neo4j_driver, get_neo4j_driver
from app.db.postgres import initialize_local_database
from app.db.redis import close_redis, get_redis
from app.services.runtime.blob_store import close_blob_store, get_blob_store
from app.services.runtime.job_runner import close_job_runner

settings = get_settings()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("DEBUG" if settings.app_debug else "INFO")
    log.info("app.startup", env=settings.app_env, port=settings.app_backend_port)

    if settings.lifetree_storage_mode == "local":
        initialize_local_database()
        log.info("app.sqlite_ok")
        # 图投影重建放到后台线程，不阻塞 /health 响应
        from app.db.postgres import schedule_graph_rebuild

        schedule_graph_rebuild()
        log.info("app.graph_rebuild_scheduled")
    else:
        # Warm up server-only connections. Failures remain non-fatal so the
        # API can still expose diagnostics during a partial outage.
        try:
            get_neo4j_driver().verify_connectivity()
            log.info("app.neo4j_ok")
        except Exception as exc:  # noqa: BLE001
            log.warning("app.neo4j_unavailable", error=str(exc))

        try:
            get_redis().ping()
            log.info("app.redis_ok")
        except Exception as exc:  # noqa: BLE001
            log.warning("app.redis_unavailable", error=str(exc))

    try:
        get_blob_store().prepare()
        log.info("app.blob_store_ok", mode=settings.lifetree_storage_mode)
    except Exception as exc:  # noqa: BLE001
        log.warning("app.blob_store_unavailable", error=str(exc))

    yield

    log.info("app.shutdown")
    close_neo4j_driver()
    close_redis()
    close_job_runner()
    close_blob_store()


def create_app() -> FastAPI:
    app = FastAPI(
        title="LifeTree API",
        version="0.1.0",
        description="Phase 1 MVP — knowledge-graph-driven decision support",
        lifespan=lifespan,
    )

    desktop_token = settings.lifetree_desktop_token.get_secret_value()
    if desktop_token:
        app.add_middleware(DesktopTokenMiddleware, token=desktop_token)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    return app


app = create_app()
