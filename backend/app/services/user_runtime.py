"""User-scoped service configuration and model resolution."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.llm.registry import (
    ALL_ROLES,
    Model,
    Provider,
    ResolvedModel,
    Role,
    load_config,
    resolve_role,
)
from app.models.llm_config import AppConfig
from app.models.user_runtime import UserServiceConfig

ALLOW_USER_SERVICES_KEY = "allow_user_service_config"


def _decode_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"true", "1"}


def user_services_allowed(db: Session) -> bool:
    row = db.get(AppConfig, ALLOW_USER_SERVICES_KEY)
    return _decode_bool(row.value if row else None)


def set_user_services_allowed(db: Session, enabled: bool) -> None:
    row = db.get(AppConfig, ALLOW_USER_SERVICES_KEY)
    value = "true" if enabled else "false"
    if row is None:
        db.add(AppConfig(key=ALLOW_USER_SERVICES_KEY, value=value))
    else:
        row.value = value
    db.commit()


def get_or_create_user_config(db: Session, user_id: str) -> UserServiceConfig:
    config = db.get(UserServiceConfig, user_id)
    if config is None:
        config = UserServiceConfig(user_id=user_id, providers=[], models=[], role_assignments={})
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def _mask(secret: str) -> str:
    return "" if not secret else f"••••{secret[-4:]}"


def runtime_catalog(db: Session, user_id: str) -> dict[str, Any]:
    global_config = load_config()
    private = get_or_create_user_config(db, user_id)
    providers = [
        {
            "id": p.id,
            "name": p.name,
            "protocol": p.protocol,
            "base_url": None,
            "api_key_configured": bool(p.api_key),
            "api_key_preview": "",
            "managed_by": "admin",
        }
        for p in global_config.providers
    ]
    providers.extend(
        {
            **p,
            "api_key": None,
            "api_key_configured": bool(p.get("api_key")),
            "api_key_preview": _mask(str(p.get("api_key", ""))),
            "managed_by": "user",
        }
        for p in (private.providers or [])
    )
    models = [
        {**m.model_dump(), "managed_by": "admin"} for m in global_config.models
    ]
    models.extend({**m, "managed_by": "user"} for m in (private.models or []))
    assignments = dict(global_config.role_assignments)
    assignments.update(private.role_assignments or {})
    return {
        "allow_user_service_config": user_services_allowed(db),
        "providers": providers,
        "models": models,
        "role_assignments": assignments,
        "tavily_configured": bool(private.tavily_api_key),
        "mineru_configured": bool(private.mineru_api_key),
        "mineru_base_url": private.mineru_base_url,
    }


def add_user_provider(
    db: Session, user_id: str, *, name: str, protocol: str,
    base_url: str | None, api_key: str,
) -> dict[str, Any]:
    config = get_or_create_user_config(db, user_id)
    provider = {
        "id": f"up_{uuid.uuid4().hex[:12]}",
        "name": name.strip(),
        "protocol": protocol,
        "base_url": (base_url or "").strip() or None,
        "api_key": api_key,
        "created_at": datetime.now(UTC).isoformat(),
    }
    config.providers = [*(config.providers or []), provider]
    db.commit()
    return provider


def add_user_model(
    db: Session, user_id: str, *, provider_id: str, name: str,
    display_name: str, capabilities: list[str],
) -> dict[str, Any]:
    config = get_or_create_user_config(db, user_id)
    if not any(p.get("id") == provider_id for p in (config.providers or [])):
        raise ValueError("User provider not found")
    valid_capabilities = [r for r in capabilities if r in ALL_ROLES]
    model = {
        "id": f"um_{uuid.uuid4().hex[:12]}",
        "provider_id": provider_id,
        "name": name.strip(),
        "display_name": display_name.strip() or name.strip(),
        "capabilities": valid_capabilities,
        "created_at": datetime.now(UTC).isoformat(),
    }
    config.models = [*(config.models or []), model]
    db.commit()
    return model


def set_user_roles(db: Session, user_id: str, assignments: dict[str, str | None]) -> None:
    config = get_or_create_user_config(db, user_id)
    current = dict(config.role_assignments or {})
    models = {m.get("id"): m for m in (config.models or [])}
    global_models = {m.id: m for m in load_config().models}
    for role, model_id in assignments.items():
        if role not in ALL_ROLES:
            raise ValueError(f"Unknown role: {role}")
        if model_id is None:
            current.pop(role, None)
            continue
        model = models.get(model_id) or global_models.get(model_id)
        capabilities = model.get("capabilities", []) if isinstance(model, dict) else model.capabilities
        if model is None or role not in capabilities:
            raise ValueError(f"Model cannot serve role '{role}'")
        current[role] = model_id
    config.role_assignments = current
    db.commit()


def update_user_services(
    db: Session, user_id: str, *, tavily_api_key: str | None,
    mineru_api_key: str | None, mineru_base_url: str | None,
) -> None:
    config = get_or_create_user_config(db, user_id)
    if tavily_api_key is not None:
        config.tavily_api_key = tavily_api_key
    if mineru_api_key is not None:
        config.mineru_api_key = mineru_api_key
    if mineru_base_url is not None:
        config.mineru_base_url = mineru_base_url.strip() or "https://mineru.net/api/v4"
    db.commit()


def resolve_user_model(
    db: Session, user_id: str, role: Role = "chat", model_id: str | None = None,
) -> ResolvedModel | None:
    config = get_or_create_user_config(db, user_id)
    selected_id = model_id or (config.role_assignments or {}).get(role)
    if selected_id:
        models = {m.get("id"): m for m in (config.models or [])}
        model_data = models.get(selected_id)
        if model_data:
            if role not in model_data.get("capabilities", []):
                return None
            provider_data = next(
                (p for p in (config.providers or []) if p.get("id") == model_data.get("provider_id")),
                None,
            )
            if provider_data:
                return ResolvedModel(
                    model=Model(**model_data), provider=Provider(**provider_data)
                )
        global_config = load_config()
        global_model = next((m for m in global_config.models if m.id == selected_id), None)
        if global_model and role in global_model.capabilities:
            provider = next(
                (p for p in global_config.providers if p.id == global_model.provider_id), None
            )
            if provider:
                return ResolvedModel(model=global_model, provider=provider)
    return resolve_role(role)
