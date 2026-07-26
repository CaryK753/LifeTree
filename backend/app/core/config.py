"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings; populated from .env or process environment."""

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- App ----------
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    app_secret_key: SecretStr = SecretStr("change-me-in-production")
    app_backend_port: int = 8000
    app_frontend_port: int = 3000
    app_cors_origins: str = "http://localhost:3000"

    # ---------- PostgreSQL ----------
    postgres_user: str = "lifetree"
    postgres_password: SecretStr = SecretStr("lifetree")
    postgres_db: str = "lifetree"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # ---------- Neo4j ----------
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("lifetree123")
    neo4j_uri: str = "bolt://localhost:7687"

    # ---------- Redis ----------
    redis_host: str = "localhost"
    redis_port: int = 6379

    # ---------- MinIO ----------
    minio_root_user: str = "lifetree"
    minio_root_password: SecretStr = SecretStr("lifetree123")
    minio_endpoint: str = "localhost:9000"
    minio_bucket: str = "lifetree-uploads"

    # ---------- LLM ----------
    llm_provider: Literal["openai", "anthropic", "openai_compatible"] = "openai"
    llm_base_url: str | None = None
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4o-mini"
    llm_embedding_model: str = "text-embedding-3-small"

    # ---------- Tavily ----------
    tavily_api_key: SecretStr = SecretStr("")

    # ---------- SMTP ----------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "notify@lifetree.local"

    # ---------- Computed ----------
    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.app_cors_origins.split(",") if o.strip()]

    @field_validator("llm_base_url")
    @classmethod
    def _normalize_base_url(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        return v.rstrip("/")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key.get_secret_value()) and bool(self.llm_base_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()
