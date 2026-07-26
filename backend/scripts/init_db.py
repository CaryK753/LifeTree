"""Initialize the database schema via Alembic migrations.

This is a thin wrapper around `alembic upgrade head`. In Docker deployments,
the entrypoint.sh script runs migrations automatically on container start,
so running this script manually is no longer required.

For local development:
    python scripts/init_db.py
    # or equivalently:
    alembic upgrade head

For ongoing schema evolution, generate new migrations with:
    alembic revision --autogenerate -m "description_of_change"
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import configure_logging, get_logger  # noqa: E402

log = get_logger(__name__)


def init_db() -> None:
    configure_logging("INFO")
    log.info("init_db.start", message="Running alembic upgrade head")

    # Ensure pgvector extension exists (idempotent — Alembic migration also
    # creates it, but we run it here as a safety net for fresh databases).
    from app.db.postgres import engine  # noqa: E402
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=False,
    )
    if result.returncode != 0:
        log.error("init_db.failed", returncode=result.returncode)
        sys.exit(result.returncode)
    log.info("init_db.complete")


if __name__ == "__main__":
    init_db()
