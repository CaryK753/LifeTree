"""User-scoped AI service and MCP configuration endpoints."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import AdminUser, CurrentUser
from app.db.postgres import get_db
from app.llm.registry import ALL_ROLES, get_use_mode
from app.models.user_runtime import UserMCPServer
from app.services.user_runtime import (
    add_user_model,
    add_user_provider,
    runtime_catalog,
    set_user_roles,
    set_user_services_allowed,
    update_user_services,
    user_services_allowed,
)

router = APIRouter(prefix="/settings/runtime", tags=["user-runtime"])
DbSession = Annotated[Session, Depends(get_db)]


class PolicyUpdate(BaseModel):
    enabled: bool


class UserProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    protocol: Literal["openai_compatible", "ollama", "anthropic", "bailian"]
    base_url: str | None = Field(None, max_length=512)
    api_key: str = Field("", max_length=4096)


class UserModelCreate(BaseModel):
    provider_id: str = Field(..., max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field("", max_length=128)
    capabilities: list[str] = Field(default_factory=list)


class UserRolesUpdate(BaseModel):
    assignments: dict[str, str | None]


class UserServicesUpdate(BaseModel):
    tavily_api_key: str | None = Field(None, max_length=4096)
    mineru_api_key: str | None = Field(None, max_length=4096)
    mineru_base_url: str | None = Field(None, max_length=512)


class MCPCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    protocol: Literal["http", "sse", "stdio"]
    description: str = Field("", max_length=512)
    url: HttpUrl | None = None
    command: str | None = Field(None, max_length=256)
    args: list[str] = Field(default_factory=list, max_length=32)
    headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class ToggleUpdate(BaseModel):
    enabled: bool


def _require_service_access(db: Session, user: CurrentUser) -> None:
    if get_use_mode() == "multi" and user.role != "admin" and not user_services_allowed(db):
        raise HTTPException(403, "Administrator has disabled personal service configuration")


def _mcp_view(row: UserMCPServer) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "protocol": row.protocol,
        "description": row.description,
        "config": row.config,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/catalog")
def get_catalog(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return runtime_catalog(db, user.id)


@router.get("/policy", response_model=PolicyUpdate)
def get_policy(admin: AdminUser, db: DbSession) -> PolicyUpdate:
    return PolicyUpdate(enabled=user_services_allowed(db))


@router.put("/policy", response_model=PolicyUpdate)
def put_policy(
    payload: PolicyUpdate, admin: AdminUser, db: DbSession
) -> PolicyUpdate:
    set_user_services_allowed(db, payload.enabled)
    return payload


@router.post("/providers", status_code=201)
def create_provider(
    payload: UserProviderCreate, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    _require_service_access(db, user)
    add_user_provider(db, user.id, **payload.model_dump())
    return runtime_catalog(db, user.id)


@router.post("/models", status_code=201)
def create_model(
    payload: UserModelCreate, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    _require_service_access(db, user)
    invalid = set(payload.capabilities) - set(ALL_ROLES)
    if invalid:
        raise HTTPException(400, f"Unknown capabilities: {', '.join(sorted(invalid))}")
    try:
        add_user_model(db, user.id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return runtime_catalog(db, user.id)


@router.put("/roles")
def put_roles(
    payload: UserRolesUpdate, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    _require_service_access(db, user)
    try:
        set_user_roles(db, user.id, payload.assignments)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return runtime_catalog(db, user.id)


@router.put("/services")
def put_services(
    payload: UserServicesUpdate, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    _require_service_access(db, user)
    update_user_services(db, user.id, **payload.model_dump())
    return runtime_catalog(db, user.id)


@router.get("/mcp")
def list_mcp(user: CurrentUser, db: DbSession) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(UserMCPServer)
        .where(UserMCPServer.user_id == user.id)
        .order_by(UserMCPServer.created_at.desc())
    )
    return [_mcp_view(row) for row in rows]


@router.post("/mcp", status_code=201)
def create_mcp(
    payload: MCPCreate, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    if payload.protocol in {"http", "sse"} and payload.url is None:
        raise HTTPException(400, "URL is required for HTTP/SSE MCP")
    if payload.protocol == "stdio" and not payload.command:
        raise HTTPException(400, "Command is required for stdio MCP")
    config = (
        {
            "url": str(payload.url),
            "headers": payload.headers,
            "extra_body": payload.extra_body,
        }
        if payload.protocol in {"http", "sse"}
        else {"command": payload.command, "args": payload.args}
    )
    row = UserMCPServer(
        user_id=user.id, name=payload.name.strip(), protocol=payload.protocol,
        description=payload.description.strip(), config=config,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _mcp_view(row)


@router.patch("/mcp/{server_id}")
def toggle_mcp(
    server_id: str, payload: ToggleUpdate, user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    row = db.get(UserMCPServer, server_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "MCP server not found")
    row.enabled = payload.enabled
    db.commit()
    db.refresh(row)
    return _mcp_view(row)


@router.delete("/mcp/{server_id}", status_code=204)
def delete_mcp(
    server_id: str, user: CurrentUser, db: DbSession
) -> None:
    row = db.get(UserMCPServer, server_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "MCP server not found")
    db.delete(row)
    db.commit()
