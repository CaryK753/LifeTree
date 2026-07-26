"""Notification list / mark-read endpoints.

Single-user mode: endpoints default to the default user when ``user_id`` is
not supplied. The ``GET /notifications/{user_id}`` path form is kept for
backward compatibility; new clients should call ``GET /notifications``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.tenant import get_default_user
from app.db.postgres import get_db
from app.models.notification import NotificationLog
from app.schemas.api import NotificationRead
from app.services.notification import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


class BulkReadRequest(BaseModel):
    """Body for ``POST /notifications/bulk-read``."""

    notification_ids: list[str] = Field(default_factory=list)


class BulkReadResponse(BaseModel):
    updated: int


class UnreadCountResponse(BaseModel):
    count: int


# ---------- Specific paths (registered BEFORE /{user_id} catch-all) ----------


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    user_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> UnreadCountResponse:
    """Efficient single COUNT of unread notifications for the user."""
    target = user_id or get_default_user(db).id
    return UnreadCountResponse(count=NotificationService(db).count_unread(target))


@router.post("/bulk-read", response_model=BulkReadResponse)
def bulk_mark_read(
    payload: BulkReadRequest,
    user_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> BulkReadResponse:
    """Mark multiple notifications as read in a single UPDATE.

    Returns ``{"updated": N}`` where N is the number of rows actually
    changed (already-read rows are not counted).
    """
    target = user_id or get_default_user(db).id
    updated = NotificationService(db).bulk_mark_read(target, payload.notification_ids)
    return BulkReadResponse(updated=updated)


# ---------- List (with server-side filtering) ----------


def _normalize_severity(value: str | None) -> str | None:
    """Normalize the public severity vocabulary to the DB vocabulary.

    The DB stores ``info | warning | critical`` (per NotificationLog.severity).
    The public API also accepts ``urgent`` as an alias for ``critical`` so
    callers using the urgency vocabulary get the expected results.
    """
    if value is None:
        return None
    if value == "urgent":
        return "critical"
    return value


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    severity: str | None = Query(
        None,
        description="Filter by severity: urgent | warning | info",
    ),
    status: str | None = Query(
        None,
        description="Filter by status: read | unread",
    ),
    channel: str | None = Query(
        None,
        description="Filter by channel: email | in_app | sms | push",
    ),
    limit: int = Query(50, ge=1, le=200, description="Max results (1..200)"),
    offset: int = Query(0, ge=0, description="Skip this many results"),
    db: Session = Depends(get_db),
) -> list[NotificationLog]:
    """List recent notifications for the default user.

    Supports server-side filtering by ``severity``, ``status``, ``channel``
    plus ``limit`` / ``offset`` pagination. The ``status`` query param
    accepts the special value ``unread`` which excludes READ and SUPPRESSED
    rows (SUPPRESSED rows are invisible to the user and shouldn't appear).
    """
    target = get_default_user(db).id
    service = NotificationService(db)
    severity = _normalize_severity(severity)

    if status == "unread":
        # "unread" can't be expressed as a single equality on the status
        # column (which stores pending|sent|failed|suppressed|read). Fetch
        # without the status filter and exclude READ/SUPPRESSED in Python.
        rows = service.list_filtered(
            target,
            severity=severity,
            status=None,
            channel=channel,
            limit=limit,
            offset=offset,
        )
        return [r for r in rows if r.status not in {"read", "suppressed"}]

    return service.list_filtered(
        target,
        severity=severity,
        status="read" if status == "read" else None,
        channel=channel,
        limit=limit,
        offset=offset,
    )


# ---------- Backward-compat path form (must come AFTER specific paths) ----------


@router.get(
    "/{user_id}",
    response_model=list[NotificationRead],
    include_in_schema=False,
)
def list_notifications_for_user(
    user_id: str,
    severity: str | None = Query(None),
    status: str | None = Query(None),
    channel: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[NotificationLog]:
    """Backward-compat: ``GET /notifications/{user_id}`` form.

    New clients should call ``GET /notifications`` and let the default-user
    resolution handle it. This path form is kept so older builds keep working.
    """
    service = NotificationService(db)
    severity = _normalize_severity(severity)
    if status == "unread":
        rows = service.list_filtered(
            user_id,
            severity=severity,
            status=None,
            channel=channel,
            limit=limit,
            offset=offset,
        )
        return [r for r in rows if r.status not in {"read", "suppressed"}]
    return service.list_filtered(
        user_id,
        severity=severity,
        status="read" if status == "read" else None,
        channel=channel,
        limit=limit,
        offset=offset,
    )


# ---------- Single-notification mark-read ----------


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
