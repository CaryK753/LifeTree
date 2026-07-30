"""Shared ingestion stage for trusted and isolated plugin output."""

from __future__ import annotations

from sqlalchemy import select

from app.core.logging import get_logger
from app.models.event import Event
from app.models.user import UserProfile
from app.services.notification import NotificationService
from app.services.reasoning.risk_propagation import RiskPropagationEngine
from app.services.structuring import StructuringService

log = get_logger(__name__)


def ingest_and_pack(db, text: str, title: str, skip_llm: bool, out: dict) -> dict:
    try:
        source, extraction = StructuringService(db).ingest_text(
            text=text,
            title=title or "Untitled",
            source_kind="public",
            skip_llm=skip_llm,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("plugins.ingest_failed", error=str(exc))
        out["error"] = f"入库失败: {exc}"
        return out

    out["source_id"] = source.id
    if extraction is None:
        out["ok"] = True
        return out

    out.update({
        "events_created": len(extraction.events),
        "metrics_created": len(extraction.metrics),
        "assertions_created": len(extraction.assertions),
        "relationships_created": len(extraction.relationships),
        "extraction_confidence": extraction.overall_confidence,
    })
    notifications = 0
    propagation = RiskPropagationEngine(db)
    notifier = NotificationService(db)
    high_risk_events = list(db.scalars(
        select(Event).where(
            Event.source_id == source.id,
            Event.risk_flag_level == "high",
        )
    ))
    for event in high_risk_events:
        for assessment in propagation.propagate_from_event(event):
            user = getattr(assessment, "user", None) or db.get(
                UserProfile, assessment.user_id
            )
            if user is None:
                continue
            notifier.notify(
                user,
                title=f"High-risk event: {event.subject} {event.action}",
                body=getattr(event, "summary", "")
                or f"Risk level {event.risk_flag_level} detected.",
                severity=(
                    "critical" if event.risk_flag_urgency == "urgent" else "warning"
                ),
                event_id=event.id,
                impact_summary={
                    "goal_id": assessment.goal_id,
                    "overall_risk": assessment.overall_risk,
                    "factor_scores": assessment.factor_scores,
                },
            )
            notifications += 1
    out["notifications_triggered"] = notifications
    out["ok"] = True
    return out
