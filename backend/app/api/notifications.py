"""Notification list / mark-read endpoints.

Multi-user isolation: all endpoints resolve the authenticated user via
``CurrentUser`` and filter notifications by ``user.id``. In single-user
mode ``CurrentUser`` falls back to the default user, so behavior is
unchanged. The legacy ``GET /notifications/{user_id}`` path form is kept
for backward compatibility but ignores the path user_id — the
authenticated user's notifications are always returned.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.notification import NotificationLog, WebPushSubscription
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


class PushSubscriptionBody(BaseModel):
    endpoint: str = Field(..., min_length=1, max_length=4096)
    p256dh: str = Field(..., min_length=1, max_length=4096)
    auth: str = Field(..., min_length=1, max_length=4096)
    user_agent: str | None = Field(None, max_length=512)


# ---------- Specific paths (registered BEFORE /{user_id} catch-all) ----------


@router.get("/channels/status")
def notification_channel_status(
    user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    from app.llm.registry import get_smtp_config
    from app.services.notification_channels import NotificationChannelService

    state = NotificationChannelService(db).status(user.id)
    smtp = get_smtp_config()
    state["email"] = {
        "available": bool(smtp.get("host") or NotificationService(db).settings.smtp_host),
        "recipient_configured": bool(user.email),
    }
    return state


@router.post("/push-subscriptions", status_code=201)
def upsert_push_subscription(
    payload: PushSubscriptionBody,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    row = db.scalar(select(WebPushSubscription).where(
        WebPushSubscription.endpoint == payload.endpoint
    ))
    if row is None:
        row = WebPushSubscription(user_id=user.id, endpoint=payload.endpoint)
    elif row.user_id != user.id:
        raise HTTPException(409, "Push endpoint already belongs to another user")
    row.p256dh = payload.p256dh
    row.auth = payload.auth
    row.user_agent = payload.user_agent
    row.enabled = True
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "enabled": row.enabled}


@router.get("/push-subscriptions")
def list_push_subscriptions(
    user: CurrentUser, db: Session = Depends(get_db)
) -> list[dict]:
    rows = list(db.scalars(
        select(WebPushSubscription)
        .where(WebPushSubscription.user_id == user.id)
        .order_by(WebPushSubscription.created_at.desc())
    ))
    return [
        {"id": row.id, "enabled": row.enabled, "user_agent": row.user_agent}
        for row in rows
    ]


@router.delete("/push-subscriptions/{subscription_id}", status_code=204)
def delete_push_subscription(
    subscription_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    row = db.get(WebPushSubscription, subscription_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Push subscription not found")
    db.delete(row)
    db.commit()


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> UnreadCountResponse:
    """Efficient single COUNT of unread notifications for the user."""
    return UnreadCountResponse(count=NotificationService(db).count_unread(user.id))


@router.post("/bulk-read", response_model=BulkReadResponse)
def bulk_mark_read(
    payload: BulkReadRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> BulkReadResponse:
    """Mark multiple notifications as read in a single UPDATE.

    Returns ``{"updated": N}`` where N is the number of rows actually
    changed (already-read rows are not counted).
    """
    updated = NotificationService(db).bulk_mark_read(user.id, payload.notification_ids)
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
    user: CurrentUser,
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
    """List recent notifications for the authenticated user.

    Supports server-side filtering by ``severity``, ``status``, ``channel``
    plus ``limit`` / ``offset`` pagination. The ``status`` query param
    accepts the special value ``unread`` which excludes READ and SUPPRESSED
    rows (SUPPRESSED rows are invisible to the user and shouldn't appear).
    """
    target = user.id
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
    user: CurrentUser,
    user_id: str,
    severity: str | None = Query(None),
    status: str | None = Query(None),
    channel: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[NotificationLog]:
    """Backward-compat: ``GET /notifications/{user_id}`` form.

    The path ``user_id`` is ignored — the authenticated user's
    notifications are always returned. This path form is kept so older
    builds keep working.
    """
    target = user.id
    service = NotificationService(db)
    severity = _normalize_severity(severity)
    if status == "unread":
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


# ---------- Single-notification mark-read ----------


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> NotificationLog:
    record = NotificationService(db).mark_read(notification_id, user.id)
    if record is None:
        raise HTTPException(404, "Notification not found")
    return record
