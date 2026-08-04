from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.desktop_security import DesktopTokenMiddleware

TOKEN = "a" * 32


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(DesktopTokenMiddleware, token=TOKEN)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/private")
    def private() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_desktop_token_protects_non_health_routes() -> None:
    with _client() as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/private").status_code == 401
        response = client.get(
            "/api/v1/private",
            headers={"X-LifeTree-Desktop-Token": TOKEN},
        )
        assert response.status_code == 200


def test_desktop_token_allows_cors_preflight() -> None:
    with _client() as client:
        assert client.options("/api/v1/private").status_code != 401


def test_desktop_token_rejects_short_secret() -> None:
    app = FastAPI()
    app.add_middleware(DesktopTokenMiddleware, token="short")

    with pytest.raises(ValueError, match="at least 32"):
        with TestClient(app):
            pass
