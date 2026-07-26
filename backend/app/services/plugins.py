"""Plugin contract types — see ``plugins/__init__.py`` for the overview."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class PluginParam:
    """One declared parameter that the plugin accepts from the user."""

    name: str
    label: str
    type: str = "string"  # "string" | "number" | "boolean" | "select"
    required: bool = True
    default: Any = None
    help: str = ""
    # For type == "select"
    options: list[dict[str, str]] = field(default_factory=list)


@dataclass
class PluginManifest:
    """Metadata advertised by ``GET /api/v1/plugins``."""

    id: str  # stable unique id, also the module filename (without .py)
    name: str
    description: str
    version: str = "0.1.0"
    author: str = ""
    params: list[PluginParam] = field(default_factory=list)
    # Tags for the UI: e.g. ["news", "policy", "finance"]
    tags: list[str] = field(default_factory=list)


@runtime_checkable
class Plugin(Protocol):
    """Contract every plugin module must satisfy.

    A plugin is just a Python module (file under ``backend/plugins/``)
    exposing a top-level ``Plugin`` class implementing this protocol.
    """

    @staticmethod
    def manifest() -> PluginManifest: ...

    @staticmethod
    def fetch(params: dict[str, Any]) -> str | bytes: ...


__all__ = ["Plugin", "PluginManifest", "PluginParam"]
