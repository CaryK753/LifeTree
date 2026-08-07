"""Per-user AI services, MCP servers, and Skills."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import TimestampMixin, UUIDPkMixin
from app.models.types import JSON_DOCUMENT


class UserServiceConfig(TimestampMixin, Base):
    """Private service configuration and role defaults for one user."""

    __tablename__ = "user_service_configs"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    providers: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    models: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    role_assignments: Mapped[dict[str, str]] = mapped_column(JSON_DOCUMENT, default=dict)
    tavily_api_key: Mapped[str] = mapped_column(Text, default="", server_default="")
    exa_api_key: Mapped[str] = mapped_column(Text, default="", server_default="")
    bocha_api_key: Mapped[str] = mapped_column(Text, default="", server_default="")
    anysearch_api_key: Mapped[str] = mapped_column(Text, default="", server_default="")
    search_default_engine: Mapped[str] = mapped_column(
        String(32), default="", server_default=""
    )
    mineru_api_key: Mapped[str] = mapped_column(Text, default="", server_default="")
    mineru_base_url: Mapped[str] = mapped_column(
        String(512), default="https://mineru.net/api/v4"
    )


class UserMCPServer(UUIDPkMixin, TimestampMixin, Base):
    """A user-owned MCP endpoint or local stdio process definition."""

    __tablename__ = "user_mcp_servers"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class UserSkill(UUIDPkMixin, TimestampMixin, Base):
    """Imported user Skill content used as assistant context."""

    __tablename__ = "user_skills"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(1024), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
