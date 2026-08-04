from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  register ORM metadata on Base
from app.db.sqlite_migrations import (
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    SchemaMigration,
    apply_v1_initial_schema,
    get_schema_version,
    run_pending_migrations,
)


def _engine_for(db_path: str | Path):
    """Build a file-backed SQLite engine matching the local runtime."""
    return create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_fresh_database_migrates_to_latest(tmp_path: Path) -> None:
    engine = _engine_for(tmp_path / "fresh.sqlite3")

    applied = run_pending_migrations(engine)

    assert applied == [m.version for m in MIGRATIONS]
    with engine.connect() as conn:
        assert get_schema_version(conn) == LATEST_SCHEMA_VERSION
        table_names = set(inspect(conn).get_table_names())
    # Core ORM tables exist alongside the local-graph projection.
    assert "goals" in table_names
    assert "events" in table_names
    assert "local_graph_nodes" in table_names
    assert "local_graph_edges" in table_names


def test_existing_v1_database_skips_redundant_migration(tmp_path: Path) -> None:
    """A database already at v1 must not be touched by the v1 migration."""
    engine = _engine_for(tmp_path / "existing.sqlite3")

    # First boot creates the v1 schema and stamps user_version=1.
    run_pending_migrations(engine)
    inspector = inspect(engine.connect())
    tables_after_first_boot = set(inspector.get_table_names())

    applied = run_pending_migrations(engine)

    assert applied == []
    with engine.connect() as conn:
        assert get_schema_version(conn) == 1
        assert set(inspect(conn).get_table_names()) == tables_after_first_boot


def test_migration_failure_rolls_back_and_keeps_old_version(tmp_path: Path) -> None:
    engine = _engine_for(tmp_path / "failing.sqlite3")

    def _boom(conn) -> None:
        raise RuntimeError("simulated migration failure")

    failing_registry = MIGRATIONS + (
        SchemaMigration(LATEST_SCHEMA_VERSION + 1, "boom", _boom),
    )
    # Monkeypatch the registry used by run_pending_migrations.
    import app.db.sqlite_migrations as mod

    original = mod.MIGRATIONS
    mod.MIGRATIONS = failing_registry
    try:
        with pytest.raises(RuntimeError, match="simulated migration failure"):
            run_pending_migrations(engine)
    finally:
        mod.MIGRATIONS = original

    with engine.connect() as conn:
        assert get_schema_version(conn) == LATEST_SCHEMA_VERSION
        # Tables from the successful v1 migration survived the rolled-back step.
        assert "goals" in set(inspect(conn).get_table_names())


def test_downgrade_is_rejected(tmp_path: Path) -> None:
    engine = _engine_for(tmp_path / "downgraded.sqlite3")
    with engine.begin() as conn:
        conn.execute(text(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 5}"))

    with pytest.raises(RuntimeError, match="newer than this build supports"):
        run_pending_migrations(engine)


def test_v1_initial_schema_is_idempotent(tmp_path: Path) -> None:
    engine = _engine_for(tmp_path / "idempotent.sqlite3")

    with engine.begin() as conn:
        apply_v1_initial_schema(conn)
    # Re-running must not raise (defends against crash-retry re-applying a step).
    with engine.begin() as conn:
        apply_v1_initial_schema(conn)

    with engine.connect() as conn:
        table_names = set(inspect(conn).get_table_names())
    assert {"goals", "local_graph_nodes"} <= table_names
