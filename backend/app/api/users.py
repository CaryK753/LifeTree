"""User profile CRUD endpoints.

Multi-user isolation:
  - ``GET /users`` — any authenticated user; non-admins see only themselves.
  - ``GET / PATCH /users/{user_id}`` — own profile or admin.
  - ``POST / DELETE /users/{user_id}`` — admin only.

In single-user mode ``CurrentUser`` falls back to the default user, so
behavior is unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import CurrentUser, DEFAULT_USER_ID
from app.db.postgres import get_db
from app.models.user import UserProfile
from app.schemas.entities import (
    UserProfileCreate,
    UserProfileRead,
    UserProfileUpdate,
)
from app.services.profiling import ProfilingService

log = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


def _require_admin(user: CurrentUser) -> None:
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")


@router.post("", response_model=UserProfileRead, status_code=201)
def create_user(
    payload: UserProfileCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> UserProfile:
    _require_admin(user)
    new_user = UserProfile(**payload.model_dump())
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    ProfilingService(db).refresh(new_user)
    return new_user


@router.get("", response_model=list[UserProfileRead])
def list_users(
    user: CurrentUser, limit: int = 50, db: Session = Depends(get_db)
) -> list[UserProfile]:
    # Non-admins see only their own profile. Admins can list all users.
    if user.role != "admin":
        return [user]
    return list(
        db.scalars(select(UserProfile).limit(limit).order_by(UserProfile.created_at.desc()))
    )


@router.get("/{user_id}", response_model=UserProfileRead)
def get_user(
    user_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> UserProfile:
    target = db.get(UserProfile, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    # Users can read their own profile; admins can read any.
    if target.id != user.id and user.role != "admin":
        raise HTTPException(403, "You can only view your own profile")
    return target


@router.patch("/{user_id}", response_model=UserProfileRead)
def update_user(
    user_id: str,
    payload: UserProfileUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> UserProfile:
    target = db.get(UserProfile, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    # Users can update their own profile; admins can update any.
    if target.id != user.id and user.role != "admin":
        raise HTTPException(403, "You can only edit your own profile")
    # Prevent role escalation: only admins can change the role field.
    updates = payload.model_dump(exclude_unset=True)
    if "role" in updates and user.role != "admin":
        updates.pop("role")
    for k, v in updates.items():
        setattr(target, k, v)
    db.commit()
    ProfilingService(db).refresh(target)
    return target


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> None:
    _require_admin(user)
    target = db.get(UserProfile, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    db.delete(target)
    db.commit()


@router.delete("/me/destroy", status_code=204)
def destroy_my_data(
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    """One-click data destruction — wipes the current user's account and
    all user-scoped data (goals, scenarios, memories, uploads, notifications,
    risk assessments). Cascades are declared at the ORM level
    (``ondelete="CASCADE"`` on every user_id FK) so a single ``db.delete``
    cleans up the related rows.

    Implements §6 of the project plan: "一键销毁数据".

    Safeguards:
      - Refuses to delete the fixed default user
        (``00000000-...-000000000001``) — doing so in single-user mode
        would brick the app on next reload (``get_default_user`` would
        re-create an empty profile, losing all data anyway).
      - Refuses to delete the last remaining admin (same rule as the
        admin delete-user endpoint) so the platform isn't locked out.
    """
    if user.id == DEFAULT_USER_ID:
        raise HTTPException(
            status_code=400,
            detail="Cannot destroy the default user — use a real account in multi-user mode.",
        )

    if user.role == "admin":
        other_admins = db.scalars(
            select(UserProfile).where(
                UserProfile.role == "admin",
                UserProfile.id != user.id,
                UserProfile.is_enabled.is_(True),
            )
        ).all()
        if not other_admins:
            raise HTTPException(
                status_code=400,
                detail="Cannot destroy the last admin account.",
            )

    db.delete(user)
    db.commit()
    log.info("user.self_destroyed", user_id=user.id)
