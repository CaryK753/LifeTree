"""Celery tasks for deep research (§C.2 / §C.4 of the spec).

The ``run_research_job`` task advances a ``ResearchJob`` through the six-
stage LangGraph pipeline (planning → searching → extracting → structuring
→ validating → synthesizing). Soft time limit 10 min, hard 11 min — a
soft-timeout leaves partial results (sources / assertions / conflicts) in
the DB row so the frontend can still render what was collected.

Registered under ``app.workers.research_tasks`` so the Celery app picks
it up via the ``include`` list in ``celery_app.py``.
"""

from __future__ import annotations

from celery.exceptions import SoftTimeLimitExceeded

from app.core.logging import get_logger
from app.db.postgres import get_session
from app.services.research import run_research
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(
    name="app.workers.research_tasks.run_research_job",
    soft_time_limit=600,
    time_limit=660,
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_kwargs={"max_retries": 1},
)
def run_research_job(job_id: str) -> dict:
    """Execute a deep-research job.

    Soft time limit 600 s (10 min): when the soft timer fires, Celery raises
    ``SoftTimeLimitExceeded`` inside the running node. Each node commits
    partial progress before yielding back to LangGraph, so the DB row keeps
    whatever was collected. The exception is caught here so the row is
    marked FAILED (not CRASHED) with a partial-results note.

    Hard time limit 660 s (11 min): Celery forcibly terminates the worker.
    The job row will keep whatever status / progress was last committed.
    """
    log.info("research.job_started", job_id=job_id)
    db = get_session()
    try:
        try:
            final = run_research(db, job_id)
        except SoftTimeLimitExceeded as exc:
            # Soft timeout: mark the job FAILED with partial results.
            log.warning("research.job_soft_timeout", job_id=job_id, error=str(exc))
            from app.models.research import ResearchJob, ResearchStatus
            from datetime import datetime, timezone

            job = db.get(ResearchJob, job_id)
            if job is not None and job.status not in (
                ResearchStatus.COMPLETED.value,
                ResearchStatus.CANCELLED.value,
            ):
                job.status = ResearchStatus.FAILED.value
                job.error = (
                    f"soft_time_limit_exceeded: partial results collected "
                    f"({len(job.source_ids or [])} sources, "
                    f"{len(job.assertion_ids or [])} assertions)"
                )
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
            return {
                "job_id": job_id,
                "status": "failed",
                "error": "soft_time_limit_exceeded",
            }

        # Inspect final state for surfacing to the caller (and Celery result backend).
        error = final.get("error") if isinstance(final, dict) else None
        if error:
            return {"job_id": job_id, "status": "failed", "error": error}
        return {
            "job_id": job_id,
            "status": "completed",
            "report_keys": list((final.get("report") or {}).keys()) if isinstance(final, dict) else [],
        }
    finally:
        db.close()
