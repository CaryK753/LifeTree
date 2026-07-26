"""Information half-life (decay) service.

Implements §4.8 of the project plan: knowledge half-life management.
Each piece of information (Event) has a decay score that drops over time
based on its half-life. When the score crosses thresholds, the event is
marked "stale" (needs refresh) or "expired" (should be archived).

Decay model
-----------
We use exponential decay with a configurable half-life per event:

    score(t) = 0.5 ** (age_days / half_life_days)

- score = 1.0      → brand new
- score = 0.5      → one half-life old (default threshold for "stale")
- score = 0.25     → two half-lives (default threshold for "expired")
- score → 0        → fully decayed

Default half-lives by source kind (§4.8: "政策信息默认有效期 2 年;
新闻事件影响力定期衰减"):
    - official / policy: 730 days (2 years)
    - news:              30 days
    - public:            180 days
    - advisor:           365 days
    - user_upload:       365 days
    - other:             365 days

A user can override the half-life per event via the API.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.event import Event, SourceKind

log = get_logger(__name__)


# ---------- Defaults ----------

# Half-life (days) by source kind. These match the project plan §4.8:
# policy/official = 2 years; news = 1 month; everything else = 1 year.
DEFAULT_HALF_LIFE_DAYS: dict[str, int] = {
    SourceKind.OFFICIAL.value: 730,
    SourceKind.NEWS.value: 30,
    SourceKind.PUBLIC.value: 180,
    SourceKind.ADVISOR.value: 365,
    SourceKind.USER_UPLOAD.value: 365,
    SourceKind.OTHER.value: 365,
}

FALLBACK_HALF_LIFE_DAYS = 365

# Score thresholds. Below STALE_THRESHOLD the event is flagged for refresh;
# below EXPIRED_THRESHOLD it should be archived.
STALE_SCORE_THRESHOLD = 0.5
EXPIRED_SCORE_THRESHOLD = 0.25


# ---------- Public dataclasses ----------

@dataclass
class DecayScore:
    """Decay computation result for a single event."""

    event_id: str
    score: float
    age_days: float
    half_life_days: int
    status: str  # "fresh" | "stale" | "expired"
    last_refreshed_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "score": round(self.score, 4),
            "age_days": round(self.age_days, 2),
            "half_life_days": self.half_life_days,
            "status": self.status,
            "last_refreshed_at": self.last_refreshed_at.isoformat()
            if self.last_refreshed_at
            else None,
        }


@dataclass
class DecayDistribution:
    """Aggregate decay stats across a set of events."""

    total: int
    fresh: int
    stale: int
    expired: int
    archived: int
    avg_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "fresh": self.fresh,
            "stale": self.stale,
            "expired": self.expired,
            "archived": self.archived,
            "avg_score": round(self.avg_score, 4),
        }


# ---------- Service ----------

class DecayService:
    """Computes and persists decay scores for events.

    The service is stateless — every call recomputes the score from the
    event's `created_at` (or `last_refreshed_at` if set) and its
    `half_life_days` (falling back to the source-kind default).
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ----- Pure helpers -----

    @staticmethod
    def half_life_for(ev: Event) -> int:
        """Resolve the effective half-life (days) for an event."""
        if ev.half_life_days and ev.half_life_days > 0:
            return ev.half_life_days
        # Fall back to the source-kind default.
        src = ev.source
        if src is not None and src.kind in DEFAULT_HALF_LIFE_DAYS:
            return DEFAULT_HALF_LIFE_DAYS[src.kind]
        return FALLBACK_HALF_LIFE_DAYS

    @staticmethod
    def compute_score(
        ev: Event, now: datetime | None = None
    ) -> tuple[float, float, datetime]:
        """Return (score, age_days, reference_time).

        `reference_time` is `last_refreshed_at` if set, else `created_at`.
        Age is measured in days from `reference_time` to `now`.
        """
        now = now or datetime.now(timezone.utc)
        ref = ev.meta.get("last_refreshed_at")
        ref_dt: datetime
        if ref:
            try:
                ref_dt = datetime.fromisoformat(ref)
            except (ValueError, TypeError):
                ref_dt = ev.created_at
        else:
            ref_dt = ev.created_at
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)
        age = (now - ref_dt).total_seconds() / 86400.0
        age = max(age, 0.0)
        half_life = float(DecayService.half_life_for(ev))
        if half_life <= 0:
            score = 0.0
        else:
            score = math.pow(0.5, age / half_life)
        return score, age, ref_dt

    @staticmethod
    def status_for(score: float, archived: bool) -> str:
        if archived:
            return "archived"
        if score < EXPIRED_SCORE_THRESHOLD:
            return "expired"
        if score < STALE_SCORE_THRESHOLD:
            return "stale"
        return "fresh"

    # ----- DB-backed operations -----

    def score_event(self, ev: Event, now: datetime | None = None) -> DecayScore:
        score, age, ref_dt = self.compute_score(ev, now)
        archived = bool(ev.meta.get("archived"))
        return DecayScore(
            event_id=ev.id,
            score=score,
            age_days=age,
            half_life_days=self.half_life_for(ev),
            status=self.status_for(score, archived),
            last_refreshed_at=ref_dt if ev.meta.get("last_refreshed_at") else None,
        )

    def list_events(
        self,
        status: str | None = None,
        limit: int = 200,
    ) -> list[tuple[Event, DecayScore]]:
        """Return events with their decay scores, optionally filtered by status."""
        now = datetime.now(timezone.utc)
        stmt = select(Event).order_by(Event.created_at.desc()).limit(limit)
        events = list(self.db.scalars(stmt))
        out: list[tuple[Event, DecayScore]] = []
        for ev in events:
            sc = self.score_event(ev, now)
            if status is None or sc.status == status:
                out.append((ev, sc))
        return out

    def distribution(self) -> DecayDistribution:
        now = datetime.now(timezone.utc)
        events = list(self.db.scalars(select(Event)))
        fresh = stale = expired = archived = 0
        total_score = 0.0
        for ev in events:
            sc = self.score_event(ev, now)
            if sc.status == "fresh":
                fresh += 1
            elif sc.status == "stale":
                stale += 1
            elif sc.status == "expired":
                expired += 1
            elif sc.status == "archived":
                archived += 1
            total_score += sc.score
        total = len(events)
        return DecayDistribution(
            total=total,
            fresh=fresh,
            stale=stale,
            expired=expired,
            archived=archived,
            avg_score=(total_score / total) if total else 0.0,
        )

    def refresh(self, event_id: str) -> Event | None:
        """Mark an event as freshly reviewed — resets the decay clock."""
        ev = self.db.get(Event, event_id)
        if ev is None:
            return None
        now_iso = datetime.now(timezone.utc).isoformat()
        meta = dict(ev.meta or {})
        meta["last_refreshed_at"] = now_iso
        meta.pop("archived", None)
        meta.pop("archived_at", None)
        ev.meta = meta
        self.db.commit()
        self.db.refresh(ev)
        log.info("decay.refresh", event_id=event_id)
        return ev

    def archive(self, event_id: str) -> Event | None:
        """Archive an event — excludes it from active reasoning/dashboard."""
        ev = self.db.get(Event, event_id)
        if ev is None:
            return None
        now_iso = datetime.now(timezone.utc).isoformat()
        meta = dict(ev.meta or {})
        meta["archived"] = True
        meta["archived_at"] = now_iso
        ev.meta = meta
        self.db.commit()
        self.db.refresh(ev)
        log.info("decay.archive", event_id=event_id)
        return ev

    def set_half_life(self, event_id: str, half_life_days: int) -> Event | None:
        """Override the half-life for a specific event."""
        ev = self.db.get(Event, event_id)
        if ev is None:
            return None
        if half_life_days <= 0:
            ev.half_life_days = None  # reset to default
        else:
            ev.half_life_days = half_life_days
        self.db.commit()
        self.db.refresh(ev)
        return ev

    def sweep_expired(self, archive_below: float = EXPIRED_SCORE_THRESHOLD) -> int:
        """Auto-archive every event whose score is below `archive_below`.

        Called by the daily `graph_health_check` Celery task. Returns the
        number of events archived in this sweep.

        Also emits user-facing notifications:
          - score < STALE_THRESHOLD  → warning "建议刷新"
          - score < EXPIRED_THRESHOLD → info "已自动归档"
        Each notification is rate-limited to once per day per event via
        Redis SETNX (mirrors ``NotificationService._is_suppressed``).
        """
        from app.core.tenant import get_default_user
        from app.db.redis import get_redis
        from app.services.notification import NotificationService

        now = datetime.now(timezone.utc)
        events = list(self.db.scalars(select(Event)))
        archived = 0
        stale_notified = 0
        archive_notified = 0

        # Single-user mode: resolve once. (Multi-tenant would thread user
        # through event ownership; this matches the rest of the codebase.)
        user = get_default_user(self.db)
        notif_service = NotificationService(self.db)
        redis = get_redis()

        for ev in events:
            if ev.meta.get("archived"):
                continue
            score, _, _ = self.compute_score(ev, now)
            title = self._event_title(ev)
            if score < archive_below:
                meta = dict(ev.meta or {})
                meta["archived"] = True
                meta["archived_at"] = now.isoformat()
                meta["auto_archived"] = True
                ev.meta = meta
                archived += 1
                if self._mark_decay_notified(redis, user.id, ev.id, "archived"):
                    notif_service.notify(
                        user,
                        title=f"信息已自动归档：{title}",
                        body=f"信息「{title}」已自动归档",
                        severity="info",
                        event_id=ev.id,
                        risk_factor_id=f"decay:archived:{ev.id}",
                        force=True,  # we already SETNX-rated above
                    )
                    archive_notified += 1
            elif score < STALE_SCORE_THRESHOLD:
                if self._mark_decay_notified(redis, user.id, ev.id, "stale"):
                    notif_service.notify(
                        user,
                        title=f"信息已过时：{title}",
                        body=f"信息「{title}」已过时，建议刷新",
                        severity="warning",
                        event_id=ev.id,
                        risk_factor_id=f"decay:stale:{ev.id}",
                        force=True,
                    )
                    stale_notified += 1
        if archived:
            self.db.commit()
        log.info(
            "decay.sweep_expired",
            archived=archived,
            threshold=archive_below,
            stale_notified=stale_notified,
            archive_notified=archive_notified,
        )
        return archived

    # ---------------- Helpers (notifications) ----------------

    @staticmethod
    def _event_title(ev: Event) -> str:
        """Best-effort human-readable title for an event."""
        src = getattr(ev, "source", None)
        if src is not None and getattr(src, "title", None):
            return src.title
        return ev.subject or ev.id

    @staticmethod
    def _mark_decay_notified(
        redis, user_id: str, event_id: str, kind: str
    ) -> bool:
        """Once-per-day SETNX gate for decay notifications.

        Mirrors the pattern in ``NotificationService._is_suppressed`` but
        uses a 24h TTL so we never notify about the same event twice in
        a single day. Returns True if this caller "won" the slot.
        """
        key = f"notif:decay:{kind}:{user_id}:{event_id}"
        try:
            acquired = redis.set(key, "1", ex=86400, nx=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("decay.redis_setnx_failed", error=str(exc))
            return False
        return bool(acquired)


def is_active(ev: Event) -> bool:
    """Filter predicate: skip archived events in active views."""
    return not bool(ev.meta.get("archived"))
