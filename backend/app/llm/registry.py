"""Multi-provider / multi-model LLM registry.

Single source of truth for AI model configuration in LifeTree. Replaces the
old single-LLM env-var setup (``LLM_BASE_URL`` / ``LLM_API_KEY`` / etc.) with
a structured document that can describe many providers and many models, each
tagged with the roles they can serve.

Storage: PostgreSQL tables (``llm_providers``, ``llm_models``, ``app_config``).
Previously this module persisted to ``backend/.llm_config.json``; on first load
against an empty DB, any existing JSON file is imported once and then the JSON
file is ignored. If neither DB nor JSON has data, the registry bootstraps from
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
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.postgres import SessionLocal
from app.models.llm_config import AppConfig, LLMModel, LLMProvider

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
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class Model(BaseModel):
    """An individual model exposed by a provider, tagged with capabilities."""

    id: str
    provider_id: str
    name: str  # the model id sent to the API (e.g. "gpt-4o-mini")
    display_name: str  # human label in the UI
    capabilities: list[Role] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class LLMConfig(BaseModel):
    """Top-level persisted config."""

    version: int = 1
    providers: list[Provider] = Field(default_factory=list)
    models: list[Model] = Field(default_factory=list)
    role_assignments: dict[Role, str] = Field(default_factory=dict)
    tavily_api_key: str = ""
    # Third-party service keys (kept here so the whole config is one document)
    mineru_api_key: str = ""
    mineru_base_url: str = "https://mineru.net/api/v4"
    # SMTP for risk-warning email notifications (§4.5). Hot-reloadable like
    # the rest of this config — no process restart required.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "notify@lifetree.local"
    smtp_sender_name: str = "LifeTree"  # display name for From header
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False  # use SSL (port 465) instead of STARTTLS


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
    smtp_sender_name: str
    smtp_use_tls: bool
    smtp_use_ssl: bool


# ---------- Resolved client target (internal) ----------

class ResolvedModel(BaseModel):
    """A model + its parent provider, ready to construct a client."""

    model: Model
    provider: Provider


# ---------- Storage ----------

# Legacy JSON path — only consulted once for migration into the DB.
CONFIG_PATH = Path(__file__).resolve().parents[2] / ".llm_config.json"

# app_config keys (single source of truth — keep in sync with load/save).
_KEY_TAVILY = "tavily_api_key"
_KEY_MINERU_KEY = "mineru_api_key"
_KEY_MINERU_URL = "mineru_base_url"
_KEY_SMTP_HOST = "smtp_host"
_KEY_SMTP_PORT = "smtp_port"
_KEY_SMTP_USER = "smtp_user"
_KEY_SMTP_PASSWORD = "smtp_password"
_KEY_SMTP_FROM = "smtp_from"
_KEY_SMTP_SENDER_NAME = "smtp_sender_name"
_KEY_SMTP_USE_TLS = "smtp_use_tls"
_KEY_SMTP_USE_SSL = "smtp_use_ssl"
_KEY_ROLE_ASSIGNMENTS = "role_assignments"

_DEFAULT_MINERU_URL = "https://mineru.net/api/v4"
_DEFAULT_SMTP_FROM = "notify@lifetree.local"
_DEFAULT_SMTP_SENDER_NAME = "LifeTree"

_lock = threading.RLock()


@contextmanager
def _db_session() -> Iterator[Session]:
    """Context-managed DB session: commit on success, rollback on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 4:
        return "••••"
    return "••••" + secret[-4:]


