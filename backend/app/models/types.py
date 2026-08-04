"""Dialect-aware ORM types shared by server and local runtimes."""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import TypeDecorator

# Keep PostgreSQL's indexed JSONB representation on servers while allowing
# SQLite JSON1 to persist the same Python dictionaries and lists locally.
JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type: Vector, _compiler: object, **_kwargs: object) -> str:
    """Allow schema creation; local vector search remains a separate adapter."""
    return "TEXT"


class EncryptedText(TypeDecorator):
    """Text column transparently encrypted at rest in local storage mode.

    - ``local`` mode: values are Fernet-encrypted on write and decrypted on
      read, so secrets in the SQLite file are unreadable without the keyring
      master key.
    - ``server`` mode: values pass through unchanged.
    - Empty strings and ``None`` are stored as-is.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN202
        if not value:
            return value
        from app.core.config import get_settings
        from app.core.local_encryption import get_encryption

        if get_settings().lifetree_storage_mode != "local":
            return value
        return get_encryption().encrypt(value)

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN202
        if not value:
            return value
        from app.core.config import get_settings
        from app.core.local_encryption import get_encryption

        if get_settings().lifetree_storage_mode != "local":
            return value
        return get_encryption().decrypt(value)


__all__ = ["JSON_DOCUMENT", "EncryptedText"]
