"""add search engine config keys (exa / bocha / anysearch / default / enabled)

Revision ID: o8b9c0d1e2f3
Revises: n7g8h9i0j1k2
Create Date: 2026-08-07 20:00:00.000000

Seeds the ``app_config`` rows for the multi-source search layer
(§A.3 of the cross-validation / deep-research / multi-source-search spec):

    exa_api_key             ""                     (sensitive — encrypted in local mode)
    bocha_api_key           ""                     (sensitive — encrypted in local mode)
    anysearch_api_key       ""                     (sensitive — encrypted in local mode)
    search_default_engine   "tavily"
    search_engines_enabled  ["tavily"]

The application layer (``app.llm.registry._load_from_db``) already falls
back to these same in-code defaults when a key is absent, so this migration
is **not** required for correctness. It exists to:

  1. Make the schema state explicit for operators inspecting ``app_config``.
  2. Document the canonical default values in one place alongside the code.
  3. Ensure future code changes to the in-code defaults don't silently
     change behaviour for deployments that haven't written the keys yet.

The insert is idempotent — ``ON CONFLICT (key) DO NOTHING`` — so existing
deployments that have already written non-default values (e.g. an admin who
configured Exa via /settings/exa) are never overwritten. The values are
JSON-encoded to match the convention used by ``_set_app_config``.

NOTE on local-storage encryption: the three ``*_api_key`` rows are seeded
as plaintext empty strings (``""``). ``_encode_app_config_value`` only
encrypts non-empty sensitive values, so empty strings are stored as
``""`` regardless of storage mode — exactly what the application would
write on a fresh boot. When the admin later sets a real key via the
settings API, ``_set_app_config`` will re-encrypt it in local mode.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "o8b9c0d1e2f3"
down_revision: Union[str, None] = "n7g8h9i0j1k2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (key, JSON-encoded value). Values mirror the in-code defaults in
# app/llm/registry.py so the DB and the application agree on first boot.
_SEED_ROWS: list[tuple[str, str]] = [
    # Sensitive keys — empty string on first boot (no secret to encrypt).
    ("exa_api_key", "\"\""),
    ("bocha_api_key", "\"\""),
    ("anysearch_api_key", "\"\""),
    # Non-sensitive configuration.
    ("search_default_engine", "\"tavily\""),
    ("search_engines_enabled", "[\"tavily\"]"),
]


def upgrade() -> None:
    # ON CONFLICT DO NOTHING keeps the migration idempotent: deployments
    # that already wrote these keys (e.g. via /settings/search-engine) are
    # left untouched.
    for key, value in _SEED_ROWS:
        op.execute(
            f"""
            INSERT INTO app_config (key, value)
            VALUES ('{key}', '{value}')
            ON CONFLICT (key) DO NOTHING
            """
        )


def downgrade() -> None:
    # Only delete the rows we seeded *if* they still hold the default
    # values — never delete an admin-configured real key. This makes the
    # downgrade safe to run on a deployment that has since configured
    # Exa/Bocha/AnySearch or changed the default engine.
    for key, default_value in _SEED_ROWS:
        op.execute(
            f"""
            DELETE FROM app_config
            WHERE key = '{key}'
              AND value = '{default_value}'
            """
        )
