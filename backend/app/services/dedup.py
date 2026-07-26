"""Semantic fingerprint-based deduplication.

Per project plan §4.8: dedup uses subject+action+object+time_window
fingerprints to decide whether a new event is a duplicate, an update,
or a new node.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.event import Event, EventFingerprint

log = get_logger(__name__)

# Time bucket size (in days) for grouping "same event" detections
TIME_BUCKET_DAYS = 7


def compute_fingerprint(
    subject: str,
    action: str,
    object: str | None,
    occurred_at: datetime | None,
) -> tuple[str, str | None]:
    """Return (fingerprint, time_window_label)."""
    if occurred_at:
        bucket = occurred_at - timedelta(
            days=occurred_at.timetuple().tm_yday % TIME_BUCKET_DAYS
        )
        window = bucket.strftime("%Y-%m-%d")
    else:
        window = None

    raw = "|".join(
        [
            subject.strip().lower(),
            action.strip().lower(),
            (object or "").strip().lower(),
            window or "",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), window


class DedupService:
    """Decide whether an incoming atom duplicates an existing event."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def find_duplicate(
        self,
        subject: str,
        action: str,
        object: str | None,
        occurred_at: datetime | None,
    ) -> tuple[Event | None, str | None]:
        """Return (existing_event, fingerprint) if duplicate, else (None, fp)."""
        fp, window = compute_fingerprint(subject, action, object, occurred_at)

        existing_fp = self.db.scalar(
            select(EventFingerprint).where(EventFingerprint.fingerprint == fp)
        )
        if existing_fp is None:
            return None, fp

        existing_event = self.db.get(Event, existing_fp.primary_event_id)
        return existing_event, fp

    def register(
        self,
        event: Event,
        fingerprint: str,
        subject: str,
        action: str,
        object: str | None,
        time_window: str | None,
    ) -> EventFingerprint:
        """Register a new fingerprint → event mapping."""
        record = EventFingerprint(
            fingerprint=fingerprint,
            subject=subject,
            action=action,
            object=object,
            time_window=time_window,
            primary_event_id=event.id,
        )
        self.db.add(record)
        return record

    def merge_into(
        self,
        new_event: Event,
        existing_event: Event,
    ) -> Event:
        """Mark new_event as a duplicate of existing_event.

        For MVP we simply discard the new event by not adding it; the caller
        can decide to instead record a version update.
        """
        log.info(
            "dedup.merge_into",
            existing=existing_event.id,
            duplicate_subject=new_event.subject,
        )
        # Detach new event so caller doesn't accidentally persist it
        self.db.expunge(new_event)
        return existing_event
