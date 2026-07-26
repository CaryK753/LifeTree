"""PostgreSQL engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from collections.abc import Generator, Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.postgres_dsn,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.app_debug and settings.app_env == "development",
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


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
