"""Create all tables directly via Base.metadata.create_all().

This is the fastest path to a working schema for first-time setup.
For ongoing schema evolution, use Alembic (`alembic revision --autogenerate`).

Run via:  python scripts/init_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.db.postgres import Base, engine  # noqa: E402
from app import models  # noqa: F401, E402

log = get_logger(__name__)


def init_db() -> None:
    configure_logging("INFO")

    # Enable pgvector extension (idempotent)
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()

    Base.metadata.create_all(bind=engine)
    log.info("init_db.complete", tables=list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    init_db()