def _parse_iso(s: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a tz-aware datetime.

    Returns None if the string is empty or unparseable (lets the DB fall
    back to its ``server_default``).
    """
    if not s:
        return None
    try:
        # ``datetime.fromisoformat`` accepts "+00:00" but not "Z" pre-3.11.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _iso(dt: datetime | None) -> str:
    """Render a DB datetime as an ISO string (matching the old JSON format)."""
    if dt is None:
        return datetime.now(UTC).isoformat()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _decode_value(raw: str | None, default: Any) -> Any:
    """Decode a JSON-encoded app_config value, falling back to default.

    All app_config values are stored JSON-encoded so scalars (int/bool/str)
    and complex types (dict/list) round-trip losslessly. This avoids the
    classic ``False or default`` / ``0 or default`` coercion trap.
    """
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _set_app_config(session: Session, key: str, value: Any) -> None:
    """Upsert one app_config row. Value is JSON-encoded."""
    encoded = json.dumps(value)
    row = session.get(AppConfig, key)
    if row is None:
        session.add(AppConfig(key=key, value=encoded))
    else:
        row.value = encoded


def _bootstrap_from_env() -> LLMConfig:
    """Build an initial config from legacy LLM_* env vars.

    This runs once on first startup if neither the DB nor the legacy JSON
    file has any config. The resulting config is *not* written to the DB by
    this function — callers decide whether to persist.
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


# ---------- DB <-> pydantic translation ----------

def _load_from_db() -> LLMConfig | None:
    """Build an LLMConfig from DB rows.

    Returns None if the DB has no config rows at all (so the caller can
    decide to bootstrap from JSON or env vars).
    """
    with _db_session() as session:
        providers_orm = (
            session.query(LLMProvider).order_by(LLMProvider.created_at).all()
        )
        models_orm = session.query(LLMModel).order_by(LLMModel.created_at).all()
        config_rows = {r.key: r.value for r in session.query(AppConfig).all()}

        if not providers_orm and not models_orm and not config_rows:
            return None

        providers = [
            Provider(
                id=p.id,
                name=p.name,
                protocol=p.protocol,
                base_url=p.base_url,
                api_key=p.api_key or "",
                created_at=_iso(p.created_at),
            )
            for p in providers_orm
        ]
        models = [
            Model(
                id=m.id,
                provider_id=m.provider_id,
                name=m.name,
                display_name=m.display_name,
                capabilities=list(m.capabilities or []),
                created_at=_iso(m.created_at),
            )
            for m in models_orm
        ]

        role_assignments = _decode_value(
            config_rows.get(_KEY_ROLE_ASSIGNMENTS), {}
        ) or {}
        if not isinstance(role_assignments, dict):
            role_assignments = {}

        tavily = _decode_value(config_rows.get(_KEY_TAVILY), "") or ""
        mineru_key = _decode_value(config_rows.get(_KEY_MINERU_KEY), "") or ""
        mineru_url = (
            _decode_value(config_rows.get(_KEY_MINERU_URL), _DEFAULT_MINERU_URL)
            or _DEFAULT_MINERU_URL
        )
        smtp_host = _decode_value(config_rows.get(_KEY_SMTP_HOST), "") or ""
        smtp_port = _decode_value(config_rows.get(_KEY_SMTP_PORT), 587) or 587
        smtp_user = _decode_value(config_rows.get(_KEY_SMTP_USER), "") or ""
        smtp_password = _decode_value(config_rows.get(_KEY_SMTP_PASSWORD), "") or ""
        smtp_from = (
            _decode_value(config_rows.get(_KEY_SMTP_FROM), _DEFAULT_SMTP_FROM)
            or _DEFAULT_SMTP_FROM
        )
        smtp_sender_name = (
            _decode_value(config_rows.get(_KEY_SMTP_SENDER_NAME), _DEFAULT_SMTP_SENDER_NAME)
            or _DEFAULT_SMTP_SENDER_NAME
        )
        # NOTE: do not coerce ``smtp_use_tls`` with ``or`` — False is valid.
        smtp_use_tls = _decode_value(config_rows.get(_KEY_SMTP_USE_TLS), True)
        if not isinstance(smtp_use_tls, bool):
            smtp_use_tls = True
        # NOTE: same bool-safe pattern for ``smtp_use_ssl``.
        smtp_use_ssl = _decode_value(config_rows.get(_KEY_SMTP_USE_SSL), False)
        if not isinstance(smtp_use_ssl, bool):
            smtp_use_ssl = False

        return LLMConfig(
            version=1,
            providers=providers,
            models=models,
            role_assignments=role_assignments,
            tavily_api_key=tavily,
            mineru_api_key=mineru_key,
            mineru_base_url=mineru_url,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            smtp_from=smtp_from,
            smtp_sender_name=smtp_sender_name,
            smtp_use_tls=smtp_use_tls,
            smtp_use_ssl=smtp_use_ssl,
        )


def load_config() -> LLMConfig:
    """Load the config from the DB.

    On first run against an empty DB:
      1. If the legacy ``.llm_config.json`` exists, its contents are imported
         into the DB once and then the JSON file is ignored.
      2. Otherwise, bootstrap from ``LLM_*`` env vars and persist to DB.
    """
    with _lock:
        try:
            cfg = _load_from_db()
            if cfg is not None:
                return cfg
        except Exception as exc:  # noqa: BLE001
            log.error("registry.load_db_failed", error=str(exc))
            # Fall back to env bootstrap if the DB read fails outright.
            return _bootstrap_from_env()

        # DB is empty — try the one-time JSON migration.
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                cfg = LLMConfig.model_validate(data)
                # Persist the migrated config so subsequent loads skip JSON.
                try:
                    save_config(cfg)
                    log.info(
                        "registry.json_migrated",
                        providers=len(cfg.providers),
                        models=len(cfg.models),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("registry.json_migrate_save_failed", error=str(exc))
                return cfg
            except Exception as exc:  # noqa: BLE001
                log.warning("registry.json_migration_failed", error=str(exc))
                # Fall through to env bootstrap.

        # No DB data, no JSON — bootstrap from env and persist.
        cfg = _bootstrap_from_env()
        try:
            save_config(cfg)
        except Exception as exc:  # noqa: BLE001
            log.warning("registry.bootstrap_save_failed", error=str(exc))
        return cfg


def save_config(cfg: LLMConfig) -> None:
    """Persist config to the DB (full sync).

    Upserts every provider/model/app_config row from ``cfg`` and deletes
    DB rows that no longer exist in ``cfg``. ``created_at`` is preserved
    on existing rows; new rows get the DB ``server_default`` (or the
    pydantic ``created_at`` if it carries a real timestamp).
    """
    with _lock:
        with _db_session() as session:
            cfg_provider_ids = {p.id for p in cfg.providers}
            cfg_model_ids = {m.id for m in cfg.models}

            # --- Providers: upsert + delete missing ---
            for p in cfg.providers:
                row = session.get(LLMProvider, p.id)
                if row is None:
                    created_at = _parse_iso(p.created_at)
                    session.add(
                        LLMProvider(
                            id=p.id,
                            name=p.name,
                            protocol=p.protocol,
                            base_url=p.base_url,
                            api_key=p.api_key or "",
                            created_at=created_at,  # None → DB server_default
                            updated_at=created_at,
                        )
                    )
                else:
                    row.name = p.name
                    row.protocol = p.protocol
                    row.base_url = p.base_url
                    row.api_key = p.api_key or ""
                    # created_at intentionally untouched

            existing_providers = session.query(LLMProvider).all()
            for row in existing_providers:
                if row.id not in cfg_provider_ids:
                    session.delete(row)  # CASCADE removes its models

            # --- Models: upsert + delete missing ---
            for m in cfg.models:
                row = session.get(LLMModel, m.id)
                if row is None:
                    created_at = _parse_iso(m.created_at)
                    session.add(
                        LLMModel(
                            id=m.id,
                            provider_id=m.provider_id,
                            name=m.name,
                            display_name=m.display_name,
                            capabilities=list(m.capabilities),
                            created_at=created_at,
                            updated_at=created_at,
                        )
                    )
                else:
                    row.provider_id = m.provider_id
                    row.name = m.name
                    row.display_name = m.display_name
                    row.capabilities = list(m.capabilities)

            existing_models = session.query(LLMModel).all()
            for row in existing_models:
                if row.id not in cfg_model_ids:
                    session.delete(row)

            # --- app_config: upsert all known keys ---
            _set_app_config(session, _KEY_TAVILY, cfg.tavily_api_key)
            _set_app_config(session, _KEY_MINERU_KEY, cfg.mineru_api_key)
            _set_app_config(session, _KEY_MINERU_URL, cfg.mineru_base_url)
            _set_app_config(session, _KEY_SMTP_HOST, cfg.smtp_host)
            _set_app_config(session, _KEY_SMTP_PORT, cfg.smtp_port)
            _set_app_config(session, _KEY_SMTP_USER, cfg.smtp_user)
            _set_app_config(session, _KEY_SMTP_PASSWORD, cfg.smtp_password)
            _set_app_config(session, _KEY_SMTP_FROM, cfg.smtp_from)
            _set_app_config(session, _KEY_SMTP_SENDER_NAME, cfg.smtp_sender_name)
            _set_app_config(session, _KEY_SMTP_USE_TLS, cfg.smtp_use_tls)
            _set_app_config(session, _KEY_SMTP_USE_SSL, cfg.smtp_use_ssl)
            _set_app_config(session, _KEY_ROLE_ASSIGNMENTS, dict(cfg.role_assignments))


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
        smtp_sender_name=cfg.smtp_sender_name,
        smtp_use_tls=cfg.smtp_use_tls,
        smtp_use_ssl=cfg.smtp_use_ssl,
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
    """Return (api_key, base_url) from the DB-backed config."""
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
    sender_name: str | None = None,
    use_tls: bool | None = None,
    use_ssl: bool | None = None,
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
    if sender_name is not None:
        cfg.smtp_sender_name = sender_name.strip() or "LifeTree"
    if use_tls is not None:
        cfg.smtp_use_tls = bool(use_tls)
    if use_ssl is not None:
        cfg.smtp_use_ssl = bool(use_ssl)


def get_smtp_config() -> dict[str, Any]:
    """Return SMTP settings from the DB-backed config (hot-reloadable).

    Keys: host, port, user, password, from, sender_name, use_tls, use_ssl.
    """
    cfg = load_config()
    return {
        "host": cfg.smtp_host,
        "port": cfg.smtp_port,
        "user": cfg.smtp_user,
        "password": cfg.smtp_password,
        "from": cfg.smtp_from,
        "sender_name": cfg.smtp_sender_name,
        "use_tls": cfg.smtp_use_tls,
        "use_ssl": cfg.smtp_use_ssl,
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
    """Look up the configured model for ``role`` from the DB-backed config."""
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
