"""User memory CRUD endpoints.

Memories are the unbounded "remember this" channel — free-form facts the
advisor LLM can write to during chat (via the `remember` tool) and the user
can edit on the profile page.

Multi-user isolation: all endpoints resolve the authenticated user via
``CurrentUser`` and filter memories by ``user.id``. In single-user mode
``CurrentUser`` falls back to the default user, so behavior is unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.memory import UserMemory
from app.schemas.entities import (
    UserMemoryCreate,
    UserMemoryRead,
    UserMemoryUpdate,
)

router = APIRouter(prefix="/memories", tags=["memories"])


@router.post("", response_model=UserMemoryRead, status_code=201)
def create_memory(
    payload: UserMemoryCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> UserMemory:
    # Always associate the memory with the authenticated user, ignoring
    # any client-supplied user_id to prevent cross-user pollution.
    mem = UserMemory(**payload.model_dump(exclude={"user_id"}), user_id=user.id)
    db.add(mem)
    db.commit()
    db.refresh(mem)
    return mem


@router.get("", response_model=list[UserMemoryRead])
def list_memories(
    user: CurrentUser,
    category: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[UserMemory]:
    """List memories for the authenticated user, newest first.

    Optional ``category`` filter. Limited to 1000 rows — this is a profile
    page view, not a bulk export.
    """
    stmt = select(UserMemory).where(UserMemory.user_id == user.id)
    if category:
        stmt = stmt.where(UserMemory.category == category)
    stmt = stmt.order_by(UserMemory.importance.desc(), UserMemory.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


@router.patch("/{memory_id}", response_model=UserMemoryRead)
def update_memory(
    memory_id: str,
    payload: UserMemoryUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> UserMemory:
    mem = db.get(UserMemory, memory_id)
    if mem is None:
        raise HTTPException(404, "Memory not found")
    if mem.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this memory")
    # Prevent user_id reassignment.
    updates = payload.model_dump(exclude_unset=True)
    updates.pop("user_id", None)
    for k, v in updates.items():
        setattr(mem, k, v)
    db.commit()
    db.refresh(mem)
    return mem


@router.delete("/{memory_id}", status_code=204)
def delete_memory(
    memory_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> None:
    mem = db.get(UserMemory, memory_id)
    if mem is None:
        raise HTTPException(404, "Memory not found")
    if mem.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this memory")
    db.delete(mem)
    db.commit()
