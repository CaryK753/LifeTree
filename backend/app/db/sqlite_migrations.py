"""Lightweight schema migration runner for the local SQLite database.

The server side uses Alembic to manage PostgreSQL schema. The local desktop
runtime ships a single SQLite file, so a full migration framework is
overkill; instead we keep an ordered tuple of migration functions and apply
the pending ones at startup, each in its own transaction.

Versioning contract:
- ``PRAGMA user_version`` stores the current schema version (0 = fresh).
- ``LATEST_SCHEMA_VERSION`` is the highest version this build can apply.
- A database with ``user_version > LATEST_SCHEMA_VERSION`` (user downgraded
  the app) is rejected to avoid writing to an unknown schema.
- Each migration runs in its own transaction; on failure that transaction
  rolls back and the exception propagates, leaving the DB at the last
  successful version with data intact.
"""

from __future__ import annotations

from collections import namedtuple
from collections.abc import Callable
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

SchemaMigration = namedtuple("SchemaMigration", ["version", "description", "apply"])
MigrationFn = Callable[["Connection"], None]


def apply_v1_initial_schema(conn: Connection) -> None:
    """v0 -> v1: create the full ORM + local-graph schema.

    SQLAlchemy ``create_all`` only creates missing tables, so this is safe
    to re-run on a database already at v1 (idempotent).
    """
    import app.models  # noqa: F401  register ORM metadata on Base
    from app.db.postgres import Base
    from app.models.local_graph import LocalGraphBase

    Base.metadata.create_all(conn)
    LocalGraphBase.metadata.create_all(conn)


MIGRATIONS: tuple[SchemaMigration, ...] = (
    SchemaMigration(1, "initial_schema", apply_v1_initial_schema),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version if MIGRATIONS else 0


def get_schema_version(conn: Connection) -> int:
    """Read ``PRAGMA user_version`` as an int."""
    return int(conn.execute(text("PRAGMA user_version")).scalar_one())


def run_pending_migrations(engine: Engine) -> list[int]:
    """Apply all pending schema migrations in version order.

    Each migration runs in a fresh ``engine.begin()`` transaction so a
    failure rolls back only that step. ``user_version`` is bumped inside
    the same transaction as the DDL, right before commit.

    Returns the list of newly applied version numbers (empty if up-to-date).

    Raises ``RuntimeError`` if the database is newer than this build
    supports (downgrade protection).
    """
    with engine.connect() as conn:
        current = get_schema_version(conn)

    if current > LATEST_SCHEMA_VERSION:
        raise RuntimeError(
            f"Local database schema version {current} is newer than this "
            f"build supports ({LATEST_SCHEMA_VERSION}). Upgrade the LifeTree "
            "desktop app to open this database."
        )

    applied: list[int] = []
    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        with engine.begin() as conn:
            migration.apply(conn)
            conn.execute(text(f"PRAGMA user_version = {migration.version}"))
        applied.append(migration.version)
    return applied


__all__ = [
    "LATEST_SCHEMA_VERSION",
    "MIGRATIONS",
    "SchemaMigration",
    "apply_v1_initial_schema",
    "get_schema_version",
    "run_pending_migrations",
]
