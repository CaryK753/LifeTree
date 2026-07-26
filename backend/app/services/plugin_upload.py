"""Plugin upload service: validation, persistence, deletion.

Responsibilities:

- Validate uploaded source: filename pattern, size, AST shape, no
  dangerous imports / calls.
- Persist the file under ``plugins/user_uploaded/{plugin_id}.py`` and
  record metadata in the ``user_plugins`` table.
- Soft-delete: remove the file, mark the DB row deleted, drop the
  cached module from ``sys.modules`` so the runner won't re-pick it up.

This module is the only place that mutates the ``plugins/user_uploaded/``
directory; the runner (``plugin_runner.py``) only reads from it.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.postgres import SessionLocal
from app.models.user_plugin import UserPlugin
from app.services.plugins import PluginManifest

log = get_logger(__name__)


# ---------- Constants ----------

#: Top-level modules a user plugin is NOT allowed to import.
#: Covers subprocess / network / dynamic-exec primitives that could
#: escape the sandbox or load arbitrary native code.
IMPORT_DENYLIST: frozenset[str] = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "ctypes",
        "socket",
        "multiprocessing",
        "importlib",
        "pickle",
        "marshal",
        "pty",
        "posix",
        "nt",
        "resource",
    }
)

#: Builtins that must never appear as a Call target in user plugins.
DANGEROUS_BUILTINS: frozenset[str] = frozenset(
    {"eval", "exec", "compile", "__import__"}
)

#: Plugin filenames must match this pattern (lowercase snake_case .py).
_FILENAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.py$")

#: Max source size we accept (256 KiB).
MAX_SOURCE_BYTES = 256 * 1024


# ---------- Validation result ----------


@dataclass
class ValidationResult:
    """Outcome of source validation.

    ``ok=True`` means the source passed every check; ``errors`` lists
    human-readable reasons on failure. ``warnings`` is non-fatal.
    """

    ok: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    plugin_id: str = ""
    size_bytes: int = 0
    sha256: str = ""


# ---------- Public API ----------


def user_plugins_root() -> Path:
    """Resolve the user plugins directory, creating it + ``__init__.py`` if missing.

    The directory is configurable via ``settings.user_plugins_dir`` and
    defaults to ``plugins/user_uploaded`` relative to the backend CWD.
    The ``__init__.py`` is required so the directory is importable as a
    Python subpackage of ``plugins``.
    """
    settings = get_settings()
    root = Path(settings.user_plugins_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    init_path = root / "__init__.py"
    if not init_path.exists():
        init_path.write_text(
            '"""Auto-generated package marker for user-uploaded plugins."""\n',
            encoding="utf-8",
        )
    return root


def validate_plugin_source(filename: str, source: str | bytes) -> ValidationResult:
    """Run all static checks against an uploaded plugin file.

    Returns a :class:`ValidationResult`; on success ``plugin_id`` is the
    filename stem (without ``.py``).
    """
    result = ValidationResult()

    # 1. Filename pattern
    if not filename or not _FILENAME_RE.match(filename):
        result.errors.append(
            f"文件名非法：必须匹配 {_FILENAME_RE.pattern}（小写字母开头，仅含小写字母/数字/下划线，.py 结尾）"
        )
        return result

    plugin_id = filename[:-3]  # strip .py
    result.plugin_id = plugin_id

    # 2. Size limit
    if isinstance(source, str):
        raw_bytes = source.encode("utf-8")
    else:
        raw_bytes = source
    result.size_bytes = len(raw_bytes)
    if result.size_bytes > MAX_SOURCE_BYTES:
        result.errors.append(
            f"文件过大：{result.size_bytes} bytes，超过上限 {MAX_SOURCE_BYTES} bytes (256 KiB)"
        )
        return result

    result.sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # Decode to text for AST parsing
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        result.errors.append(f"文件不是合法 UTF-8 文本: {exc}")
        return result

    # 3. AST parse
    try:
        tree = ast.parse(text, filename=filename)
    except SyntaxError as exc:
        result.errors.append(f"语法错误 (line {exc.lineno}): {exc.msg}")
        return result

    # 4. Top-level `class Plugin:` with `manifest` and `fetch` static methods
    plugin_cls = _find_plugin_class(tree)
    if plugin_cls is None:
        result.errors.append(
            "未找到顶层 `class Plugin:` 类定义（必须直接定义在模块顶层）"
        )
    else:
        missing = _missing_static_methods(plugin_cls, {"manifest", "fetch"})
        if missing:
            result.errors.append(
                f"Plugin 类缺少 @staticmethod: {', '.join(sorted(missing))}"
            )

    # 5. No denylist imports
    for mod in _iter_imported_top_level_modules(tree):
        if mod in IMPORT_DENYLIST:
            result.errors.append(f"禁止导入模块: {mod}")

    # 6. No calls to eval/exec/compile/__import__
    for name in _iter_dangerous_calls(tree):
        result.errors.append(f"禁止调用: {name}()")

    result.ok = not result.errors
    return result


def safe_import_for_validation(plugin_id: str, source: str) -> PluginManifest:
    """Import the source from a temp file and call ``Plugin.manifest()``.

    Raises ``ValueError`` if the module can't be imported or doesn't
    expose a valid ``Plugin`` class with ``manifest()``. The temp file
    is always cleaned up.
    """
    # Write to a temp file with the right module name so the import
    # machinery picks it up cleanly.
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{plugin_id}_", suffix=".py", text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(source)

        module_name = f"_plugin_validate_{plugin_id}"
        spec = importlib.util.spec_from_file_location(module_name, tmp_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"无法为 {plugin_id} 创建模块加载器")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"导入时执行失败: {exc}") from exc

        plugin_cls = getattr(module, "Plugin", None)
        if plugin_cls is None:
            raise ValueError("模块未定义顶层 `Plugin` 类")
        manifest_fn = getattr(plugin_cls, "manifest", None)
        if manifest_fn is None:
            raise ValueError("Plugin 类未实现 manifest()")
        try:
            manifest = manifest_fn()
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"manifest() 调用失败: {exc}") from exc
        if not isinstance(manifest, PluginManifest):
            raise ValueError(
                f"manifest() 返回类型错误: 期望 PluginManifest，实际 {type(manifest).__name__}"
            )
        # Force the id to match the filename stem so runners can find it.
        manifest.id = plugin_id
        return manifest
    finally:
        sys.modules.pop(module_name, None)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def store_plugin(
    filename: str,
    source: str,
    *,
    overwrite: bool,
    db: Session,
    user_id: str | None = None,
) -> tuple[UserPlugin, PluginManifest, list[str]]:
    """Validate, persist, and register an uploaded plugin.

    Returns ``(row, manifest, warnings)``. Raises ``ValueError`` on
    validation failure or when ``overwrite=False`` and a plugin with
    the same id already exists.
    """
    result = validate_plugin_source(filename, source)
    if not result.ok:
        raise ValueError("; ".join(result.errors))

    plugin_id = result.plugin_id

    # Check for existing row owned by the same user
    existing = db.scalar(
        select(UserPlugin).where(
            UserPlugin.plugin_id == plugin_id,
            UserPlugin.deleted_at.is_(None),
            UserPlugin.user_id == user_id if user_id is not None else True,
        )
    )
    if existing is not None and not overwrite:
        raise ValueError(f"插件已存在: {plugin_id}（请勾选“覆盖已存在”以替换）")

    # Import + call manifest() to make sure the plugin actually runs.
    manifest = safe_import_for_validation(plugin_id, source)

    # Persist file to disk
    root = user_plugins_root()
    target = root / f"{plugin_id}.py"
    target.write_text(source, encoding="utf-8")

    # Reload the module under its real path so future imports see the
    # new code immediately (otherwise sys.modules caches the old one).
    real_module = f"plugins.user_uploaded.{plugin_id}"
    sys.modules.pop(real_module, None)

    # Insert / update DB row
    if existing is not None:
        existing.original_filename = filename
        existing.source_sha256 = result.sha256
        existing.size_bytes = result.size_bytes
        existing.enabled = True
        existing.deleted_at = None
        row = existing
    else:
        row = UserPlugin(
            plugin_id=plugin_id,
            original_filename=filename,
            source_sha256=result.sha256,
            size_bytes=result.size_bytes,
            enabled=True,
            user_id=user_id,
        )
        db.add(row)

    db.commit()
    db.refresh(row)

    log.info(
        "plugin_upload.stored",
        plugin_id=plugin_id,
        filename=filename,
        size_bytes=result.size_bytes,
        overwrite=existing is not None,
    )
    return row, manifest, result.warnings


def delete_plugin(plugin_id: str, db: Session, user_id: str | None = None) -> None:
    """Soft-delete a user plugin: remove file, mark DB row, drop module cache."""
    row = db.scalar(
        select(UserPlugin).where(
            UserPlugin.plugin_id == plugin_id,
            UserPlugin.deleted_at.is_(None),
            UserPlugin.user_id == user_id if user_id is not None else True,
        )
    )
    if row is None:
        raise ValueError(f"用户插件不存在: {plugin_id}")

    # Remove the on-disk file
    root = user_plugins_root()
    target = root / f"{plugin_id}.py"
    if target.exists():
        try:
            target.unlink()
        except OSError as exc:
            log.warning("plugin_upload.unlink_failed", plugin_id=plugin_id, error=str(exc))

    # Drop cached module so the runner won't see stale code
    sys.modules.pop(f"plugins.user_uploaded.{plugin_id}", None)

    # Soft-delete DB row
    row.deleted_at = datetime.now(UTC)
    db.commit()

    log.info("plugin_upload.deleted", plugin_id=plugin_id)


def set_plugin_enabled(
    plugin_id: str, enabled: bool, db: Session, user_id: str | None = None
) -> UserPlugin:
    """Toggle the ``enabled`` flag on a user plugin row."""
    row = db.scalar(
        select(UserPlugin).where(
            UserPlugin.plugin_id == plugin_id,
            UserPlugin.deleted_at.is_(None),
            UserPlugin.user_id == user_id if user_id is not None else True,
        )
    )
    if row is None:
        raise ValueError(f"用户插件不存在: {plugin_id}")
    row.enabled = enabled
    db.commit()
    db.refresh(row)
    log.info(
        "plugin_upload.toggled",
        plugin_id=plugin_id,
        enabled=enabled,
    )
    return row


def list_user_plugins(
    db: Session, user_id: str | None = None, include_global: bool = True
) -> list[UserPlugin]:
    """Return non-deleted user plugin rows for the given user.

    When ``user_id`` is set and ``include_global`` is True, also returns
    legacy NULL-user rows (visible to all users).
    """
    stmt = select(UserPlugin).where(UserPlugin.deleted_at.is_(None))
    if user_id is not None:
        if include_global:
            stmt = stmt.where(
                or_(UserPlugin.user_id == user_id, UserPlugin.user_id.is_(None))
            )
        else:
            stmt = stmt.where(UserPlugin.user_id == user_id)
    return list(
        db.scalars(
            stmt.order_by(UserPlugin.created_at.asc())
        )
    )


def get_user_plugin(plugin_id: str, db: Session) -> UserPlugin | None:
    """Return a single non-deleted user plugin row, or None."""
    return db.scalar(
        select(UserPlugin).where(
            UserPlugin.plugin_id == plugin_id,
            UserPlugin.deleted_at.is_(None),
        )
    )


def get_session_local() -> Session:
    """Factory used by the API layer when it needs a session outside request scope.

    (Provided here so callers don't import SessionLocal directly.)
    """
    return SessionLocal()


# ---------- AST helpers ----------


def _find_plugin_class(tree: ast.Module) -> ast.ClassDef | None:
    """Return the top-level ``class Plugin:`` node, or None."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Plugin":
            return node
    return None


def _is_static_method(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        (isinstance(d, ast.Name) and d.id == "staticmethod")
        or (isinstance(d, ast.Attribute) and d.attr == "staticmethod")
        for d in fn.decorator_list
    )


def _missing_static_methods(
    cls: ast.ClassDef, required: set[str]
) -> set[str]:
    """Return the subset of ``required`` static-method names not present."""
    found: set[str] = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in required and _is_static_method(node):
                found.add(node.name)
    return required - found


def _iter_imported_top_level_modules(tree: ast.AST) -> set[str]:
    """Yield top-level module names referenced by Import / ImportFrom."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # node.module is None for relative imports like `from . import x`
            if node.module:
                out.add(node.module.split(".")[0])
            elif node.level and node.level > 0:
                # Relative import — depends on the host package, which for
                # user plugins is `plugins.user_uploaded`. Treat as safe.
                continue
    return out


def _iter_dangerous_calls(tree: ast.AST) -> set[str]:
    """Yield names from DANGEROUS_BUILTINS that appear as a Call target."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in DANGEROUS_BUILTINS:
            out.add(func.id)
        elif isinstance(func, ast.Attribute) and func.attr in DANGEROUS_BUILTINS:
            out.add(func.attr)
    return out
