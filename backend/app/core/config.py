"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
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
    app_backend_port: int = 18000
    app_frontend_port: int = 13000
    app_cors_origins: str = "http://localhost:13000"

    # ---------- Runtime storage ----------
    # ``local`` enables the Alpha SQLite, filesystem blob, and in-process job
    # adapters. Embedded graph/vector adapters and desktop packaging remain pending.
    lifetree_storage_mode: Literal["server", "local"] = "server"
    lifetree_data_dir: Path | None = None
    lifetree_desktop_token: SecretStr = SecretStr("")

    # ---------- PostgreSQL ----------
    postgres_user: str = "lifetree"
    postgres_password: SecretStr = SecretStr("lifetree")
    postgres_db: str = "lifetree"
    postgres_host: str = "localhost"
    postgres_port: int = 15432

    # ---------- Neo4j ----------
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("lifetree123")
    neo4j_uri: str = "bolt://localhost:17687"

    # ---------- Redis ----------
    redis_host: str = "localhost"
    redis_port: int = 16379

    # ---------- MinIO ----------
    minio_root_user: str = "lifetree"
    minio_root_password: SecretStr = SecretStr("lifetree123")
    minio_endpoint: str = "localhost:19000"
    minio_bucket: str = "lifetree-uploads"

    # ---------- LLM (legacy env bootstrap — configure via WebUI instead) ----------
    # These fields are only used by registry._bootstrap_from_env() on first startup
    # if the database has no LLM config yet. After that, all LLM config lives in DB.
    llm_provider: Literal["openai", "anthropic", "openai_compatible"] = "openai"
    llm_base_url: str | None = None
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4o-mini"
    llm_embedding_model: str = "text-embedding-3-small"

    # ---------- Tavily (legacy — configure via WebUI) ----------
    tavily_api_key: SecretStr = SecretStr("")

    # ---------- SMTP (legacy — configure via WebUI) ----------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "notify@lifetree.local"

    # ---------- Optional notification gateways ----------
    sms_provider: Literal["none", "twilio"] = "none"
    twilio_account_sid: str = ""
    twilio_auth_token: SecretStr = SecretStr("")
    twilio_from_number: str = ""
    vapid_private_key: SecretStr = SecretStr("")
    vapid_public_key: str = ""
    vapid_contact: str = "mailto:admin@lifetree.local"

    def model_post_init(self, __context: object) -> None:
        """Auto-generate VAPID key pair on first run if not configured.

        Web Push notifications require a VAPID key pair to identify the
        application server. Rather than force every deployment to manually
        generate and configure keys, we auto-generate a pair at startup
        when both keys are empty. This makes browser push notifications
        work out of the box — the only requirement is user authorization
        in the browser.
        """
        if not self.vapid_private_key.get_secret_value() and not self.vapid_public_key:
            try:
                import base64

                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.asymmetric import ec

                private_key = ec.generate_private_key(ec.SECP256R1())

                private_der = private_key.private_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
                self.vapid_private_key = SecretStr(
                    base64.urlsafe_b64encode(private_der).decode().rstrip("=")
                )

                public_numbers = private_key.public_key().public_numbers()
                pub_bytes = b"\x04" + public_numbers.x.to_bytes(32, "big") + public_numbers.y.to_bytes(32, "big")
                self.vapid_public_key = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")
            except Exception:
                # cryptography not installed (e.g. minimal env) — silently
                # leave keys empty; web push stays "未配置" but app runs.
                pass

    # ---------- Plugins ----------
    # Directory where user-uploaded plugin .py files are stored.
    # Relative to the backend working directory; created on demand.
    user_plugins_dir: str = "plugins/user_uploaded"

    # ---------- Auth (multi-user) ----------
    # Comma-separated list of user IDs that should be promoted to admin.
    # Set in .env, e.g. LIFETREE_ADMIN_USER_IDS=00000000-0000-0000-0000-000000000001,abc-...
    # These users gain admin role on next login / request regardless of their DB role.
    lifetree_admin_user_ids: str = ""

    # JWT access token lifetime (minutes). Short-lived; refreshed via /auth/refresh.
    auth_access_token_ttl_minutes: int = 60 * 24  # 24h
    # JWT refresh token lifetime (days). Long-lived; stored client-side.
    auth_refresh_token_ttl_days: int = 30

    # Both usage modes require login. ``single`` permits one administrator
    # account and disables later registrations; ``multi`` supports isolated
    # users and the full service deployment. Defaults to ``single`` so existing
    # deployments keep working. The runtime value lives in DB
    # (``app_config.use_mode``); this env var only seeds the initial value
    # at first boot — afterwards the admin can switch modes from the
    # settings UI.
    lifetree_use_mode: Literal["single", "multi"] = "single"

    # Deprecated compatibility flag. Interactive requests never fall back to
    # an anonymous default account, regardless of this value.
    auth_allow_default_user_fallback: bool = False

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

    @field_validator("lifetree_data_dir", mode="before")
    @classmethod
    def _normalize_data_dir(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key.get_secret_value()) and bool(self.llm_base_url)

    @property
    def admin_user_ids(self) -> set[str]:
        """Return the set of user IDs promoted to admin via env var."""
        return {uid.strip() for uid in self.lifetree_admin_user_ids.split(",") if uid.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()


# Module-level singleton for scripts (entrypoint, alembic) that need direct import.
settings = get_settings()
