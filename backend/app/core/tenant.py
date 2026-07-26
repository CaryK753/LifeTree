"""Tenant / current-user resolution.

This module bridges the legacy single-user ``get_default_user()`` helper
and the new multi-user auth flow.

Two resolution modes:

  1. **Authenticated** — FastAPI dependency ``get_current_user()`` reads
     ``Authorization: Bearer <jwt>``, decodes the JWT, fetches the
     ``UserProfile`` from DB, and applies env-admin overrides.
     Falls back to default user when ``auth_allow_default_user_fallback=True``
     and no Authorization header is present (legacy single-user mode).

  2. **Legacy default user** — ``get_default_user()`` still returns the
     fixed UUID ``00000000-...-000000000001`` user. Used by Celery tasks
     and other non-request code that has no request context.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import decode_token, TOKEN_TYPE_ACCESS
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
        role="admin",
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


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> UserProfile:
    """FastAPI dependency: resolve the current user from a Bearer JWT.

    Falls back to the default user when:
      - No ``Authorization`` header is sent, AND
      - ``auth_allow_default_user_fallback`` is True (legacy single-user mode).

    Returns 401 if:
      - No header + fallback disabled, OR
      - Token is invalid/expired, OR
      - User doesn't exist or is disabled.
    """
    settings = get_settings()

    # ---------- No Authorization header → maybe default-user fallback ----------
    if not authorization or not authorization.lower().startswith("bearer "):
        if settings.auth_allow_default_user_fallback:
            return _apply_admin_override(get_default_user(db))
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
AdminUser = Annotated[UserProfile, Depends(get_admin_user)]
