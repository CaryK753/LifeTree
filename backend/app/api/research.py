"""Deep-research endpoints (§C of the cross-validation / deep-research spec).

Endpoints
---------
- ``POST /research``                 — create a ResearchJob and dispatch the Celery task.
- ``GET  /research``                 — list the current user's research jobs.
- ``GET  /research/{job_id}``        — get a single job (status / progress / report).
- ``POST /research/{job_id}/cancel`` — mark a job CANCELLED.
- ``GET  /research/engines``         — list configured search engines + domain strengths.
- ``GET  /research/{job_id}/events`` — SSE stream for live progress updates.

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
from app.models.research import ResearchJob, ResearchStatus

log = get_logger(__name__)

router = APIRouter(prefix="/research", tags=["research"])


# ---------- Schemas ----------


class StartResearchBody(BaseModel):
    """Body for ``POST /research``."""

    question: str = Field(..., min_length=3, max_length=2000)
    scope: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Free-form scope bag: {goal_id?, pathway_id?, region?, "
            "time_range?, max_sub_questions?, max_total_sources?, "
            "max_extract_chars?, max_llm_calls?}."
        ),
    )
    engines: list[str] | None = Field(
        default=None,
        description=(
            "Engines the job is allowed to use (subset of configured engines). "
            "If empty / None, all configured engines are used."
        ),
    )


class JobSummary(BaseModel):
    id: str
    question: str
    status: str
    progress: float
    current_step: str | None
    engines: list[str]
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class JobDetail(JobSummary):
    scope: dict[str, Any]
    plan: dict[str, Any] | None
    source_ids: list[str]
    assertion_ids: list[str]
    conflict_ids: list[str]
    report: dict[str, Any] | None
    failure_count: int


# ---------- Helpers ----------


def _engine_has_key(engine_name: str) -> bool:
    """Check whether an engine has a configured API key."""
    try:
        from app.llm.registry import (
            get_anysearch_key,
            get_bocha_key,
            get_exa_key,
            get_tavily_key,
        )

        key_getters = {
            "tavily": get_tavily_key,
            "exa": get_exa_key,
            "bocha": get_bocha_key,
            "anysearch": get_anysearch_key,
        }
        getter = key_getters.get(engine_name)
        return bool(getter and getter())
    except Exception:  # noqa: BLE001
        return False


def _serialize_summary(job: ResearchJob) -> JobSummary:
    return JobSummary(
        id=job.id,
        question=job.question,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        engines=list(job.engines or []),
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _serialize_detail(job: ResearchJob) -> JobDetail:
    return JobDetail(
        id=job.id,
        question=job.question,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        engines=list(job.engines or []),
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        scope=dict(job.scope or {}),
        plan=dict(job.plan or {}) if job.plan else None,
        source_ids=list(job.source_ids or []),
        assertion_ids=list(job.assertion_ids or []),
        conflict_ids=list(job.conflict_ids or []),
        report=dict(job.report or {}) if job.report else None,
        failure_count=job.failure_count or 0,
    )


def _resolve_engines(requested: list[str] | None) -> list[str]:
    """Resolve the engine list for a new job.

    If ``requested`` is empty / None, fall back to all configured engines.
    Filters out engines without API keys so the planner doesn't suggest
    engines that will fail at search time.
    """
    try:
        from app.services.search_engines import ALL_ENGINE_NAMES
    except Exception:  # noqa: BLE001
        ALL_ENGINE_NAMES = ["tavily", "exa", "bocha", "anysearch"]

    candidates = requested or ALL_ENGINE_NAMES
    return [e for e in candidates if e in ALL_ENGINE_NAMES and _engine_has_key(e)]


# ---------- Endpoints ----------


@router.get("/engines")
def list_engines(user: CurrentUser) -> dict[str, Any]:
    """List configured search engines + their domain strengths.

    Used by the frontend research launcher to render the engine picker.
    Only engines with a configured API key are marked ``available``.
    """
    try:
        from app.services.search_engines import (
            ALL_ENGINE_NAMES,
            get_engine_domain_strengths,
        )
    except Exception:  # noqa: BLE001
        ALL_ENGINE_NAMES = ["tavily", "exa", "bocha", "anysearch"]

        def get_engine_domain_strengths(e: str) -> list[str]:  # type: ignore[no-redef]
            return {
                "tavily": ["general", "official", "news"],
                "exa": ["academic", "semantic", "technical"],
                "bocha": ["chinese_news", "china_policy", "forum"],
                "anysearch": ["vertical", "structured", "batch"],
            }.get(e, [])

    engines = [
        {
            "name": name,
            "available": _engine_has_key(name),
            "domain_strengths": get_engine_domain_strengths(name),
        }
        for name in ALL_ENGINE_NAMES
    ]
    return {"engines": engines}


@router.post("", response_model=JobSummary, status_code=201)
def start_research(
    body: StartResearchBody, user: CurrentUser, db: Session = Depends(get_db)
) -> JobSummary:
    """Create a ResearchJob and dispatch the Celery ``run_research_job`` task."""
    from app.llm.registry import resolve_role

    if resolve_role("chat") is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "chat_model_not_configured: configure a chat model in Settings "
                "before starting a research job."
            ),
        )

    engines = _resolve_engines(body.engines)
    if not engines:
        raise HTTPException(
            status_code=400,
            detail=(
                "no_search_engines_configured: configure at least one search "
                "engine API key in Settings before starting a research job."
            ),
        )

    job = ResearchJob(
        user_id=user.id,
        question=body.question.strip(),
        scope=dict(body.scope or {}),
        engines=engines,
        status=ResearchStatus.PLANNING.value,
        progress=0.0,
        current_step="queued",
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
        from app.workers.research_tasks import run_research_job

        get_job_runner().submit(run_research_job, job_id=job.id)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "research.dispatch_failed",
            job_id=job.id,
            error=str(exc),
        )
        # Mark the job as failed so the frontend can surface the error.
        job.status = ResearchStatus.FAILED.value
        job.error = f"task_dispatch_failed: {exc}"[:500]
        db.commit()
        db.refresh(job)

    log.info(
        "research.job_created",
        job_id=job.id,
        user_id=user.id,
        question=job.question[:80],
        engines=engines,
    )
    return _serialize_summary(job)


@router.get("", response_model=list[JobSummary])
def list_jobs(
    user: CurrentUser,
    db: Session = Depends(get_db),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[JobSummary]:
    """List the current user's research jobs (newest first)."""
    stmt = (
        select(ResearchJob)
        .where(ResearchJob.user_id == user.id)
        .order_by(ResearchJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status:
        stmt = stmt.where(ResearchJob.status == status)
    jobs = list(db.scalars(stmt))
    return [_serialize_summary(j) for j in jobs]


@router.get("/{job_id}", response_model=JobDetail)
def get_job(
    job_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> JobDetail:
    """Get a single research job with full details / report."""
    job = db.get(ResearchJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="research_job_not_found")
    return _serialize_detail(job)


@router.post("/{job_id}/cancel", response_model=JobSummary)
def cancel_job(
    job_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> JobSummary:
    """Cancel a research job.

    Only jobs that are not yet terminal (completed / failed / cancelled)
    can be cancelled. The Celery task will see the CANCELLED status on its
    next node boundary and exit early.
    """
    job = db.get(ResearchJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="research_job_not_found")

    if job.status in (
        ResearchStatus.COMPLETED.value,
        ResearchStatus.FAILED.value,
        ResearchStatus.CANCELLED.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"job_already_terminal:{job.status}",
        )

    job.status = ResearchStatus.CANCELLED.value
    job.current_step = "cancelled by user"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)

    log.info("research.job_cancelled", job_id=job.id, user_id=user.id)
    return _serialize_summary(job)


@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> None:
    """Delete a research job.

    Non-terminal jobs are first marked CANCELLED so the Celery worker
    exits at its next node boundary. Then the DB row is removed.
    """
    job = db.get(ResearchJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="research_job_not_found")

    if job.status not in (
        ResearchStatus.COMPLETED.value,
        ResearchStatus.FAILED.value,
        ResearchStatus.CANCELLED.value,
    ):
        job.status = ResearchStatus.CANCELLED.value
        job.current_step = "cancelled by user"
        job.completed_at = datetime.now(timezone.utc)
        db.flush()

    db.delete(job)
    db.commit()
    log.info("research.job_deleted", job_id=job.id, user_id=user.id)


@router.get("/{job_id}/events")
async def stream_job_events(
    job_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """SSE stream for a single research job's progress updates.

    Subscribes to the ``lifetree:research:{job_id}`` Redis pub/sub channel.
    Emits ``event: progress`` messages with the JSON payload published by
    ``_publish_progress`` in ``research/graph.py``.

    On connect, sends the current job state as the first event so the
    client doesn't need a separate GET to bootstrap.
    """
    job = db.get(ResearchJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="research_job_not_found")

    channel = f"lifetree:research:{job_id}"

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
            ResearchStatus.COMPLETED.value,
            ResearchStatus.FAILED.value,
            ResearchStatus.CANCELLED.value,
        ):
            yield f"event: done\ndata: {json.dumps(bootstrap, default=str)}\n\n"
            return

        settings = get_settings()
        # Local-private runtime has no Redis; fall back to polling the DB.
        if settings.lifetree_storage_mode == "local":
            try:
                from app.db.postgres import SessionLocal

                last_progress = job.progress
                while True:
                    await asyncio.sleep(2)
                    with SessionLocal() as session:
                        fresh = session.get(ResearchJob, job_id)
                        if fresh is None:
                            break
                        if (
                            fresh.progress != last_progress
                            or fresh.status != job.status
                        ):
                            last_progress = fresh.progress
                            payload = {
                                "job_id": fresh.id,
                                "status": fresh.status,
                                "progress": fresh.progress,
                                "current_step": fresh.current_step,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                            yield f"event: progress\ndata: {json.dumps(payload, default=str)}\n\n"
                            if fresh.status in (
                                ResearchStatus.COMPLETED.value,
                                ResearchStatus.FAILED.value,
                                ResearchStatus.CANCELLED.value,
                            ):
                                yield f"event: done\ndata: {json.dumps(payload, default=str)}\n\n"
                                return
            except asyncio.CancelledError:
                log.info("research.sse.client_disconnected", job_id=job_id)
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
                            ResearchStatus.COMPLETED.value,
                            ResearchStatus.FAILED.value,
                            ResearchStatus.CANCELLED.value,
                        ):
                            yield f"event: done\ndata: {msg['data']}\n\n"
                            return
                    except Exception:  # noqa: BLE001
                        pass
        except asyncio.CancelledError:
            log.info("research.sse.client_disconnected", job_id=job_id)
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
