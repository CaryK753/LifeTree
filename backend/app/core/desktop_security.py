"""Loopback sidecar authentication middleware."""

from __future__ import annotations

import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_HEADER = b"x-lifetree-desktop-token"


class DesktopTokenMiddleware:
    """Require the per-launch token for every sidecar request except health."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        if len(token) < 32:
            raise ValueError("Desktop sidecar token must contain at least 32 characters")
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._requires_token(scope):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        supplied = headers.get(TOKEN_HEADER, b"").decode("utf-8", errors="ignore")
        if not secrets.compare_digest(supplied, self.token):
            response = JSONResponse({"detail": "Invalid desktop session token"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _requires_token(scope: Scope) -> bool:
        if scope["type"] != "http":
            return False
        if scope.get("method") == "OPTIONS":
            return False
        return scope.get("path") != "/health"


__all__ = ["DesktopTokenMiddleware", "TOKEN_HEADER"]
