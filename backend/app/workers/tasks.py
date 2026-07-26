"""Celery tasks: cron-driven crawl + risk propagation + notification dispatch."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.postgres import get_session
from app.models.event import Event
from app.models.goal import Goal, GoalStatus
from app.models.notification import NotificationLog, NotificationStatus
from app.models.scenario import Scenario, ScenarioStatus
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
    """Re-run risk propagation for high-risk events from the last 24h."""
    db = get_session()
    try:
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
        log.info("rerun_risk_propagation.done", events=len(events), assessments=n)
        return {"status": "ok", "events": len(events), "assessments": n}
    finally:
        db.close()


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
