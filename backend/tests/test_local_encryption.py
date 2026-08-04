from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Column, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.local_encryption import (
    ENV_KEY,
    FERNET_PREFIX,
    EncryptionError,
    LocalEncryption,
    reset_encryption_cache,
)
from app.models.types import EncryptedText


class _MemoryKeyring:
    """In-memory keyring stub for tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None


@pytest.fixture(autouse=True)
def _isolate_encryption(monkeypatch):
    """Ensure each test starts with a fresh singleton and no env leakage."""
    monkeypatch.delenv(ENV_KEY, raising=False)
    reset_encryption_cache()
    yield
    reset_encryption_cache()


def test_encrypt_decrypt_round_trip():
    store = _MemoryKeyring()
    enc = LocalEncryption(secret_store=store)

    ciphertext = enc.encrypt("sk-secret-key-123")
    assert ciphertext != "sk-secret-key-123"
    assert ciphertext.startswith(FERNET_PREFIX)
    assert enc.decrypt(ciphertext) == "sk-secret-key-123"


def test_key_is_persisted_to_keyring():
    store = _MemoryKeyring()
    enc = LocalEncryption(secret_store=store)

    enc.encrypt("first value")
    assert store.get(LocalEncryption.KEYRING_KEY) is not None

    # A new instance using the same keyring must decrypt data from the first.
    enc2 = LocalEncryption(secret_store=store)
    ciphertext = enc.encrypt("second value")
    assert enc2.decrypt(ciphertext) == "second value"


def test_env_var_takes_precedence_over_keyring(monkeypatch):
    env_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv(ENV_KEY, env_key)
    store = _MemoryKeyring()
    enc = LocalEncryption(secret_store=store)

    ciphertext = enc.encrypt("via-env")
    assert enc.decrypt(ciphertext) == "via-env"
    # Keyring was not touched because env var won.
    assert store.get(LocalEncryption.KEYRING_KEY) is None


def test_empty_values_pass_through():
    enc = LocalEncryption(secret_store=_MemoryKeyring())

    assert enc.encrypt("") == ""
    assert enc.encrypt(None) is None  # type: ignore[arg-type]
    assert enc.decrypt("") == ""
    assert enc.decrypt(None) is None  # type: ignore[arg-type]


def test_already_encrypted_value_is_idempotent():
    enc = LocalEncryption(secret_store=_MemoryKeyring())

    ciphertext = enc.encrypt("original")
    re_encrypted = enc.encrypt(ciphertext)
    assert re_encrypted == ciphertext


def test_plaintext_value_passes_through_decrypt():
    """Old plaintext rows must read fine after enabling encryption."""
    enc = LocalEncryption(secret_store=_MemoryKeyring())

    assert enc.decrypt("sk-legacy-plaintext-key") == "sk-legacy-plaintext-key"


def test_wrong_key_raises_encryption_error():
    store1 = _MemoryKeyring()
    enc1 = LocalEncryption(secret_store=store1)
    ciphertext = enc1.encrypt("secret")

    store2 = _MemoryKeyring()
    enc2 = LocalEncryption(secret_store=store2)
    with pytest.raises(EncryptionError, match="Failed to decrypt"):
        enc2.decrypt(ciphertext)


def test_malformed_key_raises_encryption_error(monkeypatch):
    monkeypatch.setenv(ENV_KEY, "not-a-valid-fernet-key")
    enc = LocalEncryption(secret_store=_MemoryKeyring())
    with pytest.raises(EncryptionError, match="malformed"):
        enc.encrypt("probe")


def _make_settings(mode: str) -> SimpleNamespace:
    return SimpleNamespace(lifetree_storage_mode=mode)


def test_encrypted_text_encrypts_in_local_mode(monkeypatch):
    monkeypatch.setenv(ENV_KEY, Fernet.generate_key().decode("ascii"))
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _make_settings("local"))

    col = EncryptedText()
    ciphertext = col.process_bind_param("sk-test", None)
    assert ciphertext is not None
    assert ciphertext.startswith(FERNET_PREFIX)
    assert col.process_result_value(ciphertext, None) == "sk-test"


def test_encrypted_text_passthrough_in_server_mode(monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _make_settings("server"))

    col = EncryptedText()
    assert col.process_bind_param("sk-test", None) == "sk-test"
    assert col.process_result_value("sk-test", None) == "sk-test"


def test_encrypted_text_empty_passthrough():
    col = EncryptedText()
    assert col.process_bind_param("", None) == ""
    assert col.process_bind_param(None, None) is None
    assert col.process_result_value("", None) == ""
    assert col.process_result_value(None, None) is None


def test_llm_provider_api_key_is_encrypted_at_rest(monkeypatch, tmp_path):
    """Integration: writing an LLMProvider in local mode stores ciphertext."""
    env_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv(ENV_KEY, env_key)
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _make_settings("local"))

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'enc.db'}")

    class _Base(DeclarativeBase):
        pass

    class _Provider(_Base):
        __tablename__ = "llm_providers_test"
        id = Column(Text, primary_key=True)
        api_key = Column(EncryptedText, default="")

    _Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(_Provider(id="p_test", api_key="sk-real-secret"))
        session.commit()

    # Read via raw SQL to bypass the TypeDecorator's decrypt.
    with engine.connect() as conn:
        from sqlalchemy import text

        row = conn.execute(
            text("SELECT api_key FROM llm_providers_test WHERE id = 'p_test'")
        ).one()
        stored = row[0]

    assert stored != "sk-real-secret"
    assert stored.startswith(FERNET_PREFIX)

    # ORM read returns the plaintext.
    with Session(engine) as session:
        provider = session.scalars(select(_Provider)).one()
        assert provider.api_key == "sk-real-secret"


# ---------- AppConfig value encryption (registry layer) ----------

from app.llm import registry as reg  # noqa: E402


def _set_local_mode(monkeypatch) -> None:
    """Configure the process to behave as if running in local storage mode."""
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _make_settings("local"))


def _set_server_mode(monkeypatch) -> None:
    """Configure the process to behave as if running in server storage mode."""
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _make_settings("server"))


def test_encode_decode_sensitive_app_config_round_trip(monkeypatch):
    """Sensitive keys are encrypted in local mode and round-trip cleanly."""
    monkeypatch.setenv(ENV_KEY, Fernet.generate_key().decode("ascii"))
    _set_local_mode(monkeypatch)

    for key in ("tavily_api_key", "mineru_api_key", "smtp_password"):
        encoded = reg._encode_app_config_value(key, "sk-secret-value")
        assert encoded.startswith(FERNET_PREFIX)
        assert encoded != json.dumps("sk-secret-value")
        decoded = reg._decode_app_config_value(key, encoded, "")
        assert decoded == "sk-secret-value"


def test_encode_app_config_skips_empty_sensitive_values(monkeypatch):
    """Empty strings and None are stored as-is, not encrypted."""
    monkeypatch.setenv(ENV_KEY, Fernet.generate_key().decode("ascii"))
    _set_local_mode(monkeypatch)

    assert reg._encode_app_config_value("tavily_api_key", "") == json.dumps("")
    assert reg._decode_app_config_value("tavily_api_key", json.dumps(""), "") == ""


def test_encode_app_config_passthrough_in_server_mode(monkeypatch):
    """Server mode stores plaintext (no encryption)."""
    _set_server_mode(monkeypatch)

    encoded = reg._encode_app_config_value("tavily_api_key", "sk-server-secret")
    assert encoded == json.dumps("sk-server-secret")
    assert reg._decode_app_config_value(
        "tavily_api_key", json.dumps("sk-server-secret"), ""
    ) == "sk-server-secret"


def test_encode_app_config_does_not_encrypt_non_sensitive_keys(monkeypatch):
    """Non-sensitive keys (smtp_host, smtp_port, …) are never encrypted."""
    monkeypatch.setenv(ENV_KEY, Fernet.generate_key().decode("ascii"))
    _set_local_mode(monkeypatch)

    for key, value in [("smtp_host", "smtp.example.com"), ("smtp_port", 587)]:
        encoded = reg._encode_app_config_value(key, value)
        assert encoded == json.dumps(value)
        assert not encoded.startswith(FERNET_PREFIX)


def test_decode_app_config_handles_plaintext_legacy_rows(monkeypatch):
    """Old plaintext rows (pre-encryption) read fine in local mode."""
    monkeypatch.setenv(ENV_KEY, Fernet.generate_key().decode("ascii"))
    _set_local_mode(monkeypatch)

    # A pre-encryption DB stored the value as plain JSON (no Fernet token).
    legacy_raw = json.dumps("tvly-legacy-plaintext")
    decoded = reg._decode_app_config_value("tavily_api_key", legacy_raw, "")
    assert decoded == "tvly-legacy-plaintext"


def test_decode_app_config_returns_default_for_none(monkeypatch):
    """Missing rows (None raw) return the default."""
    monkeypatch.setenv(ENV_KEY, Fernet.generate_key().decode("ascii"))
    _set_local_mode(monkeypatch)

    assert reg._decode_app_config_value("tavily_api_key", None, "fallback") == "fallback"
