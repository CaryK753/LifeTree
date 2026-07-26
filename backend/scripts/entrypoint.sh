#!/bin/sh
# LifeTree backend entrypoint — runs Alembic migrations before starting the app.
#
# Ensures the database schema is up to date on every container start, so both
# first-time deployments and version upgrades are handled automatically.
# Worker / beat services also run this (via command override in compose) to
# ensure their DB schema is current before consuming jobs.
set -e

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
