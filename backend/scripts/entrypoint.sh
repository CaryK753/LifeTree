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

echo "[entrypoint] Starting: $@"
exec "$@"
