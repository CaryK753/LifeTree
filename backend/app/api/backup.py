"""Backup / restore / migration endpoints (P2 整库备份/恢复/导出迁移).

Exposes the ``BackupService`` over HTTP so users can download their data
as JSON / JSONL and re-import it (merge or replace). Admins can export
any user's data via ``/admin/export/{user_id}``.

Importing in ``replace`` mode requires a ``confirm=true`` flag in the
request body to prevent accidental data loss.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import AdminUser, CurrentUser
from app.db.postgres import get_db
from app.services.backup import BackupService

log = get_logger(__name__)

router = APIRouter(prefix="/backup", tags=["backup"])


# ---------- Schemas ----------


class ImportRequest(BaseModel):
    """Body for ``POST /backup/import``.

    ``confirm`` must be ``true`` when ``mode="replace"`` — the endpoint
    returns 400 otherwise. This is the server-side guard against an
    accidental "wipe and replace" click.
    """

    data: dict = Field(..., description="Exported backup payload.")
    mode: str = Field("merge", description='"merge" or "replace".')
    confirm: bool = Field(
        False, description="Required to be true when mode='replace'."
    )


# ---------- Endpoints ----------


@router.get("/export")
def export_my_data(
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    """Download the current user's data as a JSON attachment."""
    payload = BackupService(db).export_user_data(user.id)
    body = _json_dumps(payload)
    filename = _filename(user.id, "json")
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export-jsonl")
def export_my_data_jsonl(
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    """Download the current user's data as newline-delimited JSON."""
    body = BackupService(db).export_to_jsonl(user.id)
    filename = _filename(user.id, "jsonl")
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
def import_data(
    body: ImportRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    """Import a backup into the current user's account.

    ``mode="replace"`` requires ``confirm=true`` in the body.
    """
    if body.mode == "replace" and not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Replace mode requires confirm=true in the request body.",
        )
    if not isinstance(body.data, dict):
        raise HTTPException(status_code=422, detail="`data` must be a JSON object.")

    summary = BackupService(db).import_user_data(
        user_id=user.id,
        data=body.data,
        mode=body.mode,
    )
    log.info(
        "backup.import",
        user_id=user.id,
        mode=body.mode,
        imported=summary["imported"],
        errors=len(summary["errors"]),
    )
    return summary


@router.get("/admin/export/{user_id}")
def admin_export_user(
    user_id: str,
    admin: AdminUser,
    db: Session = Depends(get_db),
) -> Response:
    """Admin-only: export any user's data as a JSON attachment."""
    payload = BackupService(db).export_user_data(user_id)
    body = _json_dumps(payload)
    filename = _filename(user_id, "json")
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- helpers ----------


def _filename(user_id: str, ext: str) -> str:
    """Build a stable, filesystem-safe download filename."""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    short_id = (user_id or "anon")[:8]
    return f"lifetree-export-{short_id}-{date_str}.{ext}"


def _json_dumps(payload: dict) -> str:
    """Serialize with ``ensure_ascii=False`` so CJK content stays readable."""
    import json

    return json.dumps(payload, ensure_ascii=False, default=str)


__all__ = ["router"]
