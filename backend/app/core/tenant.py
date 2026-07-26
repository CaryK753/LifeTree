"""Single-user / default-tenant helpers.

LifeTree is a single-user app: there is exactly one ``UserProfile`` row that
owns all goals, notifications, and uploads. This module centralizes the
resolution of that user so API handlers don't have to thread ``user_id``
through every request.

If you ever add real multi-tenancy, replace the helpers below with
request-scoped tenant resolution.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import UserProfile

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
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
