"""Ownership-aware orchestration for isolated user plugin execution."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.models.user_plugin import UserPlugin
from app.services.plugin_ingest import ingest_and_pack
from app.services.plugin_sandbox import run_user_plugin
from app.services.plugin_upload import user_plugins_root
from app.services.plugins import PluginManifest, PluginParam

log = get_logger(__name__)


def run_isolated_user_plugin(
    plugin_id: str,
    params: dict[str, Any],
    *,
    title: str | None,
    skip_llm: bool,
    db,
    user_id: str | None,
    out: dict[str, Any],
) -> dict[str, Any]:
    owns_db = db is None
    if owns_db:
        from app.db.postgres import SessionLocal

        db = SessionLocal()
    try:
        row = db.scalar(select(UserPlugin).where(
            UserPlugin.plugin_id == plugin_id,
            UserPlugin.deleted_at.is_(None),
            UserPlugin.user_id == user_id,
        ))
        if row is None or not row.enabled:
            out["error"] = f"插件不存在、无权访问或已禁用: {plugin_id}"
            return out
        try:
            result = run_user_plugin(user_plugins_root() / f"{plugin_id}.py", params)
            data = result["manifest"]
            manifest = PluginManifest(
                **{
                    **data,
                    "params": [PluginParam(**item) for item in data.get("params", [])],
                }
            )
            for parameter in manifest.params:
                if parameter.required and params.get(parameter.name) in (None, ""):
                    out["error"] = f"缺少必填参数: {parameter.label} ({parameter.name})"
                    return out
            text = str(result.get("text") or "")
            if not text.strip():
                out["error"] = "插件没有返回任何内容"
                return out
            out["warning"] = result.get("warning")
            final_title = title or f"[{manifest.name}] {params.get('title', '')}".strip()
            return ingest_and_pack(db, text, final_title, skip_llm, out)
        except Exception as exc:  # noqa: BLE001
            log.error("plugins.isolated_run_failed", plugin=plugin_id, error=str(exc))
            out["error"] = f"插件隔离进程失败: {exc}"
            return out
    finally:
        if owns_db:
            db.close()
