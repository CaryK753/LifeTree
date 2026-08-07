"""LangGraph orchestrator for the deep-research pipeline (§C.2 of the spec).

Wires the six stage nodes into a linear StateGraph::

    planning → searching → extracting → structuring → validating → synthesizing → finalize

Each node updates the persisted ``ResearchJob`` row (status / progress /
current_step) and publishes a progress event to Redis pub/sub channel
``lifetree:research:{job_id}`` so the frontend ``/research/{job_id}`` page
and the chat research-progress card can render live updates.

The structuring and validating nodes are kept inline here (rather than in
separate files) because they are thin adapters around
``StructuringService.ingest_text`` and ``CrossValidationService`` — the
heavy lifting lives in those services.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.research import ResearchJob, ResearchStatus
from app.services.research.extractor import extract_pages
from app.services.research.planner import plan_research
from app.services.research.searcher import search_sources
from app.services.research.state import ResearchState
from app.services.research.synthesizer import synthesize_report

log = get_logger(__name__)


# ---------- Progress publisher ----------


def _publish_progress(job: ResearchJob) -> None:
    """Push a progress event to Redis pub/sub for live UI updates.

    Channel: ``lifetree:research:{job_id}``. Payload: JSON with status,
    progress, current_step, and (when completed) the report.

    Failures are non-fatal — pub/sub is best-effort; the DB row is the
    source of truth.
    """
    try:
        from app.db.redis import get_redis

        payload = {
            "job_id": job.id,
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        get_redis().publish(
            f"lifetree:research:{job.id}",
            json.dumps(payload, default=str),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("research.publish_progress_failed", job_id=job.id, error=str(exc))


def _update_job(
    db: Session,
    job: ResearchJob,
    *,
    status: ResearchStatus,
    current_step: str,
    progress: float,
) -> None:
    """Update job status / progress / current_step, commit, and publish."""
    job.status = status.value
    job.current_step = current_step
    job.progress = max(0.0, min(1.0, progress))
    if status == ResearchStatus.PLANNING and job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
    if status == ResearchStatus.COMPLETED:
        job.completed_at = datetime.now(timezone.utc)
        job.progress = 1.0
    db.commit()
    _publish_progress(job)


# ---------- Inline node: structuring ----------


def structure_atoms(
    db: Session,
    job: ResearchJob,
    state: ResearchState,
) -> ResearchState:
    """Run ``StructuringService.ingest_text`` for each extracted page (§C.2).

    Each extracted page is persisted as an ``InformationSource`` with
    ``engine`` provenance recorded in ``meta`` so the resulting Assertions
    inherit the engine field (used by cross-engine consensus voting in the
    next node).

    All Assertions are written with ``status='pending_review'`` (the
    structuring service does this) so the research job never promotes
    Assertions on the main graph branch — that path stays with the
    Review Inbox (§C.1 of the spec).
    """
    from app.services.structuring import StructuringService

    _update_job(
        db,
        job,
        status=ResearchStatus.STRUCTURING,
        current_step="Structuring extracted pages into atoms",
        progress=0.65,
    )

    pages = state.get("extracted_pages") or []
    if not pages:
        log.info("research.structure_no_pages", job_id=job.id)
        state["structured_atoms"] = {
            "events": [],
            "assertions": [],
            "relationships": [],
            "metrics": [],
        }
        return state

    service = StructuringService(db)
    user_id = state.get("user_id") or job.user_id

    atoms: dict[str, list[dict[str, Any]]] = {
        "events": [],
        "assertions": [],
        "relationships": [],
        "metrics": [],
    }
    source_ids: list[str] = list(job.source_ids or [])
    assertion_ids: list[str] = list(job.assertion_ids or [])

    total = len(pages)
    for idx, page in enumerate(pages):
        # Progress within structuring stage: 0.65 → 0.80.
        progress = 0.65 + 0.15 * (idx / max(1, total))
        job.progress = progress
        job.current_step = f"Structuring page {idx + 1}/{total}"
        db.commit()
        _publish_progress(job)

        url = page.get("url") or ""
        engine = page.get("engine") or ""
        title = (page.get("title") or url)[:200]
        content = page.get("content") or ""
        if not content.strip():
            continue

        try:
            source, extraction = service.ingest_text(
                text=content[:16000],
                title=title,
                url=url or None,
                user_id=user_id,
                meta={
                    "engine": engine,
                    "extraction_source": "deep_research",
                    "research_job_id": job.id,
                    "sub_question": page.get("sub_question"),
                },
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "research.structure_page_failed",
                job_id=job.id,
                url=url,
                error=str(exc),
            )
            state["failure_count"] = state.get("failure_count", 0) + 1
            continue

        if source.id not in source_ids:
            source_ids.append(source.id)
        # Backfill the source_id on the collected source dict so the
        # synthesizer's sources_summary can reference it.
        page["source_id"] = source.id

        if extraction is not None:
            for ev in extraction.events:
                atoms["events"].append(_atom_to_dict(ev))
            for asrt in extraction.assertions:
                atoms["assertions"].append(_atom_to_dict(asrt))
            for rel in extraction.relationships:
                atoms["relationships"].append(_atom_to_dict(rel))
            for met in extraction.metrics:
                atoms["metrics"].append(_atom_to_dict(met))
            # The structuring service already triggered incremental
            # conflict detection for these assertions. We collect IDs
            # for the validating node's scoped re-scan.
            for asrt in extraction.assertions:
                # Assertion rows are flushed inside ingest_text; fetch
                # the id from the ORM object (set after flush).
                asrt_id = getattr(asrt, "id", None)
                if asrt_id and asrt_id not in assertion_ids:
                    assertion_ids.append(asrt_id)

        # Persist progress so partial results survive a soft timeout.
        job.source_ids = list(source_ids)
        job.assertion_ids = list(assertion_ids)
        db.commit()

    state["structured_atoms"] = atoms
    state["collected_sources"] = state.get("collected_sources") or []
    job.progress = 0.80
    db.commit()
    _publish_progress(job)

    log.info(
        "research.structure_complete",
        job_id=job.id,
        pages_structured=total,
        events=len(atoms["events"]),
        assertions=len(atoms["assertions"]),
    )
    return state


def _atom_to_dict(atom: Any) -> dict[str, Any]:
    """Best-effort serialization of a Pydantic atom / ORM row to a dict."""
    if hasattr(atom, "model_dump"):
        return atom.model_dump(mode="json")
    if hasattr(atom, "__dict__"):
        return {k: v for k, v in vars(atom).items() if not k.startswith("_")}
    return {"value": str(atom)}


# ---------- Inline node: validating ----------


def validate_atoms(
    db: Session,
    job: ResearchJob,
    state: ResearchState,
) -> ResearchState:
    """Run cross-validation on the newly-persisted Assertions (§C.2).

    The structuring service already triggers incremental conflict detection
    per page; this node re-scans the full set of job Assertions together so
    cross-engine conflicts that only surface when all sources are pooled
    are detected. It also runs trend analysis so the synthesizer can
    include temporal trends in the report.
    """
    from app.services.cross_validation import CrossValidationService

    _update_job(
        db,
        job,
        status=ResearchStatus.VALIDATING,
        current_step="Cross-validating extracted assertions",
        progress=0.82,
    )

    assertion_ids = list(job.assertion_ids or [])
    if not assertion_ids:
        log.info("research.validate_no_assertions", job_id=job.id)
        state["conflict_groups"] = []
        state["trends"] = []
        return state

    user_id = state.get("user_id") or job.user_id
    svc = CrossValidationService(db, user_id)

    conflict_groups: list[dict[str, Any]] = []
    trends: list[dict[str, Any]] = []

    try:
        conflict_groups = svc.detect_conflicts_for_assertions(assertion_ids)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "research.validate_conflicts_failed",
            job_id=job.id,
            error=str(exc),
        )
        state["failure_count"] = state.get("failure_count", 0) + 1

    # Persist conflict IDs on the job for partial-result recovery.
    conflict_ids = [g.get("subject", "") for g in conflict_groups if g.get("subject")]
    job.conflict_ids = conflict_ids
    db.commit()

    # Trend analysis on the detected conflict pairs.
    try:
        if conflict_groups:
            trends = svc.detect_trends()
    except Exception as exc:  # noqa: BLE001
        log.error(
            "research.validate_trends_failed",
            job_id=job.id,
            error=str(exc),
        )
        state["failure_count"] = state.get("failure_count", 0) + 1

    state["conflict_groups"] = conflict_groups
    state["trends"] = trends

    job.progress = 0.85
    db.commit()
    _publish_progress(job)

    log.info(
        "research.validate_complete",
        job_id=job.id,
        conflicts=len(conflict_groups),
        trends=len(trends),
    )
    return state


# ---------- Inline node: finalize ----------


def finalize(db: Session, job: ResearchJob, state: ResearchState) -> ResearchState:
    """Mark the job as COMPLETED and publish the final progress event."""
    error = state.get("error")
    if error:
        _update_job(
            db,
            job,
            status=ResearchStatus.FAILED,
            current_step=f"Failed: {error[:120]}",
            progress=job.progress,
        )
        job.error = error
        db.commit()
        return state

    _update_job(
        db,
        job,
        status=ResearchStatus.COMPLETED,
        current_step="Research completed",
        progress=1.0,
    )
    log.info(
        "research.finalized",
        job_id=job.id,
        sources=len(job.source_ids or []),
        assertions=len(job.assertion_ids or []),
        conflicts=len(job.conflict_ids or []),
    )
    return state


# ---------- Graph builder ----------


def build_research_graph(db: Session, job: ResearchJob) -> Any:
    """Compile the research StateGraph for one job.

    The graph is built per invocation because nodes close over the DB
    session and the ``ResearchJob`` row (mirrors the conflict-graph and
    advisor patterns).
    """
    g: StateGraph = StateGraph(ResearchState)

    g.add_node("planning", lambda s: plan_research(db, job, s))
    g.add_node("searching", lambda s: search_sources(db, job, s))
    g.add_node("extracting", lambda s: extract_pages(db, job, s))
    g.add_node("structuring", lambda s: structure_atoms(db, job, s))
    g.add_node("validating", lambda s: validate_atoms(db, job, s))
    g.add_node("synthesizing", lambda s: synthesize_report(db, job, s))
    g.add_node("finalize", lambda s: finalize(db, job, s))

    g.set_entry_point("planning")
    g.add_edge("planning", "searching")
    g.add_edge("searching", "extracting")
    g.add_edge("extracting", "structuring")
    g.add_edge("structuring", "validating")
    g.add_edge("validating", "synthesizing")
    g.add_edge("synthesizing", "finalize")
    g.add_edge("finalize", END)

    return g.compile()


def run_research(db: Session, job_id: str) -> ResearchState:
    """Synchronous runner used by the Celery ``run_research_job`` task.

    Loads the ``ResearchJob`` row, builds the graph, and invokes it with
    an initial state. On any fatal exception, the job is marked FAILED
    with the error message so the frontend can surface it.
    """
    job = db.get(ResearchJob, job_id)
    if job is None:
        log.error("research.run_job_not_found", job_id=job_id)
        return {"error": f"ResearchJob {job_id} not found"}

    # Skip if already terminal (e.g. user cancelled, or task was retried
    # after a soft-timeout partial completion).
    if job.status in (
        ResearchStatus.COMPLETED.value,
        ResearchStatus.CANCELLED.value,
    ):
        log.info("research.run_skip_terminal", job_id=job_id, status=job.status)
        return {"job_id": job_id, "status": job.status, "skipped": True}

    # Reset a FAILED job to PLANNING so retries re-run from the top.
    # (Partial results in source_ids / assertion_ids are preserved —
    # the structuring node idempotently re-ingests them.)
    if job.status == ResearchStatus.FAILED.value:
        job.status = ResearchStatus.PLANNING.value
        job.error = None
        db.commit()

    initial: ResearchState = {
        "job_id": job.id,
        "user_id": job.user_id,
        "question": job.question,
        "scope": dict(job.scope or {}),
        "engines": list(job.engines or []),
        "llm_calls": 0,
        "failure_count": job.failure_count or 0,
        "collected_sources": [],
        "extracted_pages": [],
        "structured_atoms": {
            "events": [],
            "assertions": [],
            "relationships": [],
            "metrics": [],
        },
        "conflict_groups": [],
        "trends": [],
        "error": None,
    }

    try:
        graph = build_research_graph(db, job)
        final = graph.invoke(initial)
        # Persist the final failure_count back to the job row.
        job.failure_count = int(final.get("failure_count", 0) or 0)
        db.commit()
        return final  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        log.error("research.run_failed", job_id=job_id, error=str(exc), exc_info=True)
        job.status = ResearchStatus.FAILED.value
        job.error = str(exc)[:1000]
        job.failure_count = (job.failure_count or 0) + 1
        db.commit()
        _publish_progress(job)
        return {"job_id": job_id, "error": str(exc)}


__all__ = [
    "build_research_graph",
    "run_research",
    "structure_atoms",
    "validate_atoms",
    "finalize",
]
