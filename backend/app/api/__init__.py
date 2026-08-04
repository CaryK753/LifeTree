"""API router aggregation: registers every sub-router under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.actions import router as actions_router
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.backup import router as backup_router
from app.api.changes_summary import router as changes_summary_router
from app.api.chat import router as chat_router
from app.api.crawler import router as crawler_router
from app.api.cross_validation import router as cross_validation_router
from app.api.dashboard import router as dashboard_router
from app.api.decision_tree import router as decision_tree_router
from app.api.events import router as events_router
from app.api.goals import router as goals_router
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.ingest import router as ingest_router
from app.api.lifecycle import router as lifecycle_router
from app.api.memories import router as memories_router
from app.api.model_params import router as model_params_router
from app.api.notifications import router as notifications_router
from app.api.passkey import router as passkey_router
from app.api.plugins import router as plugins_router
from app.api.review import router as review_router
from app.api.risk_discovery import router as risk_discovery_router
from app.api.risk_factors import router as risk_factors_router
from app.api.runtime import router as runtime_router
from app.api.scenarios import router as scenarios_router
from app.api.search import router as search_router
from app.api.settings import router as settings_router
from app.api.source_proposals import router as source_proposals_router
from app.api.sse import router as sse_router
from app.api.system import router as system_router
from app.api.user_runtime import router as user_runtime_router
from app.api.user_skills import router as user_skills_router
from app.api.users import router as users_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(passkey_router)
api_router.include_router(admin_router)
api_router.include_router(model_params_router)
api_router.include_router(users_router)
api_router.include_router(goals_router)
api_router.include_router(actions_router)
api_router.include_router(risk_factors_router)
api_router.include_router(runtime_router)
api_router.include_router(review_router)
api_router.include_router(risk_discovery_router)
api_router.include_router(cross_validation_router)
api_router.include_router(decision_tree_router)
api_router.include_router(search_router)
api_router.include_router(events_router)
api_router.include_router(scenarios_router)
api_router.include_router(source_proposals_router)
api_router.include_router(ingest_router)
api_router.include_router(graph_router)
api_router.include_router(notifications_router)
api_router.include_router(dashboard_router)
api_router.include_router(changes_summary_router)
api_router.include_router(chat_router)
api_router.include_router(crawler_router)
api_router.include_router(sse_router)
api_router.include_router(settings_router)
api_router.include_router(plugins_router)
api_router.include_router(memories_router)
api_router.include_router(system_router)
api_router.include_router(lifecycle_router)
api_router.include_router(user_runtime_router)
api_router.include_router(user_skills_router)
api_router.include_router(backup_router)
api_router.include_router(health_router)


@api_router.get("/_meta", tags=["meta"])
async def meta() -> dict[str, str]:
    return {"name": "LifeTree API", "phase": "MVP"}


def _read_version() -> str:
    """Read the backend version robustly.

    Tries ``importlib.metadata`` first (works in normal Python envs and
    in PyInstaller bundles that include ``--copy-metadata=lifetree-backend``).
    Falls back to parsing ``pyproject.toml`` directly (works even when the
    package metadata is missing, e.g. stale PyInstaller builds).
    """
    try:
        from importlib.metadata import version as _pkg_version
        return _pkg_version("lifetree-backend")
    except Exception:
        pass
    # Fallback: read pyproject.toml next to the backend package.
    try:
        from pathlib import Path
        toml_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
        if toml_path.exists():
            for line in toml_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("version"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "0.0.0"


@api_router.get("/meta/about", tags=["meta"])
async def about() -> dict[str, str]:
    """Return project metadata for the Settings → About panel."""
    return {
        "name": "LifeTree",
        "version": _read_version(),
        "description": "知识图谱驱动的决策支持系统",
        "github_url": "https://github.com/CaryK753/LifeTree",
        "license": "AGPL-3.0",
    }


@api_router.get("/meta/check-update", tags=["meta"])
async def check_update() -> dict[str, str | bool | None]:
    """Check GitHub releases for a newer version.

    Returns ``latest_version``, ``has_update``, and ``release_url``.
    Network failures are non-fatal — the frontend just shows "unable to check".
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.github.com/repos/CaryK753/LifeTree/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
        if resp.status_code != 200:
            return {"has_update": False, "latest_version": None, "release_url": None}
        data = resp.json()
        latest = (data.get("tag_name") or "").lstrip("v")
        current = _read_version()
        # Simple semver compare (major.minor.patch).
        def _parse(v: str):
            parts = []
            for p in (v or "").split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(0)
            return parts[:3]

        cur_parts = _parse(current)
        new_parts = _parse(latest)
        has_update = new_parts > cur_parts
        return {
            "has_update": has_update,
            "latest_version": latest or None,
            "current_version": current,
            "release_url": data.get("html_url"),
        }
    except Exception:  # noqa: BLE001
        return {"has_update": False, "latest_version": None, "release_url": None}
