"""Authentication security primitives: password hashing and JWT tokens.

Uses ``bcrypt`` directly for password hashing and python-jose for JWT
encoding/decoding. Tokens are HS256-signed with ``app_secret_key``.

Two token types:
  - **access** (short-lived, 24h default): sent in ``Authorization: Bearer``,
    used to authenticate API requests.
  - **refresh** (long-lived, 30d default): used only at ``POST /auth/refresh``
    to mint a new access token without re-entering the password.

Why not passlib:
  - passlib's bcrypt backend introspects ``bcrypt.__about__.__version__``,
    which was removed in bcrypt 4.x. The fallback path then calls
    ``bcrypt.hashpw`` with a 73-byte detection string and raises
    ``ValueError: password cannot be longer than 72 bytes``. Using
    bcrypt directly sidesteps the incompatibility entirely.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

ALGORITHM = "HS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# bcrypt has a hard 72-byte input limit. We truncate to 72 bytes (UTF-8)
# before hashing so long passwords don't raise. This matches what most
# production bcrypt wrappers do silently.
_BCRYPT_MAX_PW_BYTES = 72


def _truncate_for_bcrypt(plain: str) -> bytes:
    raw = plain.encode("utf-8")
    return raw[:_BCRYPT_MAX_PW_BYTES]


def hash_password(plain: str) -> str:
    """Return bcrypt hash of ``plain`` password."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(_truncate_for_bcrypt(plain), salt).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    """Return True if ``plain`` matches ``hashed``.

    Returns False if ``hashed`` is None (legacy user without a password).
    """
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(
            _truncate_for_bcrypt(plain), hashed.encode("utf-8")
        )
    except ValueError:
        # Malformed hash string — treat as no match.
        return False


def _create_token(
    *,
    subject: str,
    token_type: Literal["access", "refresh"],
    ttl: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Build and sign a JWT."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    claims: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, settings.app_secret_key.get_secret_value(), algorithm=ALGORITHM)


def create_access_token(
    user_id: str, *, role: str = "user", extra_claims: dict[str, Any] | None = None
) -> str:
    """Mint a short-lived access token for ``user_id``."""
    settings = get_settings()
    ttl = timedelta(minutes=settings.auth_access_token_ttl_minutes)
    claims = {"role": role}
    if extra_claims:
        claims.update(extra_claims)
    return _create_token(subject=user_id, token_type=TOKEN_TYPE_ACCESS, ttl=ttl, extra_claims=claims)


def create_refresh_token(user_id: str) -> str:
    """Mint a long-lived refresh token for ``user_id``."""
    settings = get_settings()
    ttl = timedelta(days=settings.auth_refresh_token_ttl_days)
    return _create_token(subject=user_id, token_type=TOKEN_TYPE_REFRESH, ttl=ttl)


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT. Returns claims dict, or None if invalid/expired."""
    settings = get_settings()
    try:
        claims = jwt.decode(
            token, settings.app_secret_key.get_secret_value(), algorithms=[ALGORITHM]
        )
        return claims
    except JWTError as exc:
        log.debug("auth.jwt_decode_failed", error=str(exc))
        return None


__all__ = [
    "ALGORITHM",
    "TOKEN_TYPE_ACCESS",
    "TOKEN_TYPE_REFRESH",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
