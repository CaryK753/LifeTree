"""Risk area auto-sensing: cluster recent events and surface emerging risks.

Per P1 feature: discovers clusters of related events that don't yet link to a
RiskFactor, asks the LLM to extract a risk theme per cluster, and estimates
how many goals/pathways would be affected if the risk were adopted.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import LLMNotConfiguredError
from app.core.logging import get_logger
from app.models.event import Event, Relationship
from app.models.goal import Goal, Pathway, RiskFactor

log = get_logger(__name__)

_SIM_THRESHOLD = 0.7

_THEME_PROMPT = """You are a risk analyst. Given the following cluster of related events, extract a risk theme.

Events:
{events_text}

You MUST respond with a single valid JSON object conforming EXACTLY to this
schema (no markdown fences, no commentary, no prose outside the JSON):
{{
  "name": "<concise risk name, e.g. US H-1B visa policy tightening>",
  "type": "<one of: policy | economic | security | political | health | operational | other>",
  "region": "<region code e.g. US, CA, or null if global>",
  "urgency": "<one of: normal | elevated | urgent>",
  "description": "<1-2 sentence description of the risk>",
  "affected_pathways_hint": "<brief hint about which pathways might be affected>"
}}

Field requirements:
- name: concise risk name string.
- type: must be one of the enumerated values; lowercase.
- region: ISO-like region code string, or null if the risk is global.
- urgency: must be one of normal / elevated / urgent.
- description: 1-2 sentence string.
- affected_pathways_hint: brief string hint.

