"""PostgreSQL engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings
from app.core.local_storage import prepare_local_storage

settings = get_settings()


def create_database_engine() -> Engine:
    """Create the configured server or local relational engine."""
    if settings.lifetree_storage_mode == "local":
        paths = prepare_local_storage(settings.lifetree_data_dir)
        local_engine = create_engine(
            f"sqlite+pysqlite:///{paths.database}",
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
            echo=settings.app_debug and settings.app_env == "development",
        )

        @event.listens_for(local_engine, "connect")
        def _configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return local_engine

    return create_engine(
        settings.postgres_dsn,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=settings.app_debug and settings.app_env == "development",
    )


engine = create_database_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def initialize_local_database() -> None:
    """Apply pending SQLite schema migrations.

    The graph projection rebuild is deferred to ``schedule_graph_rebuild()``
    so the sidecar can serve /health immediately.
    """
    if settings.lifetree_storage_mode != "local":
        return
    import app.models  # noqa: F401  register ORM metadata before migrations run
    from app.core.local_encryption import ensure_encryption_available
    from app.db.sqlite_migrations import run_pending_migrations

    ensure_encryption_available()
    run_pending_migrations(engine)


def schedule_graph_rebuild() -> None:
    """Rebuild the graph projection in a background thread.

    Called from the FastAPI lifespan after /health is ready to serve.
    Failures are logged but non-fatal — the projection can be rebuilt
    on demand from the UI.
    """
    if settings.lifetree_storage_mode != "local":
        return
    import asyncio
    import threading

    from app.core.logging import get_logger

    log = get_logger(__name__)

    def _rebuild() -> None:
        try:
            from app.services.runtime.graph_store import EmbeddedGraphStore

            EmbeddedGraphStore().rebuild()
            log.info("app.graph_rebuild_done")
        except Exception as exc:  # noqa: BLE001
            log.warning("app.graph_rebuild_failed", error=str(exc))

    threading.Thread(target=_rebuild, daemon=True, name="graph-rebuild").start()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a per-request Session, closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session() -> Session:
    """Manual session factory for use outside request scope (workers, scripts)."""
    return SessionLocal()
