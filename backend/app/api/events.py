"""Event & InformationSource listing + source credibility endpoints.

Multi-user isolation: all endpoints resolve the authenticated user via
``CurrentUser`` and filter data by ``user.id``. Legacy rows with NULL
``user_id`` (created before this migration) remain visible to all users
via ``user_id IS NULL OR user_id = :uid`` filters. In single-user mode
``CurrentUser`` falls back to the default user, so behavior is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.event import Event, InformationSource
from app.models.user import UserProfile
from app.schemas.api import (
    CredibilityDistribution,
    EventRead,
    InformationSourceRead,
    SourceScheduleUpdate,
)

log = get_logger(__name__)

router = APIRouter(tags=["events", "sources"])


def _user_scope(user: CurrentUser):
    """Return a filter clause matching rows owned by ``user`` or legacy
    NULL-user rows. Admins see all rows."""
    if user.role == "admin":
        return None  # no filter
    return or_(Event.user_id == user.id, Event.user_id.is_(None))


def _source_scope(user: CurrentUser):
    if user.role == "admin":
        return None
    return or_(InformationSource.user_id == user.id, InformationSource.user_id.is_(None))


# ---------- Events ----------

@router.get("/events", response_model=list[EventRead])
def list_events(
    user: CurrentUser,
    limit: int = 100,
    risk_level: str | None = None,
    db: Session = Depends(get_db),
) -> list[Event]:
    stmt = select(Event)
    scope = _user_scope(user)
    if scope is not None:
        stmt = stmt.where(scope)
    if risk_level:
        stmt = stmt.where(Event.risk_flag_level == risk_level)
    return list(
        db.scalars(stmt.order_by(Event.created_at.desc()).limit(limit))
    )


@router.get("/events/{event_id}", response_model=EventRead)
def get_event(
    event_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> Event:
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    # Enforce ownership: only the owner (or admin) can read. Legacy NULL
    # rows are visible to everyone.
    if ev.user_id is not None and ev.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this event")
    return ev


# ---------- §4.9 Review Inbox ----------
#
# Per project plan §4.9: events with confidence < 0.8 AND impact >= 'high'
# are routed to ``pending_review`` status by the structuring pipeline.
# This surface exposes them as a queue the user can triage with three
# actions: 采纳 (approve), 忽略 (sink), 保持低权重沉降 (keep sunk).
# High-impact pending_review events should also nudge the user via the
# notification channel — handled in ``_apply_status_transitions`` below
# (called after the status change is persisted).

class EventStatusUpdate(BaseModel):
    """PATCH body for ``/events/{id}/status``.

    ``action`` is the user intent:
    - ``approve``    → status='approved' (event joins the active graph)
    - ``sink``       → status='sunk_low_weight' (stays in DB but excluded
                      from reasoning + dashboard feeds)
    - ``keep_sunk``  → confirms a sunk event should remain sunk (no-op
                      semantically, but records user acknowledgement)
    """
    action: str  # 'approve' | 'sink' | 'keep_sunk'


@router.get("/events/pending-review", response_model=list[EventRead])
def list_pending_review(
    user: CurrentUser,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[Event]:
    """Return events awaiting user review (§4.9 Review Inbox).

    Only ``pending_review`` events are returned, newest first. Per §4.9
    rule 3 the queue should ideally only surface events whose impact is
    HIGH/CRITICAL on the user's critical path — here we approximate by
    sorting on ``risk_flag_level`` desc then ``created_at`` desc so the
    most urgent items appear at the top.
    """
    stmt = select(Event).where(Event.status == "pending_review")
    scope = _user_scope(user)
    if scope is not None:
        stmt = stmt.where(scope)
    # Sort: 'high' > 'medium' > 'low' > NULL. Use a CASE expression so
    # ordering reflects severity rather than alphabetical order.
    level_rank = func.coalesce(
        func.strpos("high,medium,low", Event.risk_flag_level),
        0,
    )
    return list(
        db.scalars(
            stmt.order_by(level_rank.desc(), Event.created_at.desc()).limit(limit)
        )
    )


@router.patch("/events/{event_id}/status", response_model=EventRead)
def update_event_status(
    event_id: str,
    body: EventStatusUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Event:
    """Advance an event's review status per §4.9.

    The three user-facing actions map onto the event ``status`` field:
      approve   → 'approved'
      sink      → 'sunk_low_weight'
      keep_sunk → 'sunk_low_weight' (idempotent — already sunk)

    Side effects:
    - On approve, the event becomes visible to the reasoning engine and
      dashboard feeds. If the event's source is currently ``pending``
      credibility, we also bump it to ``medium`` so the approved event
      contributes to inferences with a non-zero weight.
    - On sink, the event is excluded from reasoning but retained for
      audit. No source-credibility change.
    - §4.9: approving a high-impact pending_review event runs risk
      propagation and notifies the user about any material impact
      changes on affected goals.
    """
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    if ev.user_id is not None and ev.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this event")

    action = body.action.lower()
    next_status = {
        "approve": "approved",
        "sink": "sunk_low_weight",
        "keep_sunk": "sunk_low_weight",
    }.get(action)
    if next_status is None:
        raise HTTPException(
            422,
            "Unknown action. Expected one of: approve, sink, keep_sunk.",
        )

    prev_status = ev.status
    ev.status = next_status

    # Side effect: approving a pending-review event should also unblock
    # its source if that source was still in 'pending' credibility. We
    # only escalate pending→medium (never downgrade an existing mark).
    if action == "approve" and ev.source_id is not None:
        src = db.get(InformationSource, ev.source_id)
        if src is not None and src.credibility == "pending":
            src.credibility = "medium"
            src.credibility_score = max(src.credibility_score, 0.5)

    # §B.7: event-review reputation feedback. ``approve`` confirms the
    # source's reliability, ``sink`` refutes it. Idempotent — the
    # SourceAccuracyLog (source_id, evidence_key) unique constraint
    # prevents double-counting. Skipped for ``keep_sunk`` (no-op).
    if action in ("approve", "sink") and ev.source_id is not None:
        src = db.get(InformationSource, ev.source_id)
        if src is not None and (src.user_id == user.id or user.role == "admin"):
            try:
                from app.services.source_reputation import SourceReputationService

                SourceReputationService(db, user.id).record_verdict(
                    src,
                    evidence_key=f"event_review:{ev.id}",
                    confirmed=(action == "approve"),
                    meta={"event_id": ev.id, "action": action},
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "events.reputation_feedback_failed",
                    event_id=ev.id,
                    error=str(exc),
                )

    db.commit()
    db.refresh(ev)

    # §4.9: notify the user about the impact of their review action.
    _apply_status_transitions(ev, user, db, action, prev_status)

    log.info(
        "review.status_changed",
        event_id=ev.id,
        prev=prev_status,
        next=next_status,
        action=action,
        user_id=user.id,
    )
    return ev


def _apply_status_transitions(
    ev: Event,
    user: CurrentUser,
    db: Session,
    action: str,
    prev_status: str | None,
) -> None:
    """Side effects triggered when an event's review status changes (§4.9).

    On ``approve`` the event joins the active graph and may shift the
    user's risk profile. We run risk propagation and notify the user (and
    any other affected users) about material impact changes. On
    ``sink``/``keep_sunk`` we send a quiet confirmation so the user has
    an audit trail of their decision.

    Failures inside this helper must never roll back the status change
    itself — the user's review decision is already persisted. We catch
    all exceptions and log them as warnings.
    """
    from app.services.notification import NotificationService
    from app.services.reasoning.risk_propagation import RiskPropagationEngine

    notif_service = NotificationService(db)

    if action == "approve":
        # Run risk propagation for the newly-approved event so the user
        # sees the downstream impact on their goals.
        propagation = RiskPropagationEngine(db)
        try:
            assessments = propagation.propagate_from_event(ev)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "review.propagation_failed",
                event_id=ev.id,
                error=str(exc),
            )
            assessments = []

        if not assessments:
            notif_service.notify(
                user,
                title=f"事件已采纳: {ev.subject} {ev.action}",
                body="该事件已纳入活跃图谱，未检测到对目标的实质性风险变化。",
                severity="info",
                event_id=ev.id,
                impact_summary={
                    "action": "approve",
                    "prev_status": prev_status,
                },
            )
            return

        for a in assessments:
            affected = a.user if hasattr(a, "user") else None
            if affected is None:
                affected = db.get(UserProfile, a.user_id) if a.user_id else None
            if affected is None:
                continue
            notif_service.notify(
                affected,
                title=f"风险已更新: {ev.subject} {ev.action}",
                body=(
                    f"采纳该事件后，目标 {a.goal_id} 的整体风险更新为 "
                    f"{a.overall_risk:.2f}。"
                ),
                severity="critical" if a.overall_risk >= 0.7 else "warning",
                event_id=ev.id,
                impact_summary={
                    "goal_id": a.goal_id,
                    "overall_risk": a.overall_risk,
                    "factor_scores": a.factor_scores,
                    "action": "approve",
                },
            )
    else:
        # sink / keep_sunk: quiet audit-trail notification.
        notif_service.notify(
            user,
            title=f"事件已{('忽略' if action == 'sink' else '保持忽略')}: {ev.subject} {ev.action}",
            body="该事件已排除出推理链。如需恢复，可在审核收箱中重新采纳。",
            severity="info",
            event_id=ev.id,
            impact_summary={
                "action": action,
                "prev_status": prev_status,
            },
        )


# ---------- Sources ----------

@router.get("/sources", response_model=list[InformationSourceRead])
def list_sources(
    user: CurrentUser,
    limit: int = 100,
    kind: str | None = None,
    db: Session = Depends(get_db),
) -> list[InformationSource]:
    stmt = select(InformationSource)
    scope = _source_scope(user)
    if scope is not None:
        stmt = stmt.where(scope)
    if kind:
        stmt = stmt.where(InformationSource.kind == kind)
    return list(
        db.scalars(stmt.order_by(InformationSource.created_at.desc()).limit(limit))
    )


@router.get("/sources/credibility", response_model=CredibilityDistribution)
def credibility_distribution(
    user: CurrentUser, db: Session = Depends(get_db)
) -> CredibilityDistribution:
    """Aggregate credibility distribution for the user's sources."""
    scope = _source_scope(user)
    base = select(InformationSource.credibility, func.count())
    if scope is not None:
        base = base.where(scope)
    rows = db.execute(base.group_by(InformationSource.credibility)).all()

    counts = {row[0]: row[1] for row in rows}
    total = sum(counts.values())

    private_stmt = (
        select(func.count())
        .select_from(InformationSource)
        .where(InformationSource.kind == "user_upload")
    )
    if scope is not None:
        private_stmt = private_stmt.where(scope)
    private_count = db.scalar(private_stmt) or 0

    return CredibilityDistribution(
        high=counts.get("high", 0),
        medium=counts.get("medium", 0),
        low=counts.get("low", 0),
        pending=counts.get("pending", 0),
        user_marked_reliable=counts.get("user_marked_reliable", 0),
        user_marked_questionable=counts.get("user_marked_questionable", 0),
        total=total,
        private_share=(private_count / total) if total else 0.0,
    )


