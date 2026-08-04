"""Cross-platform directory foundation for the future local runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from filelock import FileLock
from platformdirs import user_cache_path, user_config_path, user_data_path

APP_NAME = "LifeTree"


@dataclass(frozen=True, slots=True)
class LocalStoragePaths:
    data: Path
    database: Path
    config: Path
    cache: Path
    objects: Path
    plugins: Path
    backups: Path
    runtime_lock: Path

    def as_serializable_dict(self) -> dict[str, str]:
        return {name: str(path) for name, path in asdict(self).items()}


def resolve_local_storage_paths(data_dir: Path | str | None = None) -> LocalStoragePaths:
    """Resolve native OS paths, or a portable tree under ``data_dir``."""
    if data_dir is None:
        data = user_data_path(APP_NAME, appauthor=False)
        config = user_config_path(APP_NAME, appauthor=False)
        cache = user_cache_path(APP_NAME, appauthor=False)
    else:
        data = Path(data_dir).expanduser().resolve()
        config = data / "config"
        cache = data / "cache"

    return LocalStoragePaths(
        data=data,
        database=data / "lifetree.sqlite3",
        config=config,
        cache=cache,
        objects=data / "objects",
        plugins=data / "plugins",
        backups=data / "backups",
        runtime_lock=data / "runtime.lock",
    )


def prepare_local_storage(data_dir: Path | str | None = None) -> LocalStoragePaths:
    """Create the local runtime layout under a process-safe preparation lock."""
    paths = resolve_local_storage_paths(data_dir)
    paths.data.mkdir(parents=True, exist_ok=True)
    prepare_lock = FileLock(str(paths.data / ".prepare.lock"), timeout=15)
    with prepare_lock:
        for directory in (
            paths.data,
            paths.config,
            paths.cache,
            paths.objects,
            paths.plugins,
            paths.backups,
        ):
            directory.mkdir(parents=True, exist_ok=True)
    return paths


__all__ = ["LocalStoragePaths", "prepare_local_storage", "resolve_local_storage_paths"]
