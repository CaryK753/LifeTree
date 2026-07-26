"""Admin-only endpoints: user management and platform overview.

All endpoints require the ``admin`` role (resolved via ``AdminUser`` dependency).
Admin promotion is configured via the ``LIFETREE_ADMIN_USER_IDS`` env var.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import hash_password
from app.core.tenant import AdminUser
from app.db.postgres import get_db
from app.models.user import UserProfile
from app.schemas.entities import UserProfileRead

log = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- Schemas ----------

class AdminUserRead(UserProfileRead):
    """Extended user view for admins — includes auth fields."""

    role: str
    is_enabled: bool
    has_password: bool


class AdminUserUpdate(BaseModel):
    """Admin can update role / enabled / password / display_name."""

    display_name: str | None = None
    role: str | None = Field(None, description='"admin" or "user"')
    is_enabled: bool | None = None
    new_password: str | None = Field(None, min_length=6, max_length=128)


class AdminStats(BaseModel):
    """Platform overview stats."""

    total_users: int
    enabled_users: int
    admin_users: int
    disabled_users: int


# ---------- Endpoints ----------

@router.get("/stats", response_model=AdminStats)
def admin_stats(admin: AdminUser, db: Session = Depends(get_db)) -> AdminStats:
    """Return platform-wide user statistics."""
    users = list(db.scalars(select(UserProfile)))
    return AdminStats(
        total_users=len(users),
        enabled_users=sum(1 for u in users if u.is_enabled),
        admin_users=sum(1 for u in users if u.role == "admin"),
        disabled_users=sum(1 for u in users if not u.is_enabled),
    )


@router.get("/users", response_model=list[AdminUserRead])
def admin_list_users(
    admin: AdminUser,
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
) -> list[UserProfile]:
    """List all users (admin only)."""
    return list(
        db.scalars(
            select(UserProfile)
            .order_by(UserProfile.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )


@router.patch("/users/{user_id}", response_model=AdminUserRead)
def admin_update_user(
    user_id: str,
    payload: AdminUserUpdate,
    admin: AdminUser,
    db: Session = Depends(get_db),
) -> UserProfile:
    """Update a user's role / enabled / password (admin only).

    Admins can promote/demote other users, enable/disable accounts, and
    reset passwords. Self-demotion is allowed but blocked if it would
    leave zero admins.
    """
    user = db.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()

    if payload.role is not None:
        if payload.role not in ("admin", "user"):
            raise HTTPException(status_code=400, detail="role must be 'admin' or 'user'")
        # Block self-demotion that would leave zero admins
        if (
            admin.id == user.id
            and payload.role == "user"
            and user.role == "admin"
        ):
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
                    detail="Cannot demote yourself — you are the only admin",
                )
        user.role = payload.role

    if payload.is_enabled is not None:
        # Block self-disable that would leave zero admins
        if (
            admin.id == user.id
            and not payload.is_enabled
            and user.role == "admin"
        ):
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
                    detail="Cannot disable yourself — you are the only admin",
                )
        user.is_enabled = payload.is_enabled

    if payload.new_password is not None:
        user.password_hash = hash_password(payload.new_password)

    db.commit()
    db.refresh(user)
    log.info(
        "admin.user_updated",
        target=user_id,
        admin=admin.id,
        role=payload.role,
        enabled=payload.is_enabled,
        password_reset=payload.new_password is not None,
    )
    return user


@router.delete("/users/{user_id}", status_code=204)
def admin_delete_user(
    user_id: str,
    admin: AdminUser,
    db: Session = Depends(get_db),
) -> None:
    """Hard-delete a user account (admin only).

    Blocked if the target is the calling admin or the last remaining admin.
    """
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    user = db.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

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
                detail="Cannot delete the last admin",
            )

    db.delete(user)
    db.commit()
    log.info("admin.user_deleted", target=user_id, admin=admin.id)


__all__ = ["router"]
