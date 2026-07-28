"""Celery tasks: cron-driven crawl + risk propagation + notification dispatch."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.postgres import get_session
from app.models.event import Event, InformationSource
from app.models.goal import Goal, GoalStatus
from app.models.notification import NotificationLog, NotificationStatus
from app.models.user import UserProfile
from app.services.crawler import CrawlerService
from app.services.notification import NotificationService
from app.services.reasoning.risk_propagation import RiskPropagationEngine
from app.services.scenarios import ScenarioService
from app.services.structuring import StructuringService
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.crawl_all_goals")
def crawl_all_goals() -> dict:
    """For every active goal, fetch fresh public info via Tavily and ingest."""
    crawler = CrawlerService()
    if not crawler.available:
        log.warning("crawl_all_goals.skipped_no_tavily_key")
        return {"status": "skipped", "reason": "no_tavily_key"}

    db = get_session()
    try:
        goals = list(db.scalars(
            select(Goal).where(Goal.status == GoalStatus.ACTIVE.value)
        ))
        total_events = 0
        for goal in goals:
            user = db.get(UserProfile, goal.user_id)
            if user is None:
                continue
            try:
                results = asyncio.run(
                    crawler.crawl_for_goal(
                        goal.title, goal.scenario, max_results=8
                    )
                )
            except Exception as exc:  # noqa: BLE001
                log.error("crawl.goal_failed", goal_id=goal.id, error=str(exc))
                continue

            structuring = StructuringService(db)
            for r in results:
                _, extraction = structuring.ingest_text(
                    text=r.content,
                    title=r.title,
                    source_kind="public",
                    url=r.url,
                    published_at=(
                        datetime.fromisoformat(r.published_at)
                        if r.published_at
                        else None
                    ),
                )
                if extraction is not None:
                    total_events += len(extraction.events)
        log.info("crawl_all_goals.done", goals=len(goals), events=total_events)
        return {"status": "ok", "goals_crawled": len(goals), "events": total_events}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.rerun_risk_propagation")
def rerun_risk_propagation() -> dict:
    """Re-run risk propagation for high-risk events from the last 24h.

    After re-propagation, notify the user whenever a (user, goal, scenario)
    risk level INCREASES (e.g. low→medium, medium→high). Severity of the
    notification matches the new level (medium=warning, high=critical).
    """
    from app.models.notification import RiskAssessment

    db = get_session()
    try:
        # Snapshot existing overall_risk per (user, goal, scenario) so we
        # can detect transitions after re-propagation.
        existing = list(db.scalars(select(RiskAssessment)))
        old_scores: dict[tuple[str, str, str | None], float] = {
            (a.user_id, a.goal_id, a.scenario_id): a.overall_risk for a in existing
        }

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        events = list(db.scalars(
            select(Event)
            .where(Event.risk_flag_level == "high")
            .where(Event.created_at >= cutoff)
        ))
        engine = RiskPropagationEngine(db)
        n = 0
        for ev in events:
            assessments = engine.propagate_from_event(ev)
            n += len(assessments)

        # Compare new vs old and emit transition notifications on increases.
        notif_service = NotificationService(db)
        notified = 0
        new_assessments = list(db.scalars(select(RiskAssessment)))
        for a in new_assessments:
            key = (a.user_id, a.goal_id, a.scenario_id)
            old_score = old_scores.get(key)
            if old_score is None:
                continue  # brand-new assessment, not a transition
            old_level = _score_to_level(old_score)
            new_level = _score_to_level(a.overall_risk)
            if _LEVEL_ORDER[new_level] <= _LEVEL_ORDER[old_level]:
                continue  # only notify on increase
            user = db.get(UserProfile, a.user_id)
            if user is None:
                continue
            goal = db.get(Goal, a.goal_id)
            goal_title = goal.title if goal else a.goal_id
            severity = "warning" if new_level == "medium" else "critical"
            notif_service.notify(
                user,
                title=f"风险等级升级：{goal_title}",
                body=f"目标「{goal_title}」的风险等级从 {old_level} 升至 {new_level}",
                severity=severity,
                risk_factor_id=f"risk_transition:{a.goal_id}",
                impact_summary={
                    "goal_id": a.goal_id,
                    "scenario_id": a.scenario_id,
                    "old_level": old_level,
                    "new_level": new_level,
                    "old_score": old_score,
                    "new_score": a.overall_risk,
                },
            )
            notified += 1

        log.info(
            "rerun_risk_propagation.done",
            events=len(events),
            assessments=n,
            notified=notified,
        )
        return {
            "status": "ok",
            "events": len(events),
            "assessments": n,
            "notified": notified,
        }
    finally:
        db.close()


# Risk-level ordering used to detect transitions (low < medium < high).
_LEVEL_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def _score_to_level(score: float) -> str:
    """Map a 0..1 risk score back to its level label.

    Mirrors ``RiskPropagationEngine._level_to_score``: low=0.2, medium=0.5,
    high=0.8. We use the midpoints (0.35, 0.65) as decision boundaries so
    small float drift doesn't flip the level.
    """
    if score >= 0.65:
        return "high"
    if score >= 0.35:
        return "medium"
    return "low"


@celery_app.task(name="app.workers.tasks.graph_health_check")
def graph_health_check() -> dict:
    """Run the decay sweep (auto-archive expired events) and check Neo4j."""
    from app.services.decay import DecayService
    from app.services.graph import GraphService

    db = get_session()
    try:
        # Auto-archive events whose decay score dropped below the expired
        # threshold. This is the "knowledge half-life" mechanism from §4.8.
        archived = DecayService(db).sweep_expired()

        healthy = GraphService().health()
        log.info("graph_health_check.done", archived=archived, neo4j_healthy=healthy)
        return {"status": "ok", "archived_events": archived, "neo4j_healthy": healthy}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.prune_scenarios")
def prune_scenarios() -> dict:
    """Close dormant low-impact scenarios across all goals."""
    db = get_session()
    try:
        goals = list(db.scalars(select(Goal)))
        total_closed = 0
        for goal in goals:
            total_closed += ScenarioService(db).prune_low_impact(goal.id)
        log.info("prune_scenarios.done", closed=total_closed)
        return {"status": "ok", "closed": total_closed}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.dispatch_pending_notifications")
def dispatch_pending_notifications() -> dict:
    """Retry any notifications stuck in PENDING status."""
    db = get_session()
    try:
        pending = list(db.scalars(
            select(NotificationLog)
            .where(NotificationLog.status == NotificationStatus.PENDING.value)
            .limit(100)
        ))
        service = NotificationService(db)
        sent = 0
        for record in pending:
            user = db.get(UserProfile, record.user_id)
            if user is None:
                continue
            service.notify(
                user,
                title=record.title,
                body=record.body,
                severity=record.severity,
                event_id=record.event_id,
                risk_factor_id=record.risk_factor_id,
                impact_summary=record.impact_summary,
                force=True,
            )
            sent += 1
        log.info("dispatch_pending_notifications.done", sent=sent, total=len(pending))
        return {"status": "ok", "sent": sent, "total": len(pending)}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.run_scenario_reasoning")
def run_scenario_reasoning(scenario_id: str) -> dict:
    """Async wrapper for the synchronous reasoning engine.

    Used by the API to offload long-running Monte Carlo simulations.
    """
    db = get_session()
    try:
        run = ScenarioService(db).run_reasoning(scenario_id)
        log.info(
            "run_scenario_reasoning.done",
            scenario_id=scenario_id,
            run_id=run.id,
            status=run.status,
        )
        return {
            "status": run.status,
            "run_id": run.id,
            "result": run.result,
        }
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.refresh_due_sources")
def refresh_due_sources(source_ids: list[str] | None = None) -> dict:
    """Refresh information sources that are due for their scheduled update.

    Runs every minute via Celery Beat. For each source where:
      - ``auto_refresh == True``
      - ``next_refresh_at <= now``
      - ``url`` is not empty

    the task re-fetches the URL content via Tavily Extract, ingests new
    events through the structuring pipeline (which triggers risk alerts
    for high-risk events), and advances ``next_refresh_at`` by
    ``refresh_interval_minutes``.

    If ``source_ids`` is provided (manual trigger), those specific sources
    are refreshed regardless of schedule — used by the
    ``POST /sources/{id}/refresh`` API endpoint.
    """
    now = datetime.now(timezone.utc)

    db = get_session()
    try:
        if source_ids:
            sources = list(db.scalars(
                select(InformationSource).where(
                    InformationSource.id.in_(source_ids)
                )
            ))
        else:
            sources = list(db.scalars(
                select(InformationSource).where(
                    InformationSource.auto_refresh.is_(True),
                    InformationSource.url.isnot(None),
                    InformationSource.url != "",
                    InformationSource.next_refresh_at <= now,
                ).limit(50)
            ))

        if not sources:
            return {"status": "ok", "refreshed": 0}

        crawler = CrawlerService()
        if not crawler.available:
            log.warning("refresh_due_sources.skipped_no_tavily_key")
            return {"status": "skipped", "reason": "no_tavily_key"}

        total_events = 0
        refreshed = 0
        for src in sources:
            try:
                results = asyncio.run(crawler.extract([src.url]))
                if not results or not results[0].content:
                    log.info(
                        "refresh_source.empty",
                        source_id=src.id,
                        url=src.url,
                    )
                else:
                    r = results[0]
                    structuring = StructuringService(db)
                    _, extraction = structuring.ingest_text(
                        text=r.content,
                        title=src.title,
                        source_kind=src.kind,
                        url=src.url,
                        published_at=now,
                    )
                    if extraction is not None:
                        total_events += len(extraction.events)

                # Advance the schedule
                src.last_refreshed_at = now
                src.next_refresh_at = now + timedelta(
                    minutes=src.refresh_interval_minutes
                )
                refreshed += 1
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "refresh_source.failed",
                    source_id=src.id,
                    url=src.url,
                    error=str(exc),
                )
                # Still advance the schedule so one failure doesn't block
                # subsequent runs
                src.next_refresh_at = now + timedelta(
                    minutes=src.refresh_interval_minutes
                )

        db.commit()
        log.info(
            "refresh_due_sources.done",
            sources=len(sources),
            refreshed=refreshed,
            events=total_events,
        )
        return {
            "status": "ok",
            "refreshed": refreshed,
            "events": total_events,
        }
    finally:
        db.close()
