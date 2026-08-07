"""Celery tasks for AgentTeam (§D.8 of the cross-validation spec).

The ``run_agent_team`` task advances an ``AgentTeamJob`` through the
LangGraph team pipeline (decompose → dispatch → specialists → aggregate
→ review → finalize). Soft time limit 15 min, hard 16 min — AgentTeam
tasks are longer than ResearchJob (10 min) because multiple sub-agents
run sequentially within the Celery worker (the Send-API fan-out runs
specialists concurrently via asyncio, but each specialist's LLM calls
are still sequential).

Soft-timeout leaves partial results (specialist_results) in the DB row
so the frontend can still render what was collected.

Registered under ``app.workers.agent_team_tasks`` so the Celery app picks
it up via the ``include`` list in ``celery_app.py``. Celery beat does NOT
register a periodic trigger — AgentTeam tasks are on-demand only.
"""

from __future__ import annotations

from celery.exceptions import SoftTimeLimitExceeded

from app.core.logging import get_logger
from app.db.postgres import get_session
from app.services.agent_team import run_agent_team
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(
    name="app.workers.agent_team_tasks.run_agent_team",
    soft_time_limit=900,
    time_limit=960,
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_kwargs={"max_retries": 1},
)
def run_agent_team_job(job_id: str) -> dict:
    """Execute an AgentTeam task.

    Soft time limit 900 s (15 min): when the soft timer fires, Celery raises
    ``SoftTimeLimitExceeded`` inside the running node. Each node commits
    partial progress before yielding, so the DB row keeps whatever was
    collected (completed specialist results, partial aggregated output).
    The exception is caught here so the row is marked FAILED (not CRASHED)
    with a partial-results note.

    Hard time limit 960 s (16 min): Celery forcibly terminates the worker.
    The job row will keep whatever status / progress was last committed.
    """
    log.info("agent_team.job_started", job_id=job_id)
    db = get_session()
    try:
        try:
            final = run_agent_team(db, job_id)
        except SoftTimeLimitExceeded as exc:
            # Soft timeout: mark the job FAILED with partial results.
            log.warning("agent_team.job_soft_timeout", job_id=job_id, error=str(exc))
            from datetime import datetime, timezone

            from app.models.agent_team import AgentTeamJob, TeamStatus

            job = db.get(AgentTeamJob, job_id)
            if job is not None and job.status not in (
                TeamStatus.COMPLETED.value,
                TeamStatus.CANCELLED.value,
            ):
                job.status = TeamStatus.FAILED.value
                job.error = (
                    f"soft_time_limit_exceeded: partial results collected "
                    f"({len(job.specialist_results or [])} specialists completed)"
                )
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
            return {
                "job_id": job_id,
                "status": "failed",
                "error": "soft_time_limit_exceeded",
            }

        # Inspect final state for surfacing to the caller.
        error = final.get("error") if isinstance(final, dict) else None
        if error:
            return {"job_id": job_id, "status": "failed", "error": error}
        final_output = final.get("final_output") if isinstance(final, dict) else None
        return {
            "job_id": job_id,
            "status": "completed",
            "final_output_keys": list(final_output.keys()) if isinstance(final_output, dict) else [],
        }
    finally:
        db.close()
