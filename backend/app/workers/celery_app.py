"""Celery app configuration: broker + result backend + beat schedule."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "lifetree",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=4,
    task_default_queue="lifetree",
    result_expires=7 * 24 * 3600,  # 7 days
)

# ---------- Beat schedule: cron-style recurring jobs ----------

celery_app.conf.beat_schedule = {
    # Refresh all active goals every 4 hours
    "crawl-all-goals": {
        "task": "app.workers.tasks.crawl_all_goals",
        "schedule": crontab(minute=0, hour="*/4"),
    },
    # Re-run risk propagation for high-risk events every 30 minutes
    "rerun-risk-propagation": {
        "task": "app.workers.tasks.rerun_risk_propagation",
        "schedule": crontab(minute="*/30"),
    },
    # Daily knowledge-graph health check at 03:00 UTC
    "graph-health-check": {
        "task": "app.workers.tasks.graph_health_check",
        "schedule": crontab(minute=0, hour=3),
    },
    # Daily scenario pruning at 04:00 UTC
    "scenario-prune": {
        "task": "app.workers.tasks.prune_scenarios",
        "schedule": crontab(minute=0, hour=4),
    },
    # Dispatch pending notifications every 5 minutes
    "dispatch-notifications": {
        "task": "app.workers.tasks.dispatch_pending_notifications",
        "schedule": crontab(minute="*/5"),
    },
}
