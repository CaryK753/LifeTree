"""LifeTree plugins package.

A *plugin* is a Python module placed under ``backend/plugins/`` that follows
the LifeTree plugin contract:

    class Plugin:
        @staticmethod
        def manifest() -> PluginManifest: ...
        @staticmethod
        def fetch(params: dict) -> str | bytes: ...
        # transform() is optional — if omitted, the runner uses the
        # structuring pipeline directly on the fetched text.
        @staticmethod
        def transform(raw: str, llm) -> str: ...

- ``manifest()`` reports the plugin's id / name / description / param
  schema so the frontend can render a parameter form.
- ``fetch(params)`` retrieves raw information (HTTP scrape, RSS pull,
  email fetch, local DB query, …) and returns it as text or bytes.
- ``transform(raw, llm)`` is optional. If present, the plugin owns the
  LLM call (e.g. it can ask the LLM for a custom JSON shape); the
  returned text is then handed to StructuringService. If absent, the
  raw text is handed to StructuringService unchanged, which will run
  its own LLM extraction.

The plugin runner lives in ``app.services.plugins`` and is exposed via
``GET /api/v1/plugins`` and ``POST /api/v1/plugins/{id}/run``.

Example plugin: see ``backend/plugins/sample_rss_plugin.py``.
"""

# Re-export the contract types so plugin authors only need one import:
#   from plugins import PluginManifest, PluginParam, Plugin
from app.services.plugins import Plugin, PluginManifest, PluginParam  # noqa: F401
