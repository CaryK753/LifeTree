"""Process boundary for untrusted user plugin inspection and execution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 2 * 1024 * 1024


def inspect_plugin(path: Path) -> dict[str, Any]:
    return _invoke(path, {"action": "manifest"})["manifest"]


def run_user_plugin(path: Path, params: dict[str, Any]) -> dict[str, Any]:
    return _invoke(path, {"action": "run", "params": params})


def _invoke(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    backend_root = Path(__file__).resolve().parents[2]
    worker = Path(__file__).with_name("plugin_process_worker.py")
    bootstrap = (
        "import runpy,sys;"
        f"sys.path.insert(0,{str(backend_root)!r});"
        f"runpy.run_path({str(worker)!r},run_name='__main__')"
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONIOENCODING": "utf-8",
        "LIFETREE_PLUGIN_PATH": str(path.resolve()),
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", bootstrap],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            cwd=backend_root,
            env=env,
            check=False,
            preexec_fn=_resource_limits if os.name == "posix" else None,
            start_new_session=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"plugin exceeded {TIMEOUT_SECONDS}s timeout") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-1000:]
        raise ValueError(f"plugin process failed: {detail or completed.returncode}")
    if len(completed.stdout.encode()) > MAX_OUTPUT_BYTES:
        raise ValueError("plugin output exceeded 2 MiB")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("plugin returned invalid process output") from exc
    if not isinstance(result, dict):
        raise ValueError("plugin returned invalid result")
    return result


def _resource_limits() -> None:
    import resource

    limits = (
        (resource.RLIMIT_CPU, 15),
        (resource.RLIMIT_AS, 512 * 1024 * 1024),
        (resource.RLIMIT_FSIZE, 2 * 1024 * 1024),
        (resource.RLIMIT_NOFILE, 64),
    )
    for resource_id, desired in limits:
        try:
            _, hard = resource.getrlimit(resource_id)
            soft = desired if hard == resource.RLIM_INFINITY else min(desired, hard)
            resource.setrlimit(resource_id, (soft, hard))
        except (OSError, ValueError):
            # Some macOS/Linux combinations do not support every limit.
            # Timeout, isolated process and output caps remain enforced.
            continue
