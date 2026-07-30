from pathlib import Path

from app.core.config import Settings
from app.core.local_storage import prepare_local_storage, resolve_local_storage_paths


def test_server_storage_mode_remains_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.lifetree_storage_mode == "server"
    assert settings.lifetree_data_dir is None


def test_portable_local_storage_layout(tmp_path: Path) -> None:
    paths = resolve_local_storage_paths(tmp_path / "LifeTree Data")

    assert paths.data == (tmp_path / "LifeTree Data").resolve()
    assert paths.config == paths.data / "config"
    assert paths.cache == paths.data / "cache"


def test_prepare_local_storage_is_idempotent(tmp_path: Path) -> None:
    first = prepare_local_storage(tmp_path / "runtime")
    second = prepare_local_storage(tmp_path / "runtime")

    assert first == second
    for path in (
        first.data,
        first.config,
        first.cache,
        first.objects,
        first.plugins,
        first.backups,
    ):
        assert path.is_dir()
