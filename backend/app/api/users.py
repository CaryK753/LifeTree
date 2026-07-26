"""User profile CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.models.user import UserProfile
from app.schemas.entities import (
    UserProfileCreate,
    UserProfileRead,
    UserProfileUpdate,
)
from app.services.profiling import ProfilingService

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserProfileRead, status_code=201)
def create_user(payload: UserProfileCreate, db: Session = Depends(get_db)) -> UserProfile:
    user = UserProfile(**payload.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    ProfilingService(db).refresh(user)
    return user


@router.get("", response_model=list[UserProfileRead])
def list_users(limit: int = 50, db: Session = Depends(get_db)) -> list[UserProfile]:
    return list(
        db.scalars(select(UserProfile).limit(limit).order_by(UserProfile.created_at.desc()))
    )


@router.get("/{user_id}", response_model=UserProfileRead)
def get_user(user_id: str, db: Session = Depends(get_db)) -> UserProfile:
    user = db.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return user


@router.patch("/{user_id}", response_model=UserProfileRead)
def update_user(
    user_id: str, payload: UserProfileUpdate, db: Session = Depends(get_db)
) -> UserProfile:
    user = db.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(user, k, v)
    db.commit()
    ProfilingService(db).refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: str, db: Session = Depends(get_db)) -> None:
    user = db.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
