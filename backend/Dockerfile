# syntax=docker/dockerfile:1.6
# LifeTree backend image — serves the FastAPI app by default.
# Worker / beat run via command override in docker-compose.yml.

# ---------- Stage 1: builder ----------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for native extensions (psycopg, numpy, scipy, pgvector, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project metadata + source. Editable install needs the package on disk.
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY plugins ./plugins
COPY scripts ./scripts

RUN pip install --upgrade pip setuptools wheel && \
    pip install -e .

# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime libs: libpq5 for psycopg, libgomp1 for numpy/scipy, curl for healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security.
RUN groupadd --system appuser && \
    useradd --system --gid appuser --home-dir /app --shell /usr/sbin/nologin appuser

WORKDIR /app

# Copy installed packages from builder.
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source.
COPY --chown=appuser:appuser pyproject.toml ./
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser plugins ./plugins
COPY --chown=appuser:appuser scripts ./scripts

# Entrypoint runs Alembic migrations before handing off to CMD.
COPY --chown=appuser:appuser scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
