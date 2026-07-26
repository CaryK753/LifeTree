"""Plugin API: list available plugins, upload user plugins, and run one.

    GET    /plugins                     — list manifests (builtin + user)
    GET    /plugins/{id}                — single manifest
    POST   /plugins/upload              — upload a user plugin (.py)
    DELETE /plugins/{id}                — delete a user plugin (builtin plugins cannot be deleted)
    PATCH  /plugins/{id}/enabled        — toggle a user plugin's enabled flag
    POST   /plugins/{id}/run            — fetch + transform + ingest
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.services.plugin_runner import (
    get_plugin,
    list_plugins,
    manifest_to_dict,
    run_plugin,
)
from app.services.plugin_upload import (
    delete_plugin as delete_user_plugin,
)
from app.services.plugin_upload import (
    list_user_plugins,
    set_plugin_enabled,
    store_plugin,
)

log = get_logger(__name__)
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


class PluginEnableRequest(BaseModel):
    enabled: bool


class PluginUploadResponse(BaseModel):
    ok: bool
    plugin_id: str | None = None
    manifest: dict[str, Any] | None = None
    source: str = "user"
    warnings: list[str] = []
    error: str | None = None


@router.get("")
def list_all(user: CurrentUser, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Merge builtin plugin manifests with user-uploaded ones.

    Builtin entries are tagged ``source="builtin", enabled=true,
    can_delete=false``. User entries are tagged ``source="user"`` with
    their DB-enabled state and ``can_delete=true``.
    """
    out: list[dict[str, Any]] = []

    # DB rows for user plugins — used both for tagging and for surfacing
    # user plugins whose file is missing/broken on disk. Filter by user.
    uid = None if user.role == "admin" else user.id
    user_rows = {r.plugin_id: r for r in list_user_plugins(db, user_id=uid)}
    seen_user_ids: set[str] = set()

    # list_plugins() scans both builtin and user_uploaded packages.
    for m in list_plugins():
        d = manifest_to_dict(m)
        if m.id in user_rows:
            row = user_rows[m.id]
            seen_user_ids.add(m.id)
            d["source"] = "user"
            d["enabled"] = row.enabled
            d["can_delete"] = True
            d["uploaded_at"] = (
                row.created_at.isoformat() if row.created_at else None
            )
        else:
            d["source"] = "builtin"
            d["enabled"] = True
            d["can_delete"] = False
        out.append(d)

    # Surface user plugin rows whose file failed to import / was deleted,
    # so the UI can still show + delete them.
    for plugin_id, row in user_rows.items():
        if plugin_id in seen_user_ids:
            continue
        out.append(
            {
                "id": plugin_id,
                "name": row.original_filename,
                "description": "(plugin failed to import)",
                "version": "",
                "author": "",
                "params": [],
                "tags": [],
                "source": "user",
                "enabled": row.enabled,
                "can_delete": True,
                "uploaded_at": (
                    row.created_at.isoformat() if row.created_at else None
                ),
            }
        )

    return out


@router.get("/{plugin_id}")
def get_one(plugin_id: str) -> dict[str, Any]:
    module = get_plugin(plugin_id)
    if module is None or not hasattr(module, "Plugin"):
        raise HTTPException(404, f"插件不存在: {plugin_id}")
    return manifest_to_dict(module.Plugin.manifest())


@router.post("/upload", response_model=PluginUploadResponse)
async def upload_plugin(
    user: CurrentUser,
    file: UploadFile = File(...),
    overwrite: bool = Form(False),
    db: Session = Depends(get_db),
) -> PluginUploadResponse:
    """Accept a ``.py`` plugin file, validate it, store it on disk + DB."""
    filename = file.filename or ""
    raw = await file.read()
    if not raw:
        return PluginUploadResponse(ok=False, error="空文件")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return PluginUploadResponse(
            ok=False, error=f"文件不是合法 UTF-8 文本: {exc}"
        )
    try:
        row, manifest, warnings = store_plugin(
            filename, text, overwrite=overwrite, db=db, user_id=user.id
        )
    except ValueError as exc:
        log.warning("plugins.upload_rejected", filename=filename, error=str(exc))
        return PluginUploadResponse(ok=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.error("plugins.upload_failed", filename=filename, error=str(exc))
        return PluginUploadResponse(ok=False, error=f"上传失败: {exc}")

    return PluginUploadResponse(
        ok=True,
        plugin_id=row.plugin_id,
        manifest=asdict(manifest),
        source="user",
        warnings=warnings,
    )


@router.delete("/{plugin_id}")
def delete_plugin(
    plugin_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Soft-delete a user-uploaded plugin. Builtin plugins cannot be deleted."""
    try:
        delete_user_plugin(plugin_id, db, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True, "plugin_id": plugin_id}


@router.patch("/{plugin_id}/enabled")
def toggle_enabled(
    plugin_id: str,
    payload: PluginEnableRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Toggle the enabled state of a user-uploaded plugin."""
    try:
        row = set_plugin_enabled(plugin_id, payload.enabled, db, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "ok": True,
        "plugin_id": row.plugin_id,
        "enabled": row.enabled,
    }


@router.post("/{plugin_id}/run", response_model=PluginRunResponse)
def run_one(
    plugin_id: str,
    payload: PluginRunRequest,
    user: CurrentUser,
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
