"""Plugin runner: discovery + execution.

Discovery scans ``backend/plugins/*.py`` (excluding private ``_*`` files
and the ``user_uploaded`` subpackage) for builtin plugins, then scans
``backend/plugins/user_uploaded/*.py`` for user-uploaded plugins. Each
module is imported to read its ``Plugin.manifest()``. Execution loads
the plugin, calls ``fetch(params)`` and (optionally) ``transform(raw, llm)``,
then feeds the resulting text into ``StructuringService`` so the rest of
the pipeline (LLM extraction → atoms → graph mirror → notifications) is
reused unchanged.

Run flows:

    POST /api/v1/plugins/{id}/run
        params: { ... plugin-specific ... , "title": "...", "skip_llm": false }
        →
        1. load plugin module by id (builtin first, then user_uploaded)
        2. plugin.fetch(params) → raw text/bytes
        3. (optional) plugin.transform(raw, llm) → refined text
        4. StructuringService.ingest_text(text=..., title=...) → source + atoms

The runner is deliberately synchronous: plugins are I/O bound (HTTP, RSS,
DB) but the work happens inside a request handler. For long-running
plugins we recommend making the call from the frontend with a long
timeout; if you need true background execution, wrap the runner in a
Celery task.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import asdict
from typing import Any

from app.core.logging import get_logger
from app.services.plugins import Plugin, PluginManifest

log = get_logger(__name__)


# ---------- Discovery ----------

_PLUGINS_PACKAGE = "plugins"
_USER_PLUGINS_PACKAGE = "plugins.user_uploaded"


def _scan_package(package_name: str, *, skip: set[str] | None = None) -> list[PluginManifest]:
    """Import every non-private module under ``package_name`` and collect manifests.

    Errors in individual plugins are swallowed (logged) so one broken
    plugin doesn't take down the whole listing.
    """
    skip = skip or set()
    out: list[PluginManifest] = []
    try:
        pkg = importlib.import_module(package_name)
    except ImportError:
        return out

    pkg_path = getattr(pkg, "__path__", None)
    if not pkg_path:
        return out

    for mod_info in pkgutil.iter_modules(pkg_path):
        name = mod_info.name
        if name.startswith("_") or name in skip:
            continue
        full = f"{package_name}.{name}"
        try:
            module = importlib.import_module(full)
        except Exception as exc:  # noqa: BLE001
            log.warning("plugins.load_failed", plugin=full, error=str(exc))
            continue
        plugin_cls = getattr(module, "Plugin", None)
        if plugin_cls is None or not hasattr(plugin_cls, "manifest"):
            log.warning("plugins.missing_contract", plugin=full)
            continue
        try:
            manifest = plugin_cls.manifest()
            # Force the manifest id to match the filename so lookups by id
            # always succeed (plugin authors can't accidentally collide).
            manifest.id = name
            out.append(manifest)
        except Exception as exc:  # noqa: BLE001
            log.warning("plugins.manifest_failed", plugin=full, error=str(exc))
    return out


def list_plugins() -> list[PluginManifest]:
    """Return manifests for every plugin module under ``backend/plugins/``
    (builtin) and ``backend/plugins/user_uploaded/`` (user-uploaded).

    The user_uploaded subpackage is optional — if it doesn't exist (e.g.
    first run before any plugin has been uploaded), it's silently skipped.

    Errors in individual plugins are swallowed (logged) so one broken
    plugin doesn't take down the whole listing.
    """
    # Builtin plugins — skip the user_uploaded subpackage explicitly so
    # we don't double-scan it.
    out = _scan_package(_PLUGINS_PACKAGE, skip={"user_uploaded"})
    # User-uploaded plugins
    out.extend(_scan_package(_USER_PLUGINS_PACKAGE))
    return out


def get_plugin(plugin_id: str) -> Any | None:
    """Import and return the plugin module, or None if missing/broken.

    Tries the builtin package first; on ImportError falls back to the
    user_uploaded subpackage.
    """
    try:
        return importlib.import_module(f"{_PLUGINS_PACKAGE}.{plugin_id}")
    except ImportError:
        try:
            return importlib.import_module(f"{_USER_PLUGINS_PACKAGE}.{plugin_id}")
        except ImportError:
            return None
    except Exception as exc:  # noqa: BLE001
        # Module exists but raised during import (e.g. syntax error at runtime).
        # Log and treat as missing so callers see a 404 instead of a 500.
        log.warning("plugins.import_failed", plugin=plugin_id, error=str(exc))
        return None


def is_user_plugin(plugin_id: str) -> bool:
    """Return True if ``plugin_id`` resolves to a module under user_uploaded."""
    try:
        importlib.import_module(f"{_PLUGINS_PACKAGE}.{plugin_id}")
        return False
    except ImportError:
        try:
            importlib.import_module(f"{_USER_PLUGINS_PACKAGE}.{plugin_id}")
            return True
        except ImportError:
            return False
    except Exception:  # noqa: BLE001
        return False


# ---------- Execution ----------


def run_plugin(
    plugin_id: str,
    params: dict[str, Any],
    *,
    title: str | None = None,
    skip_llm: bool = False,
    db=None,
) -> dict[str, Any]:
    """Run a plugin end-to-end.

    Returns a dict with keys:
        - ok: bool
        - source_id: str | None
        - events_created, metrics_created, assertions_created,
          relationships_created, notifications_triggered: int
        - extraction_confidence: float | None
        - error: str | None
        - warning: str | None   (e.g. "transform() failed, used raw text")
    """
    out: dict[str, Any] = {
        "ok": False,
        "source_id": None,
        "events_created": 0,
        "metrics_created": 0,
        "assertions_created": 0,
        "relationships_created": 0,
        "extraction_confidence": None,
        "notifications_triggered": 0,
        "error": None,
        "warning": None,
    }

    module = get_plugin(plugin_id)
    if module is None or not hasattr(module, "Plugin"):
        out["error"] = f"插件不存在或未实现 Plugin 类: {plugin_id}"
        return out

    plugin: Plugin = module.Plugin

    # If this is a user-uploaded plugin, enforce the DB enabled flag.
    if is_user_plugin(plugin_id):
        if db is None:
            from app.db.postgres import SessionLocal
            check_db = SessionLocal()
            try:
                enabled = _user_plugin_enabled(plugin_id, check_db)
            finally:
                check_db.close()
        else:
            enabled = _user_plugin_enabled(plugin_id, db)
        if enabled is False:
            out["error"] = f"插件已禁用: {plugin_id}"
            return out

    try:
        manifest = plugin.manifest()
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"读取插件 manifest 失败: {exc}"
        return out

    # Validate required params
    for p in manifest.params:
        if p.required and (p.name not in params or params[p.name] in (None, "")):
            out["error"] = f"缺少必填参数: {p.label} ({p.name})"
            return out

    # 1. fetch
    try:
        raw = plugin.fetch(params)
    except Exception as exc:  # noqa: BLE001
        log.error("plugins.fetch_failed", plugin=plugin_id, error=str(exc))
        out["error"] = f"插件 fetch 失败: {exc}"
        return out

    if isinstance(raw, bytes):
        raw_text = raw.decode("utf-8", errors="replace")
    else:
        raw_text = str(raw)

    if not raw_text.strip():
        out["error"] = "插件没有返回任何内容"
        return out

    # 2. transform (optional)
    text = raw_text
    if hasattr(plugin, "transform"):
        try:
            from app.llm.client import get_chat_model, get_instructor_sync

            # Make the LLM client available to the plugin; many plugins
            # will call instructor directly.
            ctx = type("LLMContext", (), {
                "chat_model": get_chat_model(),
                "instructor": get_instructor_sync(),
            })()
            transformed = plugin.transform(raw_text, ctx)
            if isinstance(transformed, str) and transformed.strip():
                text = transformed
        except Exception as exc:  # noqa: BLE001
            log.warning("plugins.transform_failed", plugin=plugin_id, error=str(exc))
            out["warning"] = f"插件 transform 失败，已回退使用原始文本: {exc}"

    final_title = title or f"[{manifest.name}] {params.get('title', '')}".strip()

    # 3. ingest through structuring pipeline
    if db is None:
        from app.db.postgres import SessionLocal
        db = SessionLocal()
        try:
            return _ingest_and_pack(db, text, final_title, skip_llm, out)
        finally:
            db.close()
    return _ingest_and_pack(db, text, final_title, skip_llm, out)


def _user_plugin_enabled(plugin_id: str, db) -> bool | None:
    """Look up the enabled flag for a user plugin. Returns None if row missing."""
    from sqlalchemy import select

    from app.models.user_plugin import UserPlugin

    row = db.scalar(
        select(UserPlugin).where(
            UserPlugin.plugin_id == plugin_id,
            UserPlugin.deleted_at.is_(None),
        )
    )
    if row is None:
        return None
    return bool(row.enabled)


def _ingest_and_pack(db, text: str, title: str, skip_llm: bool, out: dict) -> dict:
    from sqlalchemy import select

    from app.models.event import Event
    from app.models.user import UserProfile
    from app.services.notification import NotificationService
    from app.services.reasoning.risk_propagation import RiskPropagationEngine
    from app.services.structuring import StructuringService

    try:
        service = StructuringService(db)
        source, extraction = service.ingest_text(
            text=text,
            title=title or "Untitled",
            source_kind="public",
            skip_llm=skip_llm,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("plugins.ingest_failed", error=str(exc))
        out["error"] = f"入库失败: {exc}"
        return out

    out["source_id"] = source.id

    if extraction is None:
        out["ok"] = True
        return out

    out["events_created"] = len(extraction.events)
    out["metrics_created"] = len(extraction.metrics)
    out["assertions_created"] = len(extraction.assertions)
    out["relationships_created"] = len(extraction.relationships)
    out["extraction_confidence"] = extraction.overall_confidence

    notifications = 0
    propagation = RiskPropagationEngine(db)
    notif_service = NotificationService(db)
    high_risk_events = list(
        db.scalars(
            select(Event)
            .where(Event.source_id == source.id, Event.risk_flag_level == "high")
        )
    )
    for ev in high_risk_events:
        for a in propagation.propagate_from_event(ev):
            user = a.user if hasattr(a, "user") else None
            if user is None:
                user = db.get(UserProfile, a.user_id)
            if user is None:
                continue
            notif_service.notify(
                user,
                title=f"High-risk event: {ev.subject} {ev.action}",
                body=getattr(ev, "summary", "") or f"Risk level {ev.risk_flag_level} detected.",
                severity="critical" if ev.risk_flag_urgency == "urgent" else "warning",
                event_id=ev.id,
                risk_factor_id=None,
                impact_summary={
                    "goal_id": a.goal_id,
                    "overall_risk": a.overall_risk,
                    "factor_scores": a.factor_scores,
                },
            )
            notifications += 1

    out["notifications_triggered"] = notifications
    out["ok"] = True
    return out


# ---------- Serialization ----------


def manifest_to_dict(m: PluginManifest) -> dict[str, Any]:
    d = asdict(m)
    return d
