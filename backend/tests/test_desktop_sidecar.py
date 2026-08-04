"""End-to-end test: the desktop sidecar boots and serves local_private mode.

Launches ``app.desktop_sidecar`` as a subprocess (the same entrypoint
PyInstaller bundles) and verifies the full startup chain: argument parsing,
env var setup, app creation, uvicorn startup, schema migration, encryption
init, graph rebuild, health check, and token-gated API access.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from cryptography.fernet import Fernet

TOKEN_HEADER = "x-lifetree-desktop-token"
STARTUP_TIMEOUT = 45.0
HEALTH_POLL = 0.5


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(port: int, timeout: float = STARTUP_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(HEALTH_POLL)
    return False


def _get_json(url: str, token: str | None = None) -> tuple[int, dict | None]:
    headers = {}
    if token:
        headers[TOKEN_HEADER] = token
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as exc:
        return exc.code, None


def _read_first_sse_event(url: str, token: str) -> str:
    request = Request(url, headers={TOKEN_HEADER: token})
    with urlopen(request, timeout=5) as response:
        lines = [response.readline().decode("utf-8") for _ in range(2)]
    return "".join(lines)


def test_sidecar_boots_and_serves_local_private(tmp_path: Path) -> None:
    port = _free_port()
    token = "a" * 64
    env_key = Fernet.generate_key().decode("ascii")
    backend_root = Path(__file__).parents[1]

    env = os.environ.copy()
    env.update(
        {
            "LIFETREE_DESKTOP_TOKEN": token,
            "LIFETREE_LOCAL_ENCRYPTION_KEY": env_key,
            "LIFETREE_DESKTOP_PARENT_PID": str(os.getpid()),
        }
    )

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.desktop_sidecar",
            "--port",
            str(port),
            "--data-dir",
            str(tmp_path / "data"),
        ],
        cwd=backend_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if not _wait_for_health(port):
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            pytest.fail(f"sidecar did not become healthy:\n{stderr}")

        # /health is public (no token required).
        status, body = _get_json(f"http://127.0.0.1:{port}/health")
        assert status == 200
        assert body == {"status": "ok", "version": "0.1.0"}

        # /api/v1/* requires the desktop token.
        status, _ = _get_json(f"http://127.0.0.1:{port}/api/v1/runtime/capabilities")
        assert status == 401

        status, caps = _get_json(
            f"http://127.0.0.1:{port}/api/v1/runtime/capabilities", token=token
        )
        assert status == 200
        assert caps["storage_mode"] == "local"
        assert caps["local_private_ready"] is True
        adapter_statuses = {a["key"]: a["status"] for a in caps["adapters"]}
        assert all(s == "ready" for s in adapter_statuses.values())

        first_event = _read_first_sse_event(f"http://127.0.0.1:{port}/api/v1/sse", token)
        assert first_event.startswith("event: hello\n")
        assert '"user_id"' in first_event
        time.sleep(0.1)
        assert proc.poll() is None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
