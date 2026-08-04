"""Application-layer field encryption for the local desktop runtime.

Secrets stored in the local SQLite database (LLM API keys, SMTP passwords,
third-party tokens) are encrypted at rest with Fernet (AES-128-CBC +
HMAC-SHA256). The master key lives in the OS Keychain / Credential Manager
via :class:`SystemSecretStore`, so copying the SQLite file alone is not
enough to recover the secrets.

Key resolution order:
1. ``LIFETREE_LOCAL_ENCRYPTION_KEY`` env var (testing / headless only).
2. OS credential store via :class:`SystemSecretStore` (desktop default).
3. If neither is available, local private mode refuses to start.

Only enabled in ``local`` storage mode; ``server`` mode is unaffected.
"""

from __future__ import annotations

import functools
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.secret_store import SecretStoreUnavailableError, SystemSecretStore

# Fernet tokens are base64url and always start with this prefix after the
# version byte. Used to detect already-encrypted values during reads so a
# plaintext database can be upgraded in place.
FERNET_PREFIX = "gAAAAA"

ENV_KEY = "LIFETREE_LOCAL_ENCRYPTION_KEY"


class EncryptionError(RuntimeError):
    """Raised when encryption is misconfigured or decryption fails."""


class LocalEncryption:
    """Encrypt and decrypt string fields using a keyring-backed master key."""

    KEYRING_KEY = "local-db-encryption-key"

    def __init__(self, secret_store: SystemSecretStore | None = None) -> None:
        self._store = secret_store
        self._fernet: Fernet | None = None

    def _get_or_create_fernet(self) -> Fernet:
        if self._fernet is not None:
            return self._fernet

        # 1. Env var (testing / headless).
        env_key = os.environ.get(ENV_KEY)
        if env_key:
            self._fernet = self._build_fernet(env_key)
            return self._fernet

        # 2. OS credential store.
        if self._store is None:
            self._store = SystemSecretStore()
        key = self._store.get(self.KEYRING_KEY)
        if key is None:
            key = Fernet.generate_key().decode("ascii")
            self._store.set(self.KEYRING_KEY, key)
        self._fernet = self._build_fernet(key)
        return self._fernet

    @staticmethod
    def _build_fernet(key: str) -> Fernet:
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise EncryptionError(
                "Stored local encryption key is malformed; remove it from the "
                "system credential store (or unset the env var) and restart."
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a non-empty plaintext string.

        Empty strings and ``None`` are returned as-is so nullable columns
        are not affected. Values that already look like Fernet tokens are
        returned unchanged (idempotent re-encryption).
        """
        if not plaintext:
            return plaintext
        if plaintext.startswith(FERNET_PREFIX):
            return plaintext
        return self._get_or_create_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        """Decrypt a Fernet token, returning plaintext.

        Values that do not look like Fernet tokens are returned unchanged
        (supports upgrading a plaintext database: old rows read fine, and
        are re-encrypted on the next write).
        """
        if not value or not value.startswith(FERNET_PREFIX):
            return value
        try:
            return self._get_or_create_fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise EncryptionError(
                "Failed to decrypt a local field. The encryption key may have "
                "changed or the data is corrupted."
            ) from exc


@functools.lru_cache(maxsize=1)
def _default_encryption() -> LocalEncryption:
    """Process-wide singleton; created on first use."""
    return LocalEncryption()


def get_encryption() -> LocalEncryption:
    """Return the process-wide :class:`LocalEncryption` instance."""
    return _default_encryption()


def reset_encryption_cache() -> None:
    """Clear the singleton (used by tests that swap the keyring backend)."""
    _default_encryption.cache_clear()


def ensure_encryption_available() -> None:
    """Eagerly initialise the master key, raising if no source is usable."""
    try:
        get_encryption().encrypt("probe")
    except SecretStoreUnavailableError as exc:
        raise EncryptionError(
            "Local private mode requires a master key: set the "
            f"{ENV_KEY} env var (testing) or enable the OS credential store "
            "(macOS Keychain / Windows Credential Manager)."
        ) from exc


__all__ = [
    "ENV_KEY",
    "EncryptionError",
    "FERNET_PREFIX",
    "LocalEncryption",
    "ensure_encryption_available",
    "get_encryption",
    "reset_encryption_cache",
]
