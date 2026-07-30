"""Source auto-discovery service (P1 信源自动发现).

Asks the LLM to propose authoritative information sources for a goal
(official gazettes, news sites, stats APIs, forums), runs a quick Tavily
Extract probe on each candidate URL to verify liveness, and persists the
survivors as ``SourceProposal`` rows awaiting user accept/reject.

Accepting a proposal promotes it to a real ``InformationSource`` with
``auto_refresh=True`` so the per-source refresh beat task picks it up.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, LLMNotConfiguredError, NotFoundError
from app.core.logging import get_logger
from app.llm.client import get_chat_model, get_instructor_sync
from app.models.event import Event, InformationSource
from app.models.goal import Goal, Pathway
from app.models.source_proposal import SourceProposal
from app.services.crawler import CrawlerService

log = get_logger(__name__)


# ---------------- Pydantic schemas for structured LLM output ----------------


class _ProposedSource(BaseModel):
    """A single source candidate returned by the LLM."""

    title: str = Field(..., description="Human-readable source title.")
    url: str = Field(..., description="Canonical URL of the source.")
    publisher: str | None = Field(None, description="Publishing org, if known.")
    kind: str = Field(
        "public",
        description="Source kind: 'official' | 'news' | 'public' | 'other'.",
    )
    relevance: float = Field(
        0.5, ge=0.0, le=1.0, description="Relevance to the goal (0-1)."
    )
    credibility_hint: str = Field(
        "pending",
        description="Credibility hint: 'high' | 'medium' | 'low' | 'pending'.",
    )
    reason: str = Field(..., description="Why this source was suggested.")


class _SourceCandidateList(BaseModel):
    """Structured wrapper so Instructor can validate the full batch."""

    sources: list[_ProposedSource] = Field(
        default_factory=list,
        description="Up to `limit` authoritative information source candidates.",
    )


_SYSTEM_PROMPT = """You are LifeTree's source-discovery agent.

Given a user's goal, optional pathway region, and the subjects of events
already tracked, suggest authoritative information sources the user should
monitor for updates that could affect their plan.

Prioritize, in this order:
1. Official government gazettes / department sites (kind=official, credibility=high)
2. Reputable news outlets covering the domain (kind=news, credibility=medium)
3. Public statistics APIs / datasets (kind=public, credibility=high)
4. High-signal community forums / aggregators (kind=other, credibility=medium)

