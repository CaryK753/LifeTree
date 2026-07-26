"""Plugin API: list available plugins and run one.

    GET  /plugins                — list manifests
    GET  /plugins/{id}           — single manifest
    POST /plugins/{id}/run       — fetch + transform + ingest
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.services.plugin_runner import (
    get_plugin,
    list_plugins,
    manifest_to_dict,
    run_plugin,
)

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginRunRequest(BaseModel):
    params: dict[str, Any] = {}
    title: str | None = None
    skip_llm: bool = False


class PluginRunResponse(BaseModel):
    ok: bool
    source_id: str | None = None
    events_created: int = 0
    metrics_created: int = 0
    assertions_created: int = 0
    relationships_created: int = 0
    extraction_confidence: float | None = None
    notifications_triggered: int = 0
    error: str | None = None
    warning: str | None = None


@router.get("")
def list_all() -> list[dict[str, Any]]:
    return [manifest_to_dict(m) for m in list_plugins()]


@router.get("/{plugin_id}")
def get_one(plugin_id: str) -> dict[str, Any]:
    module = get_plugin(plugin_id)
    if module is None or not hasattr(module, "Plugin"):
        raise HTTPException(404, f"插件不存在: {plugin_id}")
    return manifest_to_dict(module.Plugin.manifest())


@router.post("/{plugin_id}/run", response_model=PluginRunResponse)
def run_one(
    plugin_id: str,
    payload: PluginRunRequest,
    db: Session = Depends(get_db),
) -> PluginRunResponse:
    result = run_plugin(
        plugin_id,
        payload.params,
        title=payload.title,
        skip_llm=payload.skip_llm,
        db=db,
    )
    return PluginRunResponse(**result)
