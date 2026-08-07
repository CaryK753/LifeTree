"""AgentTeam endpoints (§D of the cross-validation / deep-research spec).

Endpoints
---------
- ``POST /agent-team``                 — create an AgentTeamJob and dispatch the Celery task.
- ``GET  /agent-team``                 — list the current user's team jobs.
- ``GET  /agent-team/{job_id}``        — get a single job (status / progress / final_output).
- ``POST /agent-team/{job_id}/cancel`` — mark a job CANCELLED.
- ``GET  /agent-team/templates``       — list available team templates + role specs.
- ``GET  /agent-team/{job_id}/events`` — SSE stream for live progress updates.

Multi-user isolation: every query is scoped by ``user.id``. A user can
only see / cancel their own jobs.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.agent_team import TEAM_TEMPLATES, AgentTeamJob, TeamStatus

log = get_logger(__name__)

router = APIRouter(prefix="/agent-team", tags=["agent-team"])


# ---------- Schemas ----------


class StartTeamBody(BaseModel):
    """Body for ``POST /agent-team``."""

    objective: str = Field(..., min_length=3, max_length=4000)
    template: str = Field(
        ...,
        description=(
            "Team template identifier. One of: "
            "cross_domain_research, independent_validation, "
            "multi_pathway_compare, risk_scan, iterative_research."
        ),
    )
    scope: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Free-form scope bag: {goal_id?, scenario_id?, engines?, "
            "domains?, subquestions?, max_specialists?, max_iterations?, "
            "max_llm_calls?}."
        ),
    )


class TeamJobSummary(BaseModel):
    id: str
    objective: str
    template: str
    status: str
    progress: float
    current_step: str | None
    iterations: int
    specialist_count: int
    failure_count: int
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class TeamJobDetail(TeamJobSummary):
    scope: dict[str, Any]
    subtasks: list[dict[str, Any]]
    specialist_results: list[dict[str, Any]]
    aggregated: dict[str, Any] | None
    review_gaps: list[dict[str, Any]]
    final_output: dict[str, Any] | None


class TemplateInfo(BaseModel):
    name: str
    description: str
    allowed_roles: list[str]
    max_iterations: int
    always_synthesize: bool


# ---------- Helpers ----------


def _serialize_summary(job: AgentTeamJob) -> TeamJobSummary:
    return TeamJobSummary(
        id=job.id,
        objective=job.objective,
        template=job.template,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        iterations=job.iterations or 0,
        specialist_count=len(job.specialist_results or []),
        failure_count=job.failure_count or 0,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _serialize_detail(job: AgentTeamJob) -> TeamJobDetail:
    return TeamJobDetail(
        id=job.id,
        objective=job.objective,
        template=job.template,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        iterations=job.iterations or 0,
        specialist_count=len(job.specialist_results or []),
        failure_count=job.failure_count or 0,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        scope=dict(job.scope or {}),
        subtasks=list(job.subtasks or []),
        specialist_results=list(job.specialist_results or []),
        aggregated=dict(job.aggregated or {}) if job.aggregated else None,
        review_gaps=list(job.review_gaps or []),
        final_output=dict(job.final_output or {}) if job.final_output else None,
    )


def _validate_template(name: str) -> None:
    """Reject unknown templates at the API boundary."""
    if name not in TEAM_TEMPLATES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid_template: {name}. Valid templates: "
                f"{', '.join(TEAM_TEMPLATES)}"
            ),
        )


# ---------- Endpoints ----------


@router.get("/templates")
def list_templates(user: CurrentUser) -> dict[str, Any]:
    """List available team templates + their role specs.

    Used by the frontend team launcher to render the template picker.
    """
    from app.services.agent_team.templates import TEMPLATES

    templates = [
        TemplateInfo(
            name=spec.name,
            description=spec.description,
            allowed_roles=list(spec.allowed_roles),
            max_iterations=spec.max_iterations,
            always_synthesize=spec.always_synthesize,
        ).model_dump()
        for spec in TEMPLATES.values()
    ]
    return {"templates": templates}


@router.post("", response_model=TeamJobSummary, status_code=201)
def start_team(
    body: StartTeamBody, user: CurrentUser, db: Session = Depends(get_db)
) -> TeamJobSummary:
    """Create an AgentTeamJob and dispatch the Celery ``run_agent_team`` task."""
    _validate_template(body.template)

    from app.llm.registry import resolve_role

    if resolve_role("chat") is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "chat_model_not_configured: configure a chat model in Settings "
                "before starting an agent team job."
            ),
        )

    from datetime import datetime, timezone

    job = AgentTeamJob(
        user_id=user.id,
        template=body.template,
        objective=body.objective.strip(),
        scope=dict(body.scope or {}),
        status=TeamStatus.DECOMPOSING.value,
        progress=0.0,
        current_step="queued",
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch the task via the job runner abstraction. In Docker / server
    # mode this delegates to Celery (``.delay()``); in local / desktop mode
    # it runs in-process via ``InProcessJobRunner`` so the feature works
    # without a Redis broker.
    try:
        from app.services.runtime.job_runner import get_job_runner
        from app.workers.agent_team_tasks import run_agent_team_job

        get_job_runner().submit(run_agent_team_job, job_id=job.id)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "agent_team.dispatch_failed",
            job_id=job.id,
            error=str(exc),
        )
        job.status = TeamStatus.FAILED.value
        job.error = f"task_dispatch_failed: {exc}"[:500]
        db.commit()
        db.refresh(job)

    log.info(
        "agent_team.job_created",
        job_id=job.id,
        user_id=user.id,
        template=job.template,
        objective=job.objective[:80],
    )
    return _serialize_summary(job)


@router.get("", response_model=list[TeamJobSummary])
def list_jobs(
    user: CurrentUser,
    db: Session = Depends(get_db),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[TeamJobSummary]:
    """List the current user's AgentTeam jobs (newest first)."""
    stmt = (
        select(AgentTeamJob)
        .where(AgentTeamJob.user_id == user.id)
        .order_by(AgentTeamJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status:
        stmt = stmt.where(AgentTeamJob.status == status)
    jobs = list(db.scalars(stmt))
    return [_serialize_summary(j) for j in jobs]


@router.get("/{job_id}", response_model=TeamJobDetail)
def get_job(
    job_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> TeamJobDetail:
    """Get a single AgentTeam job with full details / final output."""
    job = db.get(AgentTeamJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="agent_team_job_not_found")
    return _serialize_detail(job)


@router.post("/{job_id}/cancel", response_model=TeamJobSummary)
def cancel_job(
    job_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> TeamJobSummary:
    """Cancel an AgentTeam job.

    Only jobs that are not yet terminal (completed / failed / cancelled)
    can be cancelled. The Celery task will see the CANCELLED status on its
    next node boundary and exit early.
    """
    job = db.get(AgentTeamJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="agent_team_job_not_found")

    if job.status in (
        TeamStatus.COMPLETED.value,
        TeamStatus.FAILED.value,
        TeamStatus.CANCELLED.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"job_already_terminal:{job.status}",
        )

    job.status = TeamStatus.CANCELLED.value
    job.current_step = "cancelled by user"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)

    log.info("agent_team.job_cancelled", job_id=job.id, user_id=user.id)
    return _serialize_summary(job)


@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> None:
    """Delete an AgentTeam job.

    Non-terminal jobs are first marked CANCELLED so the Celery worker
    exits at its next node boundary. Then the DB row is removed.
    """
    job = db.get(AgentTeamJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="agent_team_job_not_found")

    if job.status not in (
        TeamStatus.COMPLETED.value,
        TeamStatus.FAILED.value,
        TeamStatus.CANCELLED.value,
    ):
        job.status = TeamStatus.CANCELLED.value
        job.current_step = "cancelled by user"
        job.completed_at = datetime.now(timezone.utc)
        db.flush()

    db.delete(job)
    db.commit()
    log.info("agent_team.job_deleted", job_id=job.id, user_id=user.id)


@router.get("/{job_id}/events")
async def stream_job_events(
    job_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """SSE stream for a single AgentTeam job's progress updates.

    Subscribes to the ``lifetree:agent_team:{job_id}`` Redis pub/sub channel.
    Emits ``event: progress`` messages with the JSON payload published by
    the orchestrator nodes.

    On connect, sends the current job state as the first event so the
    client doesn't need a separate GET to bootstrap.
    """
    job = db.get(AgentTeamJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="agent_team_job_not_found")

    channel = f"lifetree:agent_team:{job_id}"

    async def event_generator():
        # Bootstrap event with the current DB state.
        bootstrap = {
            "job_id": job.id,
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        yield f"event: progress\ndata: {json.dumps(bootstrap, default=str)}\n\n"

        # If the job is already terminal, send a final close event.
        if job.status in (
            TeamStatus.COMPLETED.value,
            TeamStatus.FAILED.value,
            TeamStatus.CANCELLED.value,
        ):
            yield f"event: done\ndata: {json.dumps(bootstrap, default=str)}\n\n"
            return

        settings = get_settings()
        # Local-private runtime has no Redis; fall back to polling the DB.
        if settings.lifetree_storage_mode == "local":
            try:
                from app.db.postgres import SessionLocal

                last_progress = job.progress
                last_status = job.status
                while True:
                    await asyncio.sleep(2)
                    with SessionLocal() as session:
                        fresh = session.get(AgentTeamJob, job_id)
                        if fresh is None:
                            break
                        if (
                            fresh.progress != last_progress
                            or fresh.status != last_status
                        ):
                            last_progress = fresh.progress
                            last_status = fresh.status
                            payload = {
                                "job_id": fresh.id,
                                "status": fresh.status,
                                "progress": fresh.progress,
                                "current_step": fresh.current_step,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                            yield f"event: progress\ndata: {json.dumps(payload, default=str)}\n\n"
                            if fresh.status in (
                                TeamStatus.COMPLETED.value,
                                TeamStatus.FAILED.value,
                                TeamStatus.CANCELLED.value,
                            ):
                                yield f"event: done\ndata: {json.dumps(payload, default=str)}\n\n"
                                return
            except asyncio.CancelledError:
                log.info("agent_team.sse.client_disconnected", job_id=job_id)
            return

        # Redis pub/sub path.
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=15.0
                )
                if msg is None:
                    yield f": ping {datetime.now(timezone.utc).isoformat()}\n\n"
                    continue
                if msg.get("type") == "message":
                    yield f"event: progress\ndata: {msg['data']}\n\n"
                    # Inspect payload for terminal status to close the stream.
                    try:
                        payload = json.loads(msg["data"])
                        if payload.get("status") in (
                            TeamStatus.COMPLETED.value,
                            TeamStatus.FAILED.value,
                            TeamStatus.CANCELLED.value,
                        ):
                            yield f"event: done\ndata: {msg['data']}\n\n"
                            return
                    except Exception:  # noqa: BLE001
                        pass
        except asyncio.CancelledError:
            log.info("agent_team.sse.client_disconnected", job_id=job_id)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await redis.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