Rules:
- Each URL must be a real, specific page (not a generic homepage when possible).
- Do not duplicate sources already tracked (listed below).
- `reason` should be one sentence explaining what signal this source provides.
- `relevance` reflects how directly this source impacts the user's goal.
- Return at most the requested number of candidates.
"""


class SourceDiscoveryService:
    """LLM-driven information source auto-discovery."""

    MAX_EVENT_SUBJECTS = 15

    def __init__(self, db: Session, llm_client: Any | None = None) -> None:
        self.db = db
        # llm_client is an instructor.Instructor (sync). Resolved lazily so
        # the service can be constructed even when the LLM isn't configured
        # yet (the call site decides whether to surface that as an error).
        self._llm_client = llm_client

    # ---------------- Public API ----------------

    async def propose_sources(
        self,
        goal: Goal,
        pathway: Pathway | None,
        limit: int = 5,
    ) -> list[SourceProposal]:
        """Discover and persist up to ``limit`` source proposals for ``goal``.

        Each candidate is probed via Tavily Extract; candidates whose URL is
        already tracked (in InformationSource or an active SourceProposal for
        this goal) are skipped. One bad candidate never aborts the batch.
        """
        # Resolve the LLM client + model name up-front so a misconfiguration
        # surfaces as a 503 before we spend time on Tavily probes.
        client = self._llm_client
        if client is None:
            try:
                client = get_instructor_sync()
            except LLMNotConfiguredError:
                raise
        try:
            model_name = get_chat_model().model.name
        except LLMNotConfiguredError:
            model_name = "gpt-4o-mini"  # fallback; instructor will raise anyway

        existing_urls = self._existing_urls(goal)
        event_subjects = self._recent_event_subjects(goal.user_id)

        messages = self._build_prompt(
            goal=goal,
            pathway=pathway,
            event_subjects=event_subjects,
            existing_urls=existing_urls,
            limit=limit,
        )

        # ---- LLM call (sync instructor) ----
        try:
            result: _SourceCandidateList = client.chat.completions.create(
                model=model_name,
                response_model=_SourceCandidateList,
                messages=messages,
                temperature=0.4,
                max_tokens=1600,
                max_retries=2,
            )
            candidates = result.sources
        except Exception as exc:  # noqa: BLE001
            log.error("source_discovery.llm_failed", goal_id=goal.id, error=str(exc))
            return []

        log.info(
            "source_discovery.llm_ok",
            goal_id=goal.id,
            candidates=len(candidates),
        )

        # ---- Probe + persist each candidate ----
        crawler = CrawlerService()
        proposals: list[SourceProposal] = []
        for cand in candidates[:limit]:
            try:
                url = (cand.url or "").strip()
                if not url or url in existing_urls:
                    log.info("source_discovery.skip_dup", url=url)
                    continue

                probe = await self._probe_url(crawler, url)

                proposal = SourceProposal(
                    goal_id=goal.id,
                    user_id=goal.user_id,
                    title=(cand.title or url)[:255],
                    url=url[:1024],
                    kind=(cand.kind or "public")[:32],
                    publisher=(cand.publisher or None),
                    proposed_reason=cand.reason or "",
                    relevance_score=float(max(0.0, min(1.0, cand.relevance or 0.5))),
                    credibility_hint=(cand.credibility_hint or "pending")[:16],
                    status="proposed",
                    probe_result=probe,
                )
                self.db.add(proposal)
                self.db.flush()
                proposals.append(proposal)
                existing_urls.add(url)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "source_discovery.candidate_failed",
                    goal_id=goal.id,
                    url=getattr(cand, "url", None),
                    error=str(exc),
                )
                continue

        if proposals:
            self.db.commit()
        return proposals

    def accept_proposal(self, proposal_id: str, user_id: str) -> InformationSource:
        """Promote a proposal to a real InformationSource with auto-refresh on.

        The proposal is marked ``accepted``. Credibility is derived from the
        proposal's ``credibility_hint``.
        """
        proposal = self._get_owned_proposal(proposal_id, user_id)
        if proposal.status == "rejected":
            raise ConflictError("Rejected source proposal cannot be accepted")
        if proposal.status == "accepted":
            # Idempotent: return the already-created source if present.
            existing = self.db.scalar(
                select(InformationSource).where(
                    InformationSource.user_id == user_id,
                    InformationSource.url == proposal.url,
                    InformationSource.kind == proposal.kind,
                )
            )
            if existing is not None:
                return existing

        credibility = self._credibility_from_hint(proposal.credibility_hint)
        source = InformationSource(
            user_id=user_id,
            kind=proposal.kind,
            title=proposal.title,
            url=proposal.url,
            publisher=proposal.publisher,
            credibility=credibility,
            credibility_score=proposal.relevance_score,
            auto_refresh=True,
            refresh_interval_minutes=1440,
            meta={
                "from_proposal_id": proposal.id,
                "proposed_reason": proposal.proposed_reason,
                "probe_result": proposal.probe_result or {},
            },
        )
        self.db.add(source)
        proposal.status = "accepted"
        self.db.add(proposal)
        self.db.commit()
        self.db.refresh(source)
        log.info(
            "source_discovery.accepted",
            proposal_id=proposal.id,
            source_id=source.id,
        )
        return source

    def reject_proposal(self, proposal_id: str, user_id: str) -> SourceProposal:
        """Mark a proposal as rejected (no InformationSource is created)."""
        proposal = self._get_owned_proposal(proposal_id, user_id)
        if proposal.status == "accepted":
            raise ConflictError("Accepted source proposal cannot be rejected")
        if proposal.status == "rejected":
            return proposal
        proposal.status = "rejected"
        self.db.add(proposal)
        self.db.commit()
        self.db.refresh(proposal)
        log.info("source_discovery.rejected", proposal_id=proposal.id)
        return proposal

    def list_proposals(
        self,
        user_id: str | None,
        goal_id: str | None = None,
        status: str | None = None,
    ) -> list[SourceProposal]:
        """List proposals, optionally filtered by goal and/or status."""
        stmt = select(SourceProposal).order_by(
            SourceProposal.relevance_score.desc(),
            SourceProposal.created_at.desc(),
        )
        if user_id is not None:
            stmt = stmt.where(SourceProposal.user_id == user_id)
        if goal_id:
            stmt = stmt.where(SourceProposal.goal_id == goal_id)
        if status:
            stmt = stmt.where(SourceProposal.status == status)
        return list(self.db.scalars(stmt))

    # ---------------- Internals ----------------

    def _get_owned_proposal(self, proposal_id: str, user_id: str) -> SourceProposal:
        proposal = self.db.get(SourceProposal, proposal_id)
        if proposal is None:
            raise NotFoundError(f"SourceProposal {proposal_id} not found")
        if proposal.user_id != user_id:
            raise NotFoundError(f"SourceProposal {proposal_id} not found")
        return proposal

    def _existing_urls(self, goal: Goal) -> set[str]:
        """URLs already tracked as InformationSource or active SourceProposal."""
        urls: set[str] = set()
        src_urls = self.db.scalars(
            select(InformationSource.url).where(
                InformationSource.user_id == goal.user_id,
                InformationSource.url.is_not(None),
            )
        )
        urls.update(u for u in src_urls if u)

        prop_urls = self.db.scalars(
            select(SourceProposal.url).where(
                SourceProposal.goal_id == goal.id,
                SourceProposal.status.in_(["proposed", "accepted"]),
            )
        )
        urls.update(u for u in prop_urls if u)
        return urls

    def _recent_event_subjects(self, user_id: str) -> list[str]:
        rows = self.db.execute(
            select(Event.subject, Event.action)
            .where(Event.user_id == user_id)
            .order_by(Event.created_at.desc())
            .limit(self.MAX_EVENT_SUBJECTS)
        ).all()
        return [f"{s} {a}".strip() for s, a in rows if s]

    def _build_prompt(
        self,
        *,
        goal: Goal,
        pathway: Pathway | None,
        event_subjects: list[str],
        existing_urls: set[str],
        limit: int,
    ) -> list[dict[str, str]]:
        parts: list[str] = []
        parts.append(f"Goal: {goal.title}")
        if goal.description:
            parts.append(f"Goal description: {goal.description[:300]}")
        parts.append(f"Scenario tag: {goal.scenario}")
        if pathway is not None:
            region = pathway.region or "global"
            parts.append(f"Pathway: {pathway.name} (region={region})")
        if event_subjects:
            parts.append(
                "Recently tracked event subjects:\n"
                + "\n".join(f"  - {s}" for s in event_subjects[: self.MAX_EVENT_SUBJECTS])
            )
        if existing_urls:
            parts.append(
                "Already-tracked URLs (do not suggest these):\n"
                + "\n".join(f"  - {u}" for u in list(existing_urls)[:30])
            )

        user_msg = (
            f"{chr(10).join(parts)}\n\n"
            f"Suggest up to {limit} authoritative information sources to monitor "
            f"for this goal. Return JSON matching the schema."
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

    async def _probe_url(
        self, crawler: CrawlerService, url: str
    ) -> dict[str, Any]:
        """Run a quick Tavily Extract trial and summarize liveness.

        Returns {ok, title_preview, update_frequency_hint, content_length}.
        Failures are non-fatal — the proposal is still persisted with ok=False.
        """
        if not crawler.available:
            return {"ok": False, "title_preview": "", "update_frequency_hint": "unknown", "content_length": 0}

        try:
            results = await crawler.extract(urls=url, extract_depth="basic")
        except Exception as exc:  # noqa: BLE001
            log.warning("source_discovery.probe_failed", url=url, error=str(exc))
            return {"ok": False, "title_preview": "", "update_frequency_hint": "unknown", "content_length": 0}

        if not results:
            return {"ok": False, "title_preview": "", "update_frequency_hint": "unknown", "content_length": 0}

        r = results[0]
        if getattr(r, "failed", False):
            return {
                "ok": False,
                "title_preview": "",
                "update_frequency_hint": "unknown",
                "content_length": 0,
                "error": r.error,
            }
        content = r.content or ""
        return {
            "ok": True,
            "title_preview": content[:120].replace("\n", " ").strip(),
            "update_frequency_hint": self._guess_frequency(content),
            "content_length": len(content),
        }

    @staticmethod
    def _guess_frequency(content: str) -> str:
        """Heuristic update-frequency hint from page content."""
        lower = content.lower()
        if any(k in lower for k in ("daily", "每日报", "updated daily")):
            return "daily"
        if any(k in lower for k in ("weekly", "每周")):
            return "weekly"
        if any(k in lower for k in ("monthly", "月报", "monthly report")):
            return "monthly"
        if any(k in lower for k in ("quarterly", "季报")):
            return "quarterly"
        return "unknown"

    @staticmethod
    def _credibility_from_hint(hint: str) -> str:
        mapping = {
            "high": "high",
            "medium": "medium",
            "low": "low",
            "pending": "pending",
        }
        return mapping.get((hint or "pending").lower(), "pending")
