"""Notification list / mark-read endpoints.

Single-user mode: endpoints default to the default user when ``user_id`` is
not supplied. The ``GET /notifications/{user_id}`` path form is kept for
backward compatibility; new clients should call ``GET /notifications``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenant import get_default_user
from app.db.postgres import get_db
from app.models.notification import NotificationLog
from app.schemas.api import NotificationRead
from app.services.notification import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
@router.get("/{user_id}", response_model=list[NotificationRead], include_in_schema=False)
def list_notifications(
    user_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[NotificationLog]:
    """List recent notifications for the default user (or the one given)."""
    target = user_id or get_default_user(db).id
    return NotificationService(db).list_recent(target, limit=limit)


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: str,
    user_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> NotificationLog:
    target = user_id or get_default_user(db).id
    record = NotificationService(db).mark_read(notification_id, target)
    if record is None:
        raise HTTPException(404, "Notification not found")
    return record
