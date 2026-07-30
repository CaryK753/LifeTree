"""Changes-summary endpoints — "since last visit" aggregate digest.

Surfaces ``ChangesSummaryService`` via two routes:

  * ``GET /changes-summary`` — aggregate counts/lists since the given
    timestamp (defaults to the stored last-visit, or 7 days ago if none).
    After computing, the user's ``last_visit_at`` is bumped to now() so
    the next call reflects only changes that happened *after* this visit.
  * ``GET /changes-summary/last-visit`` — returns the stored last-visit
    timestamp (ISO-8601) or null if never set.

The last-visit timestamp is persisted in the ``app_config`` key/value
table under ``user_last_visit:{user_id}`` because ``UserProfile`` has no
generic ``meta`` JSONB column. Values are stored as JSON-encoded strings
to match the convention used by other AppConfig entries.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.llm_config import AppConfig
from app.services.changes_summary import ChangesSummaryService

log = get_logger(__name__)

router = APIRouter(prefix="/changes-summary", tags=["changes-summary"])

#: Look-back window when no last-visit timestamp is stored yet.
DEFAULT_LOOKBACK_DAYS = 7


def _config_key(user_id: str) -> str:
    """AppConfig key under which the user's last-visit timestamp is stored."""
    return f"user_last_visit:{user_id}"


def _read_last_visit(db: Session, user_id: str) -> datetime | None:
    """Return the stored last-visit timestamp, or None if never set."""
    row = db.scalar(
        select(AppConfig).where(AppConfig.key == _config_key(user_id))
    )
    if row is None or not row.value:
        return None
    try:
        raw = json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    ts = raw.get("last_visit_at")
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _write_last_visit(db: Session, user_id: str, ts: datetime) -> None:
    """Persist (upsert) the last-visit timestamp for ``user_id``."""
    key = _config_key(user_id)
    value = json.dumps({"last_visit_at": ts.isoformat()})
    row = db.scalar(select(AppConfig).where(AppConfig.key == key))
    if row is None:
        row = AppConfig(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


@router.get("")
def get_changes_summary(
    user: CurrentUser,
    since: datetime | None = Query(
        None,
        description=(
            "ISO-8601 timestamp. Defaults to the stored last-visit, "
            f"or {DEFAULT_LOOKBACK_DAYS} days ago if never set."
        ),
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Aggregate changes digest since ``since`` (or last-visit / 7d ago).

    On a successful response the user's ``last_visit_at`` is updated to
    now() so the next call reflects only changes after this visit. The
    returned payload includes the ``since`` value actually used so the
    client can render "自上次访问 <since> 以来…".
    """
    if since is None:
        since = _read_last_visit(db, user.id)
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    service = ChangesSummaryService(db, user.id)
    summary = service.get_summary(since)

    # Bump last-visit to now so the next call reflects only new activity.
    now = datetime.now(timezone.utc)
    try:
        _write_last_visit(db, user.id, now)
        summary["last_visit_at"] = now.isoformat()
    except Exception as exc:  # noqa: BLE001
        # Last-visit tracking is best-effort; never fail the request over it.
        log.warning("changes_summary.last_visit_persist_failed", error=str(exc))
        summary["last_visit_at"] = None

    return summary


@router.get("/last-visit")
def get_last_visit(user: CurrentUser, db: Session = Depends(get_db)) -> dict:
    """Return the stored last-visit timestamp (ISO-8601) or null."""
    ts = _read_last_visit(db, user.id)
    return {"last_visit_at": ts.isoformat() if ts else None}
