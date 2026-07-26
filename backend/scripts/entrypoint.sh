#!/bin/sh
# LifeTree backend entrypoint — runs Alembic migrations before starting the app.
#
# Ensures the database schema is up to date on every container start, so both
# first-time deployments and version upgrades are handled automatically.
# Worker / beat services also run this (via command override in compose) to
# ensure their DB schema is current before consuming jobs.
set -e

# Ensure the pgvector extension exists before running migrations.
# Alembic migrations create it via `CREATE EXTENSION IF NOT EXISTS`, but
# we run it here as a safety net — fresh databases without the extension
# will fail on the first `VECTOR(1536)` column. Using Python (not psql)
# because the slim image doesn't ship a psql client.
echo "[entrypoint] Ensuring pgvector extension..."
python -c "
from app.core.config import settings
from sqlalchemy import create_engine, text
engine = create_engine(settings.postgres_dsn)
with engine.connect() as conn:
    conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector;'))
    conn.commit()
print('[entrypoint] pgvector extension OK')
" || echo "[entrypoint] Failed to create pgvector extension — Alembic will retry"

echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head

# Ensure the user-uploaded plugins directory exists with an __init__.py
# marker. In Docker this is created by the Dockerfile, but a fresh
# backend_plugins volume mounted over /app/plugins/user_uploaded can
# hide the baked-in __init__.py; recreate it here so plugin discovery
# works on first boot.
USER_PLUGINS_DIR="/app/plugins/user_uploaded"
if [ ! -f "$USER_PLUGINS_DIR/__init__.py" ]; then
  mkdir -p "$USER_PLUGINS_DIR"
  touch "$USER_PLUGINS_DIR/__init__.py"
fi

echo "[entrypoint] Starting: $@"
exec "$@"
