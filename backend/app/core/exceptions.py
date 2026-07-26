"""Domain exceptions and FastAPI exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class LifeTreeError(Exception):
    """Base domain error."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "lifetree_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(LifeTreeError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(LifeTreeError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ValidationFailedError(LifeTreeError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_failed"


class LLMNotConfiguredError(LifeTreeError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "llm_not_configured"


class ExternalServiceError(LifeTreeError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "external_service"


async def lifetree_exception_handler(_: Request, exc: LifeTreeError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred.",
                "details": {"type": type(exc).__name__},
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LifeTreeError, lifetree_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
