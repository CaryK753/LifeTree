"""Restricted FastAPI entrypoint for the bundled desktop sidecar."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import threading
import time


def _stop_when_parent_exits() -> None:
    """Stop an orphaned sidecar after its desktop host exits."""
    raw_parent_pid = os.environ.get("LIFETREE_DESKTOP_PARENT_PID")
    if not raw_parent_pid:
        return
    try:
        parent_pid = int(raw_parent_pid)
    except ValueError:
        return
    if parent_pid <= 1:
        return

    def watch_parent() -> None:
        while os.getppid() == parent_pid:
            time.sleep(2)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=watch_parent, name="desktop-parent-watch", daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    token = os.environ.get("LIFETREE_DESKTOP_TOKEN", "")
    if len(token) < 32:
        parser.error("LIFETREE_DESKTOP_TOKEN must contain at least 32 characters")

    os.environ["LIFETREE_STORAGE_MODE"] = "local"
    os.environ["LIFETREE_USE_MODE"] = "single"
    os.environ["LIFETREE_DATA_DIR"] = str(args.data_dir.expanduser().resolve())
    os.environ["APP_CORS_ORIGINS"] = "tauri://localhost,http://tauri.localhost"
    os.environ.setdefault("APP_ENV", "production")
    os.environ.setdefault("APP_DEBUG", "false")
    _stop_when_parent_exits()

    import uvicorn

    from app.main import create_app

    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
