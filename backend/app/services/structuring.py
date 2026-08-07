"""Information structuring pipeline.

Takes raw text (from crawler or user upload), asks the LLM to produce a
StructuredExtraction, dedups against existing events, and writes new
atoms to PostgreSQL + Neo4j. Per project plan §4.1.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
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

You MUST respond with a single valid JSON object conforming EXACTLY to this
schema (no markdown fences, no commentary, no prose outside the JSON):
{
  "events": [
    {
      "subject": "<entity doing the action>",
      "action": "<verb phrase>",
      "object": "<entity acted upon, or empty string>",
      "occurred_at": "<ISO 8601 date or null>",
      "effective_at": "<ISO 8601 date or null>",
      "old_value": "<string or null>",
      "new_value": "<string or null>",
      "risk_flag": {
        "level": "<one of: low | medium | high>",
        "type": "<one of: policy | economic | security | political | health | operational | other>",
        "urgency": "<one of: normal | elevated | urgent>",
        "rationale": "<short string>"
      },
      "extraction_confidence": <float 0-1>,
      "summary": "<one-sentence summary>"
    }
  ],
  "metrics": [
    {
      "name": "<metric name>",
      "region": "<region code or null>",
      "value": <number>,
      "unit": "<unit string or null>",
      "captured_at": "<ISO 8601 date or null>",
      "risk_flag": { "level": "...", "type": "...", "urgency": "...", "rationale": "..." }
    }
  ],
  "assertions": [
    {
      "subject": "<entity making the claim>",
      "predicate": "<relationship verb>",
      "claim": "<the claim text>",
      "object_value": "<any value or null>",
      "valid_from": "<ISO 8601 or null>",
      "valid_to": "<ISO 8601 or null>",
      "confidence": <float 0-1>,
      "conflicts_with": ["<other assertion predicate>", ...],
      "risk_flag": { "level": "...", "type": "...", "urgency": "...", "rationale": "..." }
    }
  ],
  "relationships": [
    {
      "subject_type": "<one of: goal | pathway | scenario | event | metric | assertion | requirement | document | source | user>",
      "subject_id": "<id or null>",
      "subject_name": "<name>",
      "object_type": "<one of: goal | pathway | scenario | event | metric | assertion | requirement | document | source | user>",
      "object_id": "<id or null>",
      "object_name": "<name>",
      "type": "<one of: AFFECTS | REQUIRES | ALTERNATIVE_TO | WARNS | EQUALS | CAUSES>",
      "weight": <float -1 to +1>,
      "confidence": <float 0-1>
    }
  ],
  "source_summary": "<1-2 sentence summary of the source>",
  "language": "<ISO 639-1 code e.g. en, zh, es, de, fr>",
  "overall_confidence": <float 0-1>
}

Field requirements:
- events: discrete things that happened (subject/action/object/time/old→new).
- metrics: numeric data points (e.g. CRS cutoff = 510).
- assertions: unconfirmed claims.
- relationships: causal / correlation edges between ontology entities.
  - type must be one of: AFFECTS, REQUIRES, ALTERNATIVE_TO, WARNS, EQUALS, CAUSES.
  - subject_type / object_type must be one of: goal, pathway, scenario, event,
    metric, assertion, requirement, document, source, user.
- risk_flag (when present) must contain level, type, urgency, rationale.
  - level: one of low / medium / high.
  - type: one of policy / economic / security / political / health / operational / other.
  - urgency: one of normal / elevated / urgent.

Rules:
- Be conservative: only emit an atom if the source supports it directly.
- Mark risk_flag.level = high only for events likely to materially change
  a user's plan (e.g. policy cutoffs, program suspensions, currency shocks).
- Use ISO 8601 for all timestamps.
- If a field is unknown, omit it (do not invent values).
- extraction_confidence reflects how clearly the source supports the atom.

Output rules:
- Return ONLY the JSON object. No markdown, no code fences, no prefix/suffix text.
- All top-level keys (events, metrics, assertions, relationships, source_summary,
  language, overall_confidence) must be present; use empty arrays when no items
  of a given type were found.
- Do not invent fields beyond the schema above.
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
        meta: dict[str, Any] | None = None,
    ) -> tuple[InformationSource, StructuredExtraction | None]:
        """Persist the source, then run LLM extraction.

        Returns (source, extraction_or_None). If LLM is not configured or
        skip_llm=True, returns (source, None) after persisting the source.

        Args:
            meta: Optional metadata dict merged into ``InformationSource.meta``.
                Used by the multi-source search layer to record which engine
                produced the source (e.g. ``{"engine": "exa"}``), which is
                later inherited by Assertions for cross-engine consensus
                voting (§B.1 of the cross-validation spec).
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
            meta=dict(meta) if meta else {},
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

        _, assertion_ids = self._persist_extraction(source, extraction, user_id=user_id)
        self.db.commit()

        # §B.3: trigger incremental conflict detection for newly-written
        # Assertions. The scan is scoped to the (subject, predicate) pairs
        # of these Assertions only (see detect_conflicts_node incremental
        # mode), so it is cheap and does not scan the whole table.
        if assertion_ids and user_id:
            try:
                from app.services.cross_validation import CrossValidationService

                CrossValidationService(self.db, user_id).detect_conflicts_for_assertions(
                    assertion_ids
                )
                self.db.commit()
            except Exception as exc:  # noqa: BLE001
                log.warning("structuring.conflict_detection_failed", error=str(exc))

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
        self,
        source: InformationSource,
        extraction: StructuredExtraction,
        *,
        user_id: str | None = None,
    ) -> tuple[int, list[str]]:
        """Write extracted atoms to PG (events/metrics/assertions/relationships).

        Returns ``(notifications_triggered, assertion_ids)``. The
        ``assertion_ids`` are the IDs of newly-persisted Assertions, used
        by :meth:`ingest_text` to trigger incremental conflict detection
        (§B.3 of the cross-validation spec).
        """
        notifications_triggered = 0
        new_assertions: list[tuple[Assertion, Any]] = []

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

            status = self._classify_atom_status(
                confidence=atom.extraction_confidence,
                impact_level=atom.risk_flag.level if atom.risk_flag else None,
            )

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
                risk_flag_level=atom.risk_flag.level if atom.risk_flag else None,
                risk_flag_type=atom.risk_flag.type if atom.risk_flag else None,
                risk_flag_urgency=atom.risk_flag.urgency if atom.risk_flag else None,
                extraction_confidence=atom.extraction_confidence,
                status=status,
                embedding=embeddings[idx] if idx < len(embeddings) else None,
                half_life_days=self._half_life_for(atom.risk_flag.type if atom.risk_flag else None),
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

            # §4.9: low-confidence + high-impact events auto-spawn a
            # lightweight "存疑子分支" off the user's primary goal so the
            # reasoning engine can independently compute the potential
            # impact without polluting the main scenario.
            if status == "pending_review":
                try:
                    self._spawn_review_branch(event, user_id=user_id)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "structuring.branch_spawn_failed",
                        event_id=event.id,
                        error=str(exc),
                    )

            if atom.risk_flag and atom.risk_flag.level == "high":
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

        # Assertions — inherit engine provenance from the source's meta.
        engine = source.meta.get("engine") if source.meta else None
        for atom in extraction.assertions:
            assertion = Assertion(
                source_id=source.id,
                user_id=user_id,
                subject=atom.subject,
                predicate=atom.predicate,
                claim=atom.claim,
                object_value=atom.object_value,
                confidence=atom.confidence,
                valid_from=atom.valid_from,
                valid_to=atom.valid_to,
                observed_at=datetime.now(timezone.utc),
                content_hash=hashlib.sha256(
                    f"{atom.subject}|{atom.predicate}|{atom.claim}".encode()
                ).hexdigest(),
                source_excerpt=atom.claim[:1000],
                engine=engine,
            )
            # §B.3: store LLM conflicts_with hint in meta for traceability.
            if atom.conflicts_with:
                assertion.meta = {"llm_conflicts_with_hint": atom.conflicts_with}
            self.db.add(assertion)
            new_assertions.append((assertion, atom))

        # Flush to populate Assertion IDs (needed for conflict detection
        # and for conflicts_with hint pre-linking).
        if new_assertions:
            self.db.flush()
            if user_id:
                for assertion, atom in new_assertions:
                    if atom.conflicts_with:
                        self._apply_conflicts_with_hint(assertion, user_id)

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

        assertion_ids = [a.id for a, _ in new_assertions]
        return notifications_triggered, assertion_ids

    @staticmethod
    def _value_key(v: Any) -> str:
        """Normalize an object_value for equality comparison."""
        if v is None or v == "":
            return "__none__"
        return str(v)

    def _apply_conflicts_with_hint(
        self, assertion: Assertion, user_id: str
    ) -> None:
        """Pre-fill ``conflicting_with_id`` from the LLM hint (§B.3).

        The LLM's ``conflicts_with`` field is a free-form string hint, not
        a reliable predicate reference. We use it only as a signal to look
        for an existing Assertion with the same (subject, predicate) but a
        different ``object_value``. If found, we pre-link via
        ``conflicting_with_id``. The authoritative conflict detection
        (``detect_conflicts``) runs afterwards and may override this link.
        """
        existing = self.db.scalar(
            select(Assertion).where(
                Assertion.user_id == user_id,
                Assertion.subject == assertion.subject,
                Assertion.predicate == assertion.predicate,
                Assertion.status.in_(["open", "confirmed"]),
                Assertion.id != assertion.id,
            )
        )
        if existing is None:
            return
        # Only pre-link if the object_values actually differ — otherwise
        # it's a corroboration, not a conflict.
        if self._value_key(existing.object_value) != self._value_key(assertion.object_value):
            assertion.conflicting_with_id = existing.id
            self.db.add(assertion)

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

    def _classify_atom_status(self, confidence: float, impact_level: str | None) -> str:
        """Route atom status based on confidence score and impact level per §4.9.

        Rules:
        - confidence >= 0.8: auto-approve ('approved')
        - confidence < 0.8 and impact >= 'high': route to review inbox ('pending_review')
        - confidence < 0.8 and impact < 'high': auto-sink with low weight ('sunk_low_weight')
        """
        if confidence >= 0.8:
            return "approved"

        impact = (impact_level or "low").lower()
        if impact in ("high", "critical"):
            return "pending_review"

        return "sunk_low_weight"

    def _spawn_review_branch(self, event: Event, *, user_id: str | None) -> None:
        """§4.9: auto-spawn a lightweight '存疑子分支' for a pending_review event.

        Finds the user's primary goal (falling back to the most recently
        created goal), locates the latest scenario for that goal, and
        spawns a DRAFT child branch carrying the uncertain event as an
        assumption. The reasoning engine can later run on this branch to
        compute the potential impact without polluting the main scenario.

        Silently no-ops when the user has no goals or no scenarios — the
        event itself is still persisted, just without a parallel branch.
        """
        if user_id is None:
            return

        # Lazy imports to avoid circular dependencies at module load time.
        from app.models.goal import Goal
        from app.models.scenario import Scenario
        from app.services.scenarios import ScenarioService

        # Find the user's primary goal, falling back to the newest goal.
        goal = self.db.scalar(
            select(Goal)
            .where(Goal.user_id == user_id)
            .order_by(Goal.created_at.desc())
        )
        if goal is None:
            log.info("structuring.branch_skip_no_goal", user_id=user_id, event_id=event.id)
            return

        # Find the latest scenario for this goal to use as the parent.
        parent = self.db.scalar(
            select(Scenario)
            .where(Scenario.goal_id == goal.id)
            .order_by(
                Scenario.computed_at.desc().nullslast(),
                Scenario.created_at.desc(),
            )
        )

        svc = ScenarioService(self.db)
        branch_name = f"存疑分支: {event.subject} {event.action}"
        assumptions = {
            "pending_review_event_id": event.id,
            "pending_review_subject": event.subject,
            "pending_review_action": event.action,
            "extraction_confidence": event.extraction_confidence,
            "risk_flag_level": event.risk_flag_level,
            "note": "低置信度+高影响事件触发的自动存疑分支；待用户审核后合并或关闭。",
        }

        if parent is None:
            # No parent scenario — create a top-level draft branch instead.
            svc.create_branch(
                goal_id=goal.id,
                name=branch_name,
                description=(
                    f"自动生成于事件审核：{event.subject} {event.action}。"
                    f"置信度 {event.extraction_confidence:.2f}，影响等级 {event.risk_flag_level}。"
                ),
            )
        else:
            svc.spawn_branch(
                parent,
                name=branch_name,
                assumptions=assumptions,
            )
        log.info(
            "structuring.review_branch_spawned",
            event_id=event.id,
            goal_id=goal.id,
            parent_scenario_id=parent.id if parent else None,
        )
