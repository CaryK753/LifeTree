"""LLM provider/model configuration ORM models (PostgreSQL-backed).

Replaces the legacy ``backend/.llm_config.json`` file. The registry
(``app.llm.registry``) reads/writes these tables; a one-time migration imports
existing JSON data into the DB on first load.

Tables:
    - ``llm_providers`` — one row per model supplier (OpenAI / DeepSeek / …)
    - ``llm_models``    — one row per model, tagged with capabilities
    - ``app_config``     — key-value store for tavily/mineru/smtp/role_assignments
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base
from app.models.base import TimestampMixin


class LLMProvider(TimestampMixin, Base):
    """A model supplier (OpenAI, DeepSeek, Anthropic, 阿里云百炼, …).

    The ``api_key`` is stored in plaintext — same security level as the
    previous JSON file (this is a single-user app).
    """

    __tablename__ = "llm_providers"

    # Registry assigns IDs like ``p_<hex12>``; the default is just a safety net
    # for direct ORM inserts that don't set the id explicitly.
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    protocol: Mapped[str] = mapped_column(
        String(32), nullable=False, default="openai_compatible"
    )
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_key: Mapped[str] = mapped_column(Text, default="", server_default="")

    models: Mapped[list[LLMModel]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<LLMProvider {self.name}>"


class LLMModel(TimestampMixin, Base):
    """An individual model exposed by a provider, tagged with capabilities.

    ``capabilities`` is a JSONB list of Role strings
    (``["chat","vision","embedding","rerank"]``).
    """

    __tablename__ = "llm_models"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    provider_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("llm_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    capabilities: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    provider: Mapped[LLMProvider] = relationship(back_populates="models")

    def __repr__(self) -> str:
        return f"<LLMModel {self.name}>"


class AppConfig(Base):
    """Key-value store for misc app config.

    Keys: ``tavily_api_key``, ``mineru_api_key``, ``mineru_base_url``,
    ``smtp_host``, ``smtp_port``, ``smtp_user``, ``smtp_password``,
    ``smtp_from``, ``smtp_use_tls``, ``role_assignments``.

    Values are JSON-encoded so any scalar/dict/list round-trips losslessly
    (avoids int/bool coercion bugs).
    """

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<AppConfig {self.key}>"