Output rules:
- Return ONLY the JSON object. No markdown, no code fences, no prefix/suffix text.
- All six keys must be present. Use null for region when the risk is global.
- Do not invent fields beyond the schema above.
"""


class RiskDiscoveryService:
    """Discover emerging risk themes by clustering recent unlinked events."""

    def __init__(self, db: Session, llm_client=None) -> None:
        self.db = db
        self.llm_client = llm_client

    # ---------------- Public API ----------------

    async def discover_emerging_risks(
        self, user_id: str, days: int = 14, min_cluster_size: int = 3
    ) -> list[dict]:
        """Scan recent events, cluster them, and propose risk themes via LLM."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(Event)
            .where(or_(Event.user_id == user_id, Event.user_id.is_(None)))
            .where(Event.status != "expected")
            .where(Event.occurred_at >= cutoff)
            .order_by(Event.occurred_at.desc())
        )
        events = list(self.db.scalars(stmt))
        if not events:
            return []

        # Exclude events already linked to a RiskFactor via Relationship
        event_ids = [e.id for e in events]
        linked_ids = set(
            self.db.scalars(
                select(Relationship.subject_id).where(
                    Relationship.subject_type == "Event",
                    Relationship.subject_id.in_(event_ids),
                    Relationship.object_type == "RiskFactor",
                )
            )
        )
        unlinked = [e for e in events if e.id not in linked_ids]
        if len(unlinked) < min_cluster_size:
            return []

        clusters = self._cluster_events(unlinked)
        clusters = [c for c in clusters if len(c) >= min_cluster_size]
        if not clusters:
            return []

        proposals: list[dict] = []
        for cluster in clusters:
            theme = await self._extract_theme(cluster)
            if theme is None:
                continue
            region = theme.get("region")
            affected = self._count_affected_goals(region, user_id)
            proposal = {
                "name": theme.get("name", "Unknown risk"),
                "type": theme.get("type", "other"),
                "region": region,
                "urgency": theme.get("urgency", "normal"),
                "description": theme.get("description", ""),
                "cluster_size": len(cluster),
                "sample_events": [e.subject for e in cluster[:3]],
                "affected_goals_count": affected,
                "affected_pathways_hint": theme.get("affected_pathways_hint"),
                "proposal_id": None,
            }
            proposals.append(proposal)

        log.info(
            "risk_discovery.completed",
            user_id=user_id,
            events_scanned=len(unlinked),
            clusters=len(clusters),
            proposals=len(proposals),
        )
        return proposals

    # ---------------- Clustering ----------------

    def _cluster_events(self, events: list[Event]) -> list[list[Event]]:
        """Greedy clustering: pick a seed, group all events with sim > 0.7."""
        embeddings = [getattr(e, "embedding", None) for e in events]
        has_embeddings = all(emb is not None and len(emb) > 0 for emb in embeddings)

        if has_embeddings:
            sim = self._embedding_cosine(embeddings)
        else:
            texts = [f"{e.subject} {e.action}" for e in events]
            sim = self._bow_cosine(texts)

        assigned = [False] * len(events)
        clusters: list[list[Event]] = []
        for i in range(len(events)):
            if assigned[i]:
                continue
            cluster = [events[i]]
            assigned[i] = True
            for j in range(i + 1, len(events)):
                if assigned[j]:
                    continue
                if sim[i][j] >= _SIM_THRESHOLD:
                    cluster.append(events[j])
                    assigned[j] = True
            clusters.append(cluster)
        return clusters

    @staticmethod
    def _embedding_cosine(embeddings: list[list[float]]) -> list[list[float]]:
        mat = np.array(embeddings, dtype=float)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = mat / norms
        return (normalized @ normalized.T).tolist()

    @staticmethod
    def _bow_cosine(texts: list[str]) -> list[list[float]]:
        """Bag-of-words cosine similarity (sklearn-free fallback)."""
        tokenized = [re.findall(r"\w+", t.lower()) for t in texts]
        vocab = sorted({w for tokens in tokenized for w in tokens})
        n = len(texts)
        if not vocab:
            return [[0.0] * n for _ in range(n)]
        idx = {w: i for i, w in enumerate(vocab)}
        mat = np.zeros((n, len(vocab)), dtype=float)
        for i, tokens in enumerate(tokenized):
            for w in tokens:
                mat[i, idx[w]] += 1.0
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = mat / norms
        return (normalized @ normalized.T).tolist()

    # ---------------- LLM theme extraction ----------------

    def _resolve_llm(self) -> tuple[Any, str] | None:
        """Return (async_client, model_name) or None if LLM unavailable."""
        try:
            if self.llm_client is not None:
                from app.llm.client import get_chat_model

                model_name = get_chat_model().model.name
                return self.llm_client, model_name
            from app.llm.client import get_chat_async_client

            return get_chat_async_client()
        except LLMNotConfiguredError:
            log.warning("risk_discovery.llm_not_configured")
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("risk_discovery.llm_resolve_failed", error=str(exc))
            return None

    async def _extract_theme(self, cluster: list[Event]) -> dict | None:
        resolved = self._resolve_llm()
        if resolved is None:
            return None
        client, model_name = resolved

        events_text = "\n".join(
            f"{i + 1}. {e.subject} — {e.action}" for i, e in enumerate(cluster[:15])
        )
        prompt = _THEME_PROMPT.format(events_text=events_text)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a risk analysis assistant. You MUST return ONLY a single "
                    "valid JSON object matching the schema in the user message — no "
                    "markdown, no code fences, no commentary, no prose outside the JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        # Try with JSON response format first; fall back to plain completion
        # for providers that don't support response_format.
        for kwargs in ({"response_format": {"type": "json_object"}}, {}):
            try:
                resp = await client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=500,
                    **kwargs,
                )
                content = resp.choices[0].message.content or ""
                parsed = self._parse_json(content)
                if parsed is not None:
                    return parsed
            except Exception as exc:  # noqa: BLE001
                log.warning("risk_discovery.llm_theme_failed", error=str(exc))
        return None

    @staticmethod
    def _parse_json(content: str) -> dict | None:
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    # ---------------- Impact estimation ----------------

    def _count_affected_goals(self, region: str | None, user_id: str) -> int:
        """Count how many of the user's goals have pathways in this region."""
        stmt = (
            select(Pathway.goal_id)
            .distinct()
            .join(Goal, Goal.id == Pathway.goal_id)
            .where(Goal.user_id == user_id)
        )
        if region:
            stmt = stmt.where(Pathway.region == region)
        return len(set(self.db.scalars(stmt).all()))
