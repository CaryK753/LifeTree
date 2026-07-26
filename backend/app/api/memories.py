"""User memory CRUD endpoints.

Memories are the unbounded "remember this" channel — free-form facts the
advisor LLM can write to during chat (via the `remember` tool) and the user
can edit on the profile page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import get_default_user
from app.db.postgres import get_db
from app.models.memory import UserMemory
from app.schemas.entities import (
    UserMemoryCreate,
    UserMemoryRead,
    UserMemoryUpdate,
)

router = APIRouter(prefix="/memories", tags=["memories"])


def _resolve_user(db: Session, user_id: str | None) -> str:
    if user_id:
        return user_id
    return get_default_user(db).id


@router.post("", response_model=UserMemoryRead, status_code=201)
def create_memory(
    payload: UserMemoryCreate, db: Session = Depends(get_db)
) -> UserMemory:
    user_id = _resolve_user(db, payload.user_id)
    mem = UserMemory(**payload.model_dump(exclude={"user_id"}), user_id=user_id)
    db.add(mem)
    db.commit()
    db.refresh(mem)
    return mem


@router.get("", response_model=list[UserMemoryRead])
def list_memories(
    category: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[UserMemory]:
    """List memories for the default user, newest first.

    Optional ``category`` filter. Limited to 1000 rows — this is a profile
    page view, not a bulk export.
    """
    user_id = _resolve_user(db, None)
    stmt = select(UserMemory).where(UserMemory.user_id == user_id)
    if category:
        stmt = stmt.where(UserMemory.category == category)
    stmt = stmt.order_by(UserMemory.importance.desc(), UserMemory.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


@router.patch("/{memory_id}", response_model=UserMemoryRead)
def update_memory(
    memory_id: str, payload: UserMemoryUpdate, db: Session = Depends(get_db)
) -> UserMemory:
    mem = db.get(UserMemory, memory_id)
    if mem is None:
        raise HTTPException(404, "Memory not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(mem, k, v)
    db.commit()
    db.refresh(mem)
    return mem


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: str, db: Session = Depends(get_db)) -> None:
    mem = db.get(UserMemory, memory_id)
    if mem is None:
        raise HTTPException(404, "Memory not found")
    db.delete(mem)
    db.commit()
