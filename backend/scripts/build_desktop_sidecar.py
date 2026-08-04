"""Build the FastAPI desktop sidecar for the current Tauri target."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
from pathlib import Path


def _target_triple() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    mapping = {
        ("darwin", "arm64"): "aarch64-apple-darwin",
        ("darwin", "aarch64"): "aarch64-apple-darwin",
        ("darwin", "x86_64"): "x86_64-apple-darwin",
        ("windows", "amd64"): "x86_64-pc-windows-msvc",
        ("windows", "x86_64"): "x86_64-pc-windows-msvc",
    }
    try:
        return mapping[(system, machine)]
    except KeyError as exc:
        raise SystemExit(f"Unsupported desktop target: {system}/{machine}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    try:
        import PyInstaller.__main__
    except ImportError as exc:
        raise SystemExit("Install desktop dependencies with pip install -e '.[desktop]'") from exc

    backend = Path(__file__).resolve().parents[1]
    workspace = backend.parent
    triple = _target_triple()
    output_dir = (args.output_dir or workspace / "desktop/src-tauri/binaries").resolve()
    runtime_dir = workspace / "desktop/src-tauri/resources/sidecar-runtime"
    build_root = backend / "build" / f"sidecar-{triple}"
    dist_dir = build_root / "dist"
    work_dir = build_root / "work"
    spec_dir = build_root / "spec"
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(runtime_dir, ignore_errors=True)

    PyInstaller.__main__.run(
        [
            str(backend / "app/desktop_sidecar.py"),
            "--name=lifetree-sidecar",
            "--onedir",
            "--clean",
            f"--paths={backend}",
            "--collect-submodules=app",
            "--hidden-import=uvicorn.logging",
            "--hidden-import=uvicorn.loops.auto",
            "--hidden-import=uvicorn.protocols.http.auto",
            "--hidden-import=uvicorn.protocols.websockets.auto",
            f"--distpath={dist_dir}",
            f"--workpath={work_dir}",
            f"--specpath={spec_dir}",
            "--noconfirm",
        ]
    )

    suffix = ".exe" if platform.system().lower() == "windows" else ""
    source_dir = dist_dir / "lifetree-sidecar"
    source = source_dir / f"lifetree-sidecar{suffix}"
    destination = output_dir / f"lifetree-sidecar-{triple}{suffix}"
    shutil.copy2(source, destination)
    shutil.copytree(source_dir, runtime_dir)
    if os.name != "nt":
        destination.chmod(0o755)
    print(
        json.dumps(
            {
                "target": triple,
                "sidecar": str(destination),
                "runtime_dir": str(runtime_dir),
                "bytes": destination.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()
