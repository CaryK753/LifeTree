"""Information structuring pipeline.

Takes raw text (from crawler or user upload), asks the LLM to produce a
StructuredExtraction, dedups against existing events, and writes new
atoms to PostgreSQL + Neo4j. Per project plan §4.1.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import LLMNotConfiguredError
from app.core.logging import get_logger
from app.llm.client import get_chat_model, get_instructor_sync
from app.llm.embeddings import embed_texts
from app.models.event import (
    Assertion,
    Event,
    InformationSource,
    MetricSnapshot,
    Relationship,
    SourceKind,
)
from app.schemas.llm_atoms import StructuredExtraction
from app.services.dedup import DedupService
from app.services.graph import GraphService

log = get_logger(__name__)


SYSTEM_PROMPT = """You are LifeTree's information-structuring agent.

Given a raw document, extract structured "information atoms":
- events: discrete things that happened (subject/action/object/time/old→new)
- metrics: numeric data points (e.g. CRS cutoff = 510)
- assertions: unconfirmed claims
- relationships: causal / correlation edges between ontology entities

Rules:
- Be conservative: only emit an atom if the source supports it directly.
- Mark risk_flag.level = high only for events likely to materially change
  a user's plan (e.g. policy cutoffs, program suspensions, currency shocks).
- Use ISO 8601 for all timestamps.
- If a field is unknown, omit it (do not invent values).
- extraction_confidence reflects how clearly the source supports the atom.
"""


class StructuringService:
    """Orchestrates LLM extraction → dedup → DB writes."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.dedup = DedupService(db)
        self.graph = GraphService()

    # ---------------- Public API ----------------

    def ingest_text(
        self,
        *,
        text: str,
        title: str,
        source_kind: str = SourceKind.PUBLIC.value,
        url: str | None = None,
        publisher: str | None = None,
        published_at: datetime | None = None,
        user_upload_id: str | None = None,
        user_id: str | None = None,
        skip_llm: bool = False,
    ) -> tuple[InformationSource, StructuredExtraction | None]:
        """Persist the source, then run LLM extraction.

        Returns (source, extraction_or_None). If LLM is not configured or
        skip_llm=True, returns (source, None) after persisting the source.
        """
        credibility = self._default_credibility(source_kind, user_upload_id is not None)

        source = InformationSource(
            kind=source_kind,
            title=title,
            url=url,
            publisher=publisher,
            published_at=published_at,
            credibility=credibility,
            raw_text=text,
            user_upload_id=user_upload_id,
            user_id=user_id,
        )
        self.db.add(source)
        self.db.flush()
        log.info("structuring.source_created", source_id=source.id, title=title)

        if skip_llm:
            self.db.commit()
            return source, None

        try:
            extraction = self._run_llm_extraction(text)
        except LLMNotConfiguredError:
            log.warning("structuring.llm_not_configured")
            self.db.commit()
            return source, None
        except Exception as exc:  # noqa: BLE001
            log.error("structuring.extraction_failed", error=str(exc))
            self.db.commit()
            return source, None

        self._persist_extraction(source, extraction)
        self.db.commit()
        return source, extraction

    # ---------------- Internals ----------------

    def _default_credibility(self, kind: str, is_user_upload: bool) -> str:
        if is_user_upload:
            return "pending"
        if kind == SourceKind.OFFICIAL.value:
            return "high"
        if kind in (SourceKind.NEWS.value, SourceKind.PUBLIC.value):
            return "medium"
        return "pending"

    def _run_llm_extraction(self, text: str) -> StructuredExtraction:
        """Call Instructor to validate LLM output against StructuredExtraction."""
        client = get_instructor_sync()
        model_name = get_chat_model().model.name
        # Cap input length to keep token costs predictable
        trimmed = text[:16000]

        extraction = client.chat.completions.create(
            model=model_name,
            response_model=StructuredExtraction,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": trimmed},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        return extraction

    def _persist_extraction(
        self, source: InformationSource, extraction: StructuredExtraction
    ) -> int:
        """Write extracted atoms to PG (events/metrics/assertions/relationships)."""
        notifications_triggered = 0

        # Embed events for similarity search (batch)
        event_texts = [
            f"{e.subject} {e.action} {e.object or ''} {e.summary}".strip()
            for e in extraction.events
        ]
        embeddings = embed_texts(event_texts) if event_texts else []

        for idx, atom in enumerate(extraction.events):
            existing, fp = self.dedup.find_duplicate(
                atom.subject, atom.action, atom.object, atom.occurred_at
            )
            if existing is not None:
                log.info(
                    "structuring.duplicate_skipped",
                    subject=atom.subject,
                    action=atom.action,
                )
                continue

            event = Event(
                source_id=source.id,
                user_id=user_id,
                subject=atom.subject,
                action=atom.action,
                object=atom.object,
                occurred_at=atom.occurred_at,
                effective_at=atom.effective_at,
                old_value=atom.old_value,
                new_value=atom.new_value,
                risk_flag_level=atom.risk_flag.level,
                risk_flag_type=atom.risk_flag.type,
                risk_flag_urgency=atom.risk_flag.urgency,
                extraction_confidence=atom.extraction_confidence,
                embedding=embeddings[idx] if idx < len(embeddings) else None,
                half_life_days=self._half_life_for(atom.risk_flag.type),
            )
            self.db.add(event)
            self.db.flush()
            self.dedup.register(
                event,
                fp,
                atom.subject,
                atom.action,
                atom.object,
                None,
            )

            # Mirror into Neo4j graph
            try:
                self.graph.upsert_event(event, source)
            except Exception as exc:  # noqa: BLE001
                log.warning("structuring.graph_mirror_failed", error=str(exc))

            if atom.risk_flag.level == "high":
                notifications_triggered += 1

        # Metrics
        for atom in extraction.metrics:
            self.db.add(
                MetricSnapshot(
                    source_id=source.id,
                    name=atom.name,
                    region=atom.region,
                    value=atom.value,
                    unit=atom.unit,
                    captured_at=atom.captured_at or datetime.now(timezone.utc),
                )
            )

        # Assertions
        for atom in extraction.assertions:
            self.db.add(
                Assertion(
                    source_id=source.id,
                    subject=atom.subject,
                    claim=atom.claim,
                    confidence=atom.confidence,
                )
            )

        # Relationships (resolved loosely by name; precise wiring happens
        # in graph_service when entities are first class)
        for atom in extraction.relationships:
            self.db.add(
                Relationship(
                    source_id=source.id,
                    subject_type=atom.subject_type,
                    subject_id=atom.subject_id or "",
                    object_type=atom.object_type,
                    object_id=atom.object_id or "",
                    type=atom.type,
                    weight=atom.weight,
                    confidence=atom.confidence,
                )
            )

        return notifications_triggered

    def _half_life_for(self, risk_type: str | None) -> int:
        defaults = {
            "policy": 730,    # 2 years
            "economic": 180,  # 6 months
            "security": 90,
            "political": 365,
            "health": 180,
            "operational": 365,
            "other": 365,
        }
        return defaults.get(risk_type or "other", 365)
