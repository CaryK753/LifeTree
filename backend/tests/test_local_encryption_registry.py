from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core import config as config_mod
from app.core.local_encryption import ENV_KEY, FERNET_PREFIX, reset_encryption_cache
from app.db.postgres import Base as PostgresBase
from app.llm import registry as reg
from app.models.llm_config import AppConfig


@pytest.fixture(autouse=True)
def _isolate_encryption(monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    reset_encryption_cache()
    yield
    reset_encryption_cache()


def _set_local_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(lifetree_storage_mode="local"),
    )


def _test_session_factory(monkeypatch, database_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    PostgresBase.metadata.create_all(
        engine,
        tables=[AppConfig.__table__, reg.LLMProvider.__table__, reg.LLMModel.__table__],
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(reg, "SessionLocal", factory)
    return engine, factory


def test_registry_round_trips_sensitive_values_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_KEY, Fernet.generate_key().decode("ascii"))
    _set_local_mode(monkeypatch)
    engine, _ = _test_session_factory(monkeypatch, tmp_path / "registry.db")

    cfg = reg.LLMConfig()
    reg.set_tavily_key(cfg, "tvly-end-to-end-123")
    reg.set_mineru_key(cfg, "mineru-key-456")
    reg.set_smtp_config(cfg, password="smtp-pass-789", host="smtp.example.com", port=587)
    reg.save_config(cfg)

    with engine.connect() as conn:
        rows = {row[0]: row[1] for row in conn.execute(text("SELECT key, value FROM app_config"))}

    assert rows["tavily_api_key"].startswith(FERNET_PREFIX)
    assert rows["mineru_api_key"].startswith(FERNET_PREFIX)
    assert rows["smtp_password"].startswith(FERNET_PREFIX)
    assert rows["smtp_host"] == json.dumps("smtp.example.com")
    assert rows["smtp_port"] == json.dumps(587)

    loaded = reg.load_config()
    assert loaded.tavily_api_key == "tvly-end-to-end-123"
    assert loaded.mineru_api_key == "mineru-key-456"
    assert loaded.smtp_password == "smtp-pass-789"
    assert loaded.smtp_host == "smtp.example.com"
    assert loaded.smtp_port == 587


def test_registry_plaintext_db_upgrades_on_next_write(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_KEY, Fernet.generate_key().decode("ascii"))
    _set_local_mode(monkeypatch)
    engine, factory = _test_session_factory(monkeypatch, tmp_path / "upgrade.db")

    with factory() as session:
        session.add(AppConfig(key="tavily_api_key", value=json.dumps("tvly-legacy")))
        session.add(AppConfig(key="smtp_password", value=json.dumps("smtp-legacy")))
        session.commit()

    loaded = reg.load_config()
    assert loaded.tavily_api_key == "tvly-legacy"
    assert loaded.smtp_password == "smtp-legacy"
    reg.save_config(loaded)

    with engine.connect() as conn:
        rows = {row[0]: row[1] for row in conn.execute(text("SELECT key, value FROM app_config"))}
    assert rows["tavily_api_key"].startswith(FERNET_PREFIX)
    assert rows["smtp_password"].startswith(FERNET_PREFIX)
    assert json.loads(rows["smtp_host"]) == ""


def test_oauth_provider_client_secret_is_encrypted_at_rest(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_KEY, Fernet.generate_key().decode("ascii"))
    _set_local_mode(monkeypatch)
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'oauth.db'}",
        connect_args={"check_same_thread": False},
    )
    PostgresBase.metadata.create_all(engine, tables=[AppConfig.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(reg, "SessionLocal", factory)
    provider = reg.add_oauth_provider(
        name="GitHub",
        client_id="cid-123",
        client_secret="super-secret-secret",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scopes=["read:user"],
        redirect_uri="http://localhost/auth/callback/github",
    )

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT value FROM app_config WHERE key = 'oauth_providers'")
        ).one()
        stored = json.loads(row[0])
    assert len(stored) == 1
    assert stored[0]["client_id"] == "cid-123"
    assert stored[0]["client_secret"] != "super-secret-secret"
    assert stored[0]["client_secret"].startswith(FERNET_PREFIX)

    providers = reg.get_oauth_providers()
    assert len(providers) == 1
    assert providers[0].client_secret == "super-secret-secret"
    assert providers[0].id == provider.id


def test_oauth_provider_plaintext_legacy_secret_reads_fine(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_KEY, Fernet.generate_key().decode("ascii"))
    _set_local_mode(monkeypatch)
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'oauth_legacy.db'}",
        connect_args={"check_same_thread": False},
    )
    PostgresBase.metadata.create_all(engine, tables=[AppConfig.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(reg, "SessionLocal", factory)
    legacy_payload = [
        {
            "id": "o_legacy",
            "name": "GitHub",
            "client_id": "cid",
            "client_secret": "plaintext-legacy-secret",
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "userinfo_url": "https://api.github.com/user",
            "scopes": ["read:user"],
            "redirect_uri": "http://localhost/auth/callback/github",
            "enabled": True,
            "avatar_url": "",
            "created_at": "2026-07-31T00:00:00+00:00",
        }
    ]
    with factory() as session:
        session.add(AppConfig(key="oauth_providers", value=json.dumps(legacy_payload)))
        session.commit()

    providers = reg.get_oauth_providers()
    assert len(providers) == 1
    assert providers[0].client_secret == "plaintext-legacy-secret"
