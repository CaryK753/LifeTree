"""Tenant / current-user resolution.

All interactive API requests require a real registered account. The legacy
default-user helper remains only for non-request migration/background code.

Two resolution modes:

  1. **Authenticated** — FastAPI dependency ``get_current_user()`` reads
     ``Authorization: Bearer <jwt>``, decodes the JWT, fetches the
     ``UserProfile`` from DB, and applies env-admin overrides.

  2. **Anonymous request** — always rejected with 401 in both runtime modes.

  3. ``get_default_user()`` is also used by Celery tasks and other
     non-request code that has no request context.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import TOKEN_TYPE_ACCESS, decode_token
from app.db.postgres import get_db
from app.models.user import UserProfile

log = get_logger(__name__)

#: Fixed UUID for the single default user. Pinned so re-seeding the database
#: does not invalidate references in backups, exports, or client state.
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

#: Display name used when bootstrapping a fresh default user.
DEFAULT_DISPLAY_NAME = "Alex Chen"
DEFAULT_EMAIL = "alex@example.com"


def get_default_user(db: Session) -> UserProfile:
    """Return the single default user, creating it on first call if needed.

    Resolution order:
      1. ``UserProfile`` with id == ``DEFAULT_USER_ID``
      2. The first ``UserProfile`` row (legacy seed data without pinned ID)
      3. Create a new row with ``DEFAULT_USER_ID``

    The default user has ``role="user"``; admin rights are granted at
    request time via ``_apply_admin_override`` (env-driven) so that
    fallback in single-user mode still gets admin powers without the
    default-user row itself being privileged.
    """
    user = db.get(UserProfile, DEFAULT_USER_ID)
    if user is not None:
        return user

    existing = db.scalars(select(UserProfile).limit(1)).first()
    if existing is not None:
        # Legacy seed row with a random UUID — adopt it in place.
        return existing

    user = UserProfile(
        id=DEFAULT_USER_ID,
        display_name=DEFAULT_DISPLAY_NAME,
        email=DEFAULT_EMAIL,
        risk_tolerance="medium",
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _apply_admin_override(user: UserProfile) -> UserProfile:
    """Promote ``user`` to admin if their id is in the env-configured admin list.

    This makes the env var the source of truth for admin promotion — admins
    don't need DB edits, just an .env entry. The DB ``role`` column is
    downstream of this override.
    """
    settings = get_settings()
    if user.id in settings.admin_user_ids and user.role != "admin":
        user.role = "admin"
    return user


def _allow_default_user_fallback() -> bool:
    """Interactive requests never use the legacy default account."""
    return False


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> UserProfile:
    """FastAPI dependency: resolve the current user from a Bearer JWT.

    Returns 401 when:
      - No ``Authorization`` header
      - Token is invalid/expired
      - User doesn't exist or is disabled
    """
    # ---------- No Authorization header ----------
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    claims = decode_token(token)
    if claims is None or claims.get("type") != TOKEN_TYPE_ACCESS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token claims")

    user = db.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user.is_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    return _apply_admin_override(user)


def get_optional_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> UserProfile | None:
    """Resolve a user when present, without rejecting an anonymous multi-user request."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return get_current_user(db, authorization)


def get_admin_user(
    user: Annotated[UserProfile, Depends(get_current_user)],
) -> UserProfile:
    """FastAPI dependency: require admin role. Use for /admin/* endpoints."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# Convenience type alias for handlers.
CurrentUser = Annotated[UserProfile, Depends(get_current_user)]
OptionalCurrentUser = Annotated[UserProfile | None, Depends(get_optional_current_user)]
AdminUser = Annotated[UserProfile, Depends(get_admin_user)]
