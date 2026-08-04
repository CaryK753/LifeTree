"""Ingest endpoints: feed raw text or uploaded files into the structuring pipeline."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.event import Event
from app.models.user import UserProfile
from app.models.user_runtime import UserServiceConfig
from app.schemas.api import IngestTextRequest, IngestTextResponse
from app.services.mineru import is_supported, parse_file
from app.services.notification import NotificationService
from app.services.reasoning.risk_propagation import RiskPropagationEngine
from app.services.runtime.blob_store import get_blob_store
from app.services.structuring import StructuringService

log = get_logger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/text", response_model=IngestTextResponse)
def ingest_text(
    payload: IngestTextRequest, user: CurrentUser, db: Session = Depends(get_db)
) -> IngestTextResponse:
    """Run raw text through the structuring pipeline."""
    return _run_ingest(
        db=db,
        user=user,
        text=payload.text,
        title=payload.title,
        source_kind=payload.source_kind,
        url=payload.url,
        publisher=payload.publisher,
        published_at=payload.published_at,
        user_upload_id=payload.user_upload_id,
        skip_llm=payload.skip_llm,
    )


@router.post("/upload", response_model=IngestTextResponse)
async def ingest_upload(
    user: CurrentUser,
    file: UploadFile = File(...),
    title: str = Form(""),
    source_kind: str = Form("user_upload"),
    url: str | None = Form(None),
    publisher: str | None = Form(None),
    skip_llm: bool = Form(False),
    db: Session = Depends(get_db),
) -> IngestTextResponse:
    """Upload a file, parse it (Mineru for Office/PDF, direct read for text),
    then run the resulting text through the same structuring pipeline as
    ``POST /ingest/text``.

    The original file is stored through the active BlobStore so users can
    re-download or re-process it later.
    """
    if not file.filename or not is_supported(file.filename):
        raise HTTPException(
            415,
            "不支持的文件类型。支持 PDF / Word / Excel / PPT / TXT / Markdown / CSV / 图片。",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")

    user_services = db.get(UserServiceConfig, user.id)
    private_mineru_key = (
        user_services.mineru_api_key if user_services else ""
    ) or None
    parsed = parse_file(
        raw,
        file.filename,
        title=title or None,
        api_key_override=private_mineru_key,
        base_url_override=user_services.mineru_base_url if private_mineru_key else None,
    )
    final_title = parsed.title or file.filename

    # Persist the original bytes for traceability. Server mode uses MinIO;
    # local mode uses the content-addressed objects directory.
    blob_key = ""
    try:
        stored = get_blob_store().put_bytes(
            raw,
            content_type=file.content_type or "application/octet-stream",
        )
        blob_key = stored.key
    except Exception as exc:  # noqa: BLE001
        log.warning("ingest.blob_put_failed", error=str(exc))

    if not parsed.text.strip():
        # Still create a source so the user sees the upload, but mark skip_llm
        return _run_ingest(
            db=db,
            user=user,
            text=parsed.warning or "(空文本)",
            title=final_title,
            source_kind="user_upload",
            url=url,
            publisher=publisher,
            user_upload_id=blob_key or None,
            skip_llm=True,
        )

    return _run_ingest(
        db=db,
        user=user,
        text=parsed.text,
        title=final_title,
        source_kind=source_kind,
        url=url,
        publisher=publisher,
        user_upload_id=blob_key or None,
        skip_llm=skip_llm,
    )


# ---------- Internal ----------

def _run_ingest(
    *,
    db: Session,
    user: CurrentUser,
    text: str,
    title: str,
    source_kind: str,
    url: str | None,
    publisher: str | None,
    published_at: datetime | None = None,
    user_upload_id: str | None = None,
    skip_llm: bool = False,
) -> IngestTextResponse:
    """Shared structuring pipeline used by both /text and /upload."""
    service = StructuringService(db)
    source, extraction = service.ingest_text(
        text=text,
        title=title,
        source_kind=source_kind,
        url=url,
        publisher=publisher,
        published_at=published_at,
        user_upload_id=user_upload_id,
        user_id=user.id,
        skip_llm=skip_llm,
    )

    if extraction is None:
        return IngestTextResponse(
            source_id=source.id,
            events_created=0,
            metrics_created=0,
            assertions_created=0,
            relationships_created=0,
            extraction_confidence=None,
            notifications_triggered=0,
        )

    notifications = 0
    propagation = RiskPropagationEngine(db)
    notif_service = NotificationService(db)

    high_risk_events = list(
        db.scalars(
            select(Event)
            .where(Event.source_id == source.id, Event.risk_flag_level == "high")
        )
    )
    for ev in high_risk_events:
        assessments = propagation.propagate_from_event(ev)
        for a in assessments:
            user = a.user if hasattr(a, "user") else None
            if user is None:
                user = db.get(UserProfile, a.user_id)
            if user is None:
                continue
            notif_service.notify(
                user,
                title=f"High-risk event: {ev.subject} {ev.action}",
                body=ev.summary if hasattr(ev, "summary") and ev.summary else
                f"Risk level {ev.risk_flag_level} detected for {ev.subject}.",
                severity="critical" if ev.risk_flag_urgency == "urgent" else "warning",
                event_id=ev.id,
                risk_factor_id=None,
                impact_summary={
                    "goal_id": a.goal_id,
                    "overall_risk": a.overall_risk,
                    "factor_scores": a.factor_scores,
                },
            )
            notifications += 1

    return IngestTextResponse(
        source_id=source.id,
        events_created=len(extraction.events),
        metrics_created=len(extraction.metrics),
        assertions_created=len(extraction.assertions),
        relationships_created=len(extraction.relationships),
        extraction_confidence=extraction.overall_confidence,
        notifications_triggered=notifications,
    )
