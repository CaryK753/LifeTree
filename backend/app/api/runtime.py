"""Public runtime capability handshake for desktop sidecar discovery."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(prefix="/runtime", tags=["runtime"])


class RuntimeAdapterView(BaseModel):
    key: str
    backend: str
    status: str


class RuntimeCapabilitiesView(BaseModel):
    protocol_version: int
    storage_mode: str
    local_private_ready: bool
    adapters: list[RuntimeAdapterView]


@router.get("/capabilities", response_model=RuntimeCapabilitiesView)
def get_runtime_capabilities() -> RuntimeCapabilitiesView:
    """Report adapter readiness without exposing endpoints or credentials."""
    return build_runtime_capabilities(get_settings().lifetree_storage_mode)


def build_runtime_capabilities(
    storage_mode: Literal["server", "local"],
) -> RuntimeCapabilitiesView:
    if storage_mode == "local":
        adapters = [
            RuntimeAdapterView(key="database", backend="sqlite_migrations_encrypted", status="ready"),
            RuntimeAdapterView(key="blobs", backend="filesystem", status="ready"),
            RuntimeAdapterView(key="jobs", backend="in_process", status="ready"),
            RuntimeAdapterView(key="graph", backend="sqlite_edges", status="ready"),
            RuntimeAdapterView(key="vectors", backend="in_process_cosine", status="ready"),
            RuntimeAdapterView(
                key="desktop_bundle",
                backend="sidecar_static_ui",
                status="ready",
            ),
        ]
    else:
        adapters = [
            RuntimeAdapterView(key="database", backend="postgresql", status="configured"),
            RuntimeAdapterView(key="blobs", backend="minio", status="configured"),
            RuntimeAdapterView(key="jobs", backend="celery", status="configured"),
            RuntimeAdapterView(key="graph", backend="neo4j", status="configured"),
            RuntimeAdapterView(key="vectors", backend="pgvector", status="configured"),
        ]

    return RuntimeCapabilitiesView(
        protocol_version=1,
        storage_mode=storage_mode,
        local_private_ready=all(adapter.status == "ready" for adapter in adapters),
        adapters=adapters,
    )


__all__ = [
    "RuntimeCapabilitiesView",
    "build_runtime_capabilities",
    "get_runtime_capabilities",
    "router",
]
