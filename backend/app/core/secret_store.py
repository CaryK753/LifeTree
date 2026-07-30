"""System credential-store adapter reserved for local/private runtime secrets."""

from __future__ import annotations


class SecretStoreUnavailableError(RuntimeError):
    """Raised when the operating system has no usable credential backend."""


class SystemSecretStore:
    """Store secrets in Keychain/Credential Manager through ``keyring``."""

    def __init__(self, service_name: str = "LifeTree") -> None:
        try:
            import keyring
        except ImportError as exc:
            raise SecretStoreUnavailableError(
                "Install the local dependency set with pip install -e '.[local]'"
            ) from exc

        backend = keyring.get_keyring()
        if getattr(backend, "priority", 0) <= 0:
            raise SecretStoreUnavailableError("No supported system credential store is available")
        self._keyring = keyring
        self._service_name = service_name

    def get(self, key: str) -> str | None:
        return self._keyring.get_password(self._service_name, key)

    def set(self, key: str, value: str) -> None:
        self._keyring.set_password(self._service_name, key, value)

    def delete(self, key: str) -> bool:
        try:
            self._keyring.delete_password(self._service_name, key)
        except self._keyring.errors.PasswordDeleteError:
            return False
        return True


__all__ = ["SecretStoreUnavailableError", "SystemSecretStore"]
