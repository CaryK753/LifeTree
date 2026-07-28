"""User Skill CRUD and import endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.user_runtime import UserSkill
from app.services.skill_import import (
    MAX_SKILL_BYTES,
    import_archive,
    import_file_set,
    import_github,
)

router = APIRouter(prefix="/settings/skills", tags=["user-skills"])
DbSession = Annotated[Session, Depends(get_db)]


class SkillTextCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    content: str = Field(..., min_length=1, max_length=MAX_SKILL_BYTES)


class SkillGithubCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    repository_url: HttpUrl


class SkillToggle(BaseModel):
    enabled: bool


def _view(row: UserSkill) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "source_type": row.source_type,
        "source_ref": row.source_ref,
        "enabled": row.enabled,
        "content_preview": row.content[:240],
        "created_at": row.created_at.isoformat(),
    }


def _create(
    db: Session, user_id: str, name: str, source_type: str,
    content: str, source_ref: str = "",
) -> dict[str, Any]:
    row = UserSkill(
        user_id=user_id, name=name.strip(), source_type=source_type,
        source_ref=source_ref, content=content,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _view(row)


@router.get("")
def list_skills(user: CurrentUser, db: DbSession) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(UserSkill)
        .where(UserSkill.user_id == user.id)
        .order_by(UserSkill.created_at.desc())
    )
    return [_view(row) for row in rows]


@router.post("/text", status_code=201)
def create_text_skill(
    payload: SkillTextCreate, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    return _create(db, user.id, payload.name, "text", payload.content)


@router.post("/github", status_code=201)
def create_github_skill(
    payload: SkillGithubCreate, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    url = str(payload.repository_url)
    try:
        content = import_github(url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _create(db, user.id, payload.name, "github", content, url)


@router.post("/archive", status_code=201)
async def create_archive_skill(
    user: CurrentUser,
    db: DbSession,
    name: Annotated[str, Form(min_length=1, max_length=128)],
    archive: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    raw = await archive.read(MAX_SKILL_BYTES + 1)
    try:
        content = import_archive(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _create(db, user.id, name, "archive", content, archive.filename or "")


@router.post("/folder", status_code=201)
async def create_folder_skill(
    user: CurrentUser,
    db: DbSession,
    name: Annotated[str, Form(min_length=1, max_length=128)],
    files: Annotated[list[UploadFile], File()],
) -> dict[str, Any]:
    imported: list[tuple[str, bytes]] = []
    total = 0
    for file in files:
        raw = await file.read(MAX_SKILL_BYTES + 1)
        total += len(raw)
        if total > MAX_SKILL_BYTES:
            raise HTTPException(400, "Skill folder exceeds 2 MiB")
        imported.append((file.filename or "unnamed.txt", raw))
    try:
        content = import_file_set(imported)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _create(db, user.id, name, "folder", content)


@router.patch("/{skill_id}")
def toggle_skill(
    skill_id: str, payload: SkillToggle, user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    row = db.get(UserSkill, skill_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Skill not found")
    row.enabled = payload.enabled
    db.commit()
    db.refresh(row)
    return _view(row)


@router.delete("/{skill_id}", status_code=204)
def delete_skill(
    skill_id: str, user: CurrentUser, db: DbSession
) -> None:
    row = db.get(UserSkill, skill_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Skill not found")
    db.delete(row)
    db.commit()