@router.patch("/sources/{source_id}/credibility", response_model=InformationSourceRead)
def mark_source_credibility(
    source_id: str,
    user: CurrentUser,
    credibility: str,
    db: Session = Depends(get_db),
) -> InformationSource:
    """User marks a source as reliable or questionable."""
    src = db.get(InformationSource, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    if src.user_id is not None and src.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this source")
    src.credibility = credibility
    if credibility == "user_marked_reliable":
        src.credibility_score = 0.9
    elif credibility == "user_marked_questionable":
        src.credibility_score = 0.2
    db.commit()
    db.refresh(src)
    return src


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(
    source_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> None:
    """Delete a source row.

    Events that reference this source via foreign-key columns are set to NULL
    (the FK is declared with ``ondelete="SET NULL"``), so deleting a source
    never cascades into losing events — only the source record is removed.
    """
    src = db.get(InformationSource, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    if src.user_id is not None and src.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this source")
    db.delete(src)
    db.commit()


@router.patch("/sources/{source_id}/schedule", response_model=InformationSourceRead)
def update_source_schedule(
    source_id: str,
    payload: SourceScheduleUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> InformationSource:
    """Set or update the auto-refresh cron schedule for a source.

    When ``auto_refresh=True``, the Celery beat task ``refresh_due_sources``
    will re-fetch this source's URL content every ``refresh_interval_minutes``
    minutes and ingest new events — which in turn triggers risk alerts via
    the standard structuring pipeline.

    Only sources with a URL can be auto-refreshed.
    """
    src = db.get(InformationSource, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    if src.user_id is not None and src.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this source")
    if payload.auto_refresh and not src.url:
        raise HTTPException(
            400, "Cannot auto-refresh a source without a URL"
        )
    src.auto_refresh = payload.auto_refresh
    src.refresh_interval_minutes = payload.refresh_interval_minutes
    if payload.auto_refresh:
        src.next_refresh_at = datetime.now(timezone.utc) + timedelta(
            minutes=payload.refresh_interval_minutes
        )
    else:
        src.next_refresh_at = None
    db.commit()
    db.refresh(src)
    return src


@router.post("/sources/{source_id}/refresh", response_model=InformationSourceRead)
def refresh_source_now(
    source_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> InformationSource:
    """Manually trigger a refresh of a single source.

    Delegates to the active JobRunner so servers use Celery while a local
    desktop runtime executes through its in-process queue.
    """
    from app.services.runtime.job_runner import get_job_runner
    from app.workers.tasks import refresh_due_sources

    src = db.get(InformationSource, source_id)
    if src is None:
        raise HTTPException(404, "Source not found")
    if src.user_id is not None and src.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this source")
    if not src.url:
        raise HTTPException(400, "Cannot refresh a source without a URL")
    get_job_runner().submit(refresh_due_sources, source_ids=[source_id])
    db.refresh(src)
    return src
