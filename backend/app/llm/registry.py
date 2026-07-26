"""Multi-provider / multi-model LLM registry.

Single source of truth for AI model configuration in LifeTree. Replaces the
old single-LLM env-var setup (``LLM_BASE_URL`` / ``LLM_API_KEY`` / etc.) with
a JSON document that can describe many providers and many models, each tagged
with the roles they can serve.

Storage: ``backend/.llm_config.json`` (gitignored). The file is created on
first write; if it does not exist on startup, the registry bootstraps from
legacy ``LLM_*`` env vars so existing deployments keep working.

Schema (v1):

    {
      "version": 1,
      "providers": [
        {
          "id": "p1",
          "name": "OpenAI",
          "protocol": "openai_compatible",  # or "anthropic" | "bailian"
          "base_url": "https://api.openai.com/v1",
          "api_key": "sk-...",
          "created_at": "2026-07-25T..."
        }
      ],
      "models": [
        {
          "id": "m1",
          "provider_id": "p1",
          "name": "gpt-4o-mini",
          "display_name": "GPT-4o mini",
          "capabilities": ["chat", "vision"],
          "created_at": "..."
        }
      ],
      "role_assignments": {
        "chat": "m1",
        "vision": "m1",
        "embedding": "m2",
        "rerank": "m3"
      },
      "tavily_api_key": "tvly-..."
    }

Roles:
    - ``chat`` — AI advisor conversation + structured extraction
    - ``vision`` — image / document analysis
    - ``embedding`` — semantic search vectors
    - ``rerank`` — second-stage reranking for retrieval (Bailian / Cohere style)
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.logging import get_logger

log = get_logger(__name__)


# ---------- Types ----------

Protocol = Literal["openai_compatible", "anthropic", "bailian"]
Role = Literal["chat", "vision", "embedding", "rerank"]
ALL_ROLES: tuple[Role, ...] = ("chat", "vision", "embedding", "rerank")


class Provider(BaseModel):
    """A model supplier (OpenAI, DeepSeek, Anthropic, 阿里云百炼, …)."""

    id: str
    name: str
    protocol: Protocol = "openai_compatible"
    base_url: str | None = None
    api_key: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Model(BaseModel):
    """An individual model exposed by a provider, tagged with capabilities."""

    id: str
    provider_id: str
    name: str  # the model id sent to the API (e.g. "gpt-4o-mini")
    display_name: str  # human label in the UI
    capabilities: list[Role] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LLMConfig(BaseModel):
    """Top-level persisted config."""

    version: int = 1
    providers: list[Provider] = Field(default_factory=list)
    models: list[Model] = Field(default_factory=list)
    role_assignments: dict[Role, str] = Field(default_factory=dict)
    tavily_api_key: str = ""
    # Third-party service keys (kept here so the whole config is one file)
    mineru_api_key: str = ""
    mineru_base_url: str = "https://mineru.net/api/v4"
    # SMTP for risk-warning email notifications (§4.5). Hot-reloadable like
    # the rest of this config — no process restart required.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "notify@lifetree.local"
    smtp_use_tls: bool = True


# ---------- Resolved view (no secrets) ----------

class ProviderView(BaseModel):
    """Provider with masked API key, for API responses."""

    id: str
    name: str
    protocol: Protocol
    base_url: str | None
    api_key_configured: bool
    api_key_preview: str
    created_at: str


class ModelView(BaseModel):
    id: str
    provider_id: str
    name: str
    display_name: str
    capabilities: list[Role]
    created_at: str


class LLMConfigView(BaseModel):
    """Masked view returned by GET /settings — safe to send to the client."""

    version: int
    providers: list[ProviderView]
    models: list[ModelView]
    role_assignments: dict[Role, str]
    tavily_api_key_configured: bool
    tavily_api_key_preview: str
    # Convenience flags: which roles have a working model assigned
    roles_configured: dict[Role, bool]
    # Mineru file-parsing service
    mineru_api_key_configured: bool
    mineru_api_key_preview: str
    mineru_base_url: str
    # SMTP for email notifications (§4.5)
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password_configured: bool
    smtp_password_preview: str
    smtp_from: str
    smtp_use_tls: bool


# ---------- Resolved client target (internal) ----------

class ResolvedModel(BaseModel):
    """A model + its parent provider, ready to construct a client."""

    model: Model
    provider: Provider


# ---------- Storage ----------

CONFIG_PATH = Path(__file__).resolve().parents[2] / ".llm_config.json"

_lock = threading.RLock()


def _mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 4:
        return "••••"
    return "••••" + secret[-4:]


def _bootstrap_from_env() -> LLMConfig:
    """Build an initial config from legacy LLM_* env vars.

    This runs once on first startup if ``.llm_config.json`` doesn't exist.
    The resulting config is *not* written to disk by this function — callers
    decide whether to persist.
    """
    base_url = os.environ.get("LLM_BASE_URL", "").strip() or None
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    provider_name = os.environ.get("LLM_PROVIDER", "openai").strip()
    chat_model = os.environ.get("LLM_MODEL", "").strip()
    embed_model = os.environ.get("LLM_EMBEDDING_MODEL", "").strip()
    tavily_key = os.environ.get("TAVILY_API_KEY", "").strip()

    # Pick a protocol from the legacy provider hint.
    protocol: Protocol = "openai_compatible"
    if provider_name == "anthropic":
        protocol = "anthropic"
    elif provider_name == "bailian":
        protocol = "bailian"

    if not api_key and not base_url and not chat_model:
        # Nothing to bootstrap — return empty config.
        return LLMConfig(tavily_api_key=tavily_key)

    provider = Provider(
        id=f"p_{uuid.uuid4().hex[:8]}",
        name="默认供应商" if not base_url else (base_url.split("//")[-1].split("/")[0]),
        protocol=protocol,
        base_url=base_url,
        api_key=api_key,
    )

    models: list[Model] = []
    role_assignments: dict[Role, str] = {}

    if chat_model:
        m = Model(
            id=f"m_{uuid.uuid4().hex[:8]}",
            provider_id=provider.id,
            name=chat_model,
            display_name=chat_model,
            capabilities=["chat"],
        )
        models.append(m)
        role_assignments["chat"] = m.id

    if embed_model and embed_model != chat_model:
        m = Model(
            id=f"m_{uuid.uuid4().hex[:8]}",
            provider_id=provider.id,
            name=embed_model,
            display_name=embed_model,
            capabilities=["embedding"],
        )
        models.append(m)
        role_assignments["embedding"] = m.id
    elif embed_model == chat_model and chat_model:
        # Same model serves both roles.
        models[0].capabilities.append("embedding")
        role_assignments["embedding"] = models[0].id

    return LLMConfig(
        providers=[provider] if (api_key or base_url) else [],
        models=models,
        role_assignments=role_assignments,
        tavily_api_key=tavily_key,
    )


def load_config() -> LLMConfig:
    """Load the config from disk, bootstrapping from env on first run."""
    with _lock:
        if not CONFIG_PATH.exists():
            cfg = _bootstrap_from_env()
            # Persist the bootstrapped config so subsequent writes have a base.
            try:
                save_config(cfg)
            except Exception as exc:  # noqa: BLE001
                log.warning("registry.bootstrap_save_failed", error=str(exc))
            return cfg
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return LLMConfig.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            log.error("registry.load_failed", error=str(exc), path=str(CONFIG_PATH))
            # Fall back to env bootstrap if the file is corrupt.
            return _bootstrap_from_env()


def save_config(cfg: LLMConfig) -> None:
    """Persist config to disk atomically."""
    with _lock:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)


def to_view(cfg: LLMConfig) -> LLMConfigView:
    """Build a masked view safe to return to the client."""
    providers = [
        ProviderView(
            id=p.id,
            name=p.name,
            protocol=p.protocol,
            base_url=p.base_url,
            api_key_configured=bool(p.api_key),
            api_key_preview=_mask(p.api_key),
            created_at=p.created_at,
        )
        for p in cfg.providers
    ]
    models = [
        ModelView(
            id=m.id,
            provider_id=m.provider_id,
            name=m.name,
            display_name=m.display_name,
            capabilities=list(m.capabilities),
            created_at=m.created_at,
        )
        for m in cfg.models
    ]
    roles_configured = {
        role: (role in cfg.role_assignments and bool(_resolve(cfg, role)))
        for role in ALL_ROLES
    }
    return LLMConfigView(
        version=cfg.version,
        providers=providers,
        models=models,
        role_assignments=dict(cfg.role_assignments),
        tavily_api_key_configured=bool(cfg.tavily_api_key),
        tavily_api_key_preview=_mask(cfg.tavily_api_key),
        roles_configured=roles_configured,
        mineru_api_key_configured=bool(cfg.mineru_api_key),
        mineru_api_key_preview=_mask(cfg.mineru_api_key),
        mineru_base_url=cfg.mineru_base_url,
        smtp_host=cfg.smtp_host,
        smtp_port=cfg.smtp_port,
        smtp_user=cfg.smtp_user,
        smtp_password_configured=bool(cfg.smtp_password),
        smtp_password_preview=_mask(cfg.smtp_password),
        smtp_from=cfg.smtp_from,
        smtp_use_tls=cfg.smtp_use_tls,
    )


# ---------- Mutations ----------

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def add_provider(
    cfg: LLMConfig,
    *,
    name: str,
    protocol: Protocol,
    base_url: str | None,
    api_key: str,
) -> Provider:
    p = Provider(
        id=_new_id("p"),
        name=name,
        protocol=protocol,
        base_url=(base_url or "").strip() or None,
        api_key=api_key or "",
    )
    cfg.providers.append(p)
    return p


def update_provider(
    cfg: LLMConfig,
    provider_id: str,
    *,
    name: str | None = None,
    protocol: Protocol | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Provider | None:
    for p in cfg.providers:
        if p.id != provider_id:
            continue
        if name is not None:
            p.name = name
        if protocol is not None:
            p.protocol = protocol
        # Empty string clears base_url; None leaves it unchanged.
        if base_url is not None:
            p.base_url = base_url.strip() or None
        # Empty string clears api_key; None leaves it unchanged.
        if api_key is not None:
            p.api_key = api_key
        return p
    return None


def delete_provider(cfg: LLMConfig, provider_id: str) -> int:
    """Delete provider + its models + role assignments pointing at them."""
    cfg.providers = [p for p in cfg.providers if p.id != provider_id]
    deleted_model_ids = {m.id for m in cfg.models if m.provider_id == provider_id}
    cfg.models = [m for m in cfg.models if m.provider_id != provider_id]
    cfg.role_assignments = {
        r: mid for r, mid in cfg.role_assignments.items() if mid not in deleted_model_ids
    }
    return len(deleted_model_ids)


def add_model(
    cfg: LLMConfig,
    *,
    provider_id: str,
    name: str,
    display_name: str | None = None,
    capabilities: list[Role] | None = None,
) -> Model | None:
    if not any(p.id == provider_id for p in cfg.providers):
        return None
    m = Model(
        id=_new_id("m"),
        provider_id=provider_id,
        name=name.strip(),
        display_name=(display_name or name).strip(),
        capabilities=list(capabilities or []),
    )
    cfg.models.append(m)
    return m


def update_model(
    cfg: LLMConfig,
    model_id: str,
    *,
    name: str | None = None,
    display_name: str | None = None,
    capabilities: list[Role] | None = None,
) -> Model | None:
    for m in cfg.models:
        if m.id != model_id:
            continue
        if name is not None:
            m.name = name.strip()
        if display_name is not None:
            m.display_name = display_name.strip()
        if capabilities is not None:
            m.capabilities = list(capabilities)
        return m
    return None


def delete_model(cfg: LLMConfig, model_id: str) -> bool:
    before = len(cfg.models)
    cfg.models = [m for m in cfg.models if m.id != model_id]
    cfg.role_assignments = {
        r: mid for r, mid in cfg.role_assignments.items() if mid != model_id
    }
    return len(cfg.models) < before


def set_role_assignment(cfg: LLMConfig, role: Role, model_id: str | None) -> bool:
    """Point ``role`` at ``model_id``. ``None`` clears it.

    Returns False if ``model_id`` doesn't exist or lacks the capability.
    """
    if model_id is None:
        cfg.role_assignments.pop(role, None)
        return True
    m = next((x for x in cfg.models if x.id == model_id), None)
    if m is None:
        return False
    if role not in m.capabilities:
        return False
    cfg.role_assignments[role] = model_id
    return True


def set_tavily_key(cfg: LLMConfig, key: str) -> None:
    cfg.tavily_api_key = key or ""


def set_mineru_key(cfg: LLMConfig, key: str, base_url: str | None = None) -> None:
    """Update Mineru API key. Optionally also update base_url.

    Empty string clears the key; None leaves base_url unchanged.
    """
    cfg.mineru_api_key = key or ""
    if base_url is not None:
        cfg.mineru_base_url = base_url.strip() or "https://mineru.net/api/v4"


def get_mineru_config() -> tuple[str, str]:
    """Return (api_key, base_url) from the on-disk config."""
    cfg = load_config()
    return cfg.mineru_api_key, cfg.mineru_base_url


def set_smtp_config(
    cfg: LLMConfig,
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    from_addr: str | None = None,
    use_tls: bool | None = None,
) -> None:
    """Update SMTP settings. None leaves a field unchanged; empty string clears.

    ``password`` follows the same convention as ``api_key`` elsewhere: pass
    None to leave unchanged, "" to clear, or a real value to set.
    """
    if host is not None:
        cfg.smtp_host = host.strip()
    if port is not None:
        cfg.smtp_port = int(port)
    if user is not None:
        cfg.smtp_user = user.strip()
    if password is not None:
        cfg.smtp_password = password
    if from_addr is not None:
        cfg.smtp_from = from_addr.strip() or "notify@lifetree.local"
    if use_tls is not None:
        cfg.smtp_use_tls = bool(use_tls)


def get_smtp_config() -> dict[str, Any]:
    """Return SMTP settings from the on-disk config (hot-reloadable).

    Keys: host, port, user, password, from, use_tls.
    """
    cfg = load_config()
    return {
        "host": cfg.smtp_host,
        "port": cfg.smtp_port,
        "user": cfg.smtp_user,
        "password": cfg.smtp_password,
        "from": cfg.smtp_from,
        "use_tls": cfg.smtp_use_tls,
    }


# ---------- Resolution ----------

def _resolve(cfg: LLMConfig, role: Role) -> ResolvedModel | None:
    """Return the (model, provider) for ``role`` or None if unconfigured."""
    model_id = cfg.role_assignments.get(role)
    if not model_id:
        return None
    m = next((x for x in cfg.models if x.id == model_id), None)
    if m is None:
        return None
    p = next((x for x in cfg.providers if x.id == m.provider_id), None)
    if p is None:
        return None
    return ResolvedModel(model=m, provider=p)


def resolve_role(role: Role) -> ResolvedModel | None:
    """Look up the configured model for ``role`` from the on-disk config."""
    cfg = load_config()
    return _resolve(cfg, role)


def get_tavily_key() -> str:
    return load_config().tavily_api_key


__all__ = [
    "ALL_ROLES",
    "LLMConfig",
    "LLMConfigView",
    "Model",
    "ModelView",
    "Provider",
    "ProviderView",
    "Protocol",
    "ResolvedModel",
    "Role",
    "add_model",
    "add_provider",
    "delete_model",
    "delete_provider",
    "get_mineru_config",
    "get_smtp_config",
    "get_tavily_key",
    "load_config",
    "resolve_role",
    "save_config",
    "set_mineru_key",
    "set_role_assignment",
    "set_smtp_config",
    "set_tavily_key",
    "to_view",
    "update_model",
    "update_provider",
]
