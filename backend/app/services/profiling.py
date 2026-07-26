"""User profile / progress / implicit-tags updates.

Per project plan §4.4: explicit attributes are filled by the user; implicit
tags are inferred from interactions and used for prioritizing notifications.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.goal import Goal, Pathway, Requirement
from app.models.user import UserProfile

log = get_logger(__name__)


class ProfilingService:
    """Build / update user profiles and recompute progress tags."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------- Gap analysis ----------------

    def compute_progress(self, user: UserProfile) -> dict[str, Any]:
        """Aggregate gap_status across the user's primary goal pathways."""
        if user.primary_goal_id is None:
            return {"requirements_total": 0, "met": 0, "partial": 0, "missing": 0}

        rows = self.db.execute(
            select(Requirement)
            .join(Pathway, Pathway.id == Requirement.pathway_id)
            .where(Pathway.goal_id == user.primary_goal_id)
        ).scalars().all()

        summary: dict[str, int] = {"requirements_total": len(rows)}
        for req in rows:
            summary[req.gap_status] = summary.get(req.gap_status, 0) + 1
        summary.setdefault("met", 0)
        summary.setdefault("partial", 0)
        summary.setdefault("missing", 0)
        return summary

    # ---------------- Implicit tags ----------------

    def infer_implicit_tags(self, user: UserProfile) -> dict[str, Any]:
        """Infer implicit preference tags from explicit inputs.

        Heuristics for MVP:
        - 'security_sensitive' if risk_tolerance == 'low'
        - 'cost_sensitive' if priority_factors contains 'cost'
        - 'speed_priority' if priority_factors contains 'speed'
        """
        tags: dict[str, Any] = {}
        if user.risk_tolerance == "low":
            tags["security_sensitive"] = True
        pf = user.priority_factors or {}
        if "cost" in pf:
            tags["cost_sensitive"] = True
        if "speed" in pf:
            tags["speed_priority"] = True
        if "climate" in pf:
            tags["climate_aware"] = True
        return tags

    # ---------------- Severity escalation ----------------

    def personalize_risk_level(
        self, base_level: str, user: UserProfile, risk_type: str
    ) -> str:
        """Escalate or de-escalate a generic risk level for this user."""
        order = {"low": 1, "medium": 2, "high": 3}
        level = order.get(base_level, 1)

        if user.risk_tolerance == "low":
            level += 1  # Low-tolerance users see things one notch higher
        tags = self.infer_implicit_tags(user)
        if risk_type == "security" and tags.get("security_sensitive"):
            level += 1
        if risk_type == "economic" and tags.get("cost_sensitive"):
            level += 1

        level = max(1, min(3, level))
        reverse = {v: k for k, v in order.items()}
        return reverse[level]

    # ---------------- Profile update ----------------

    def refresh(self, user: UserProfile) -> UserProfile:
        """Recompute progress + implicit tags and persist."""
        user.progress = self.compute_progress(user)
        user.implicit_tags = self.infer_implicit_tags(user)
        self.db.add(user)
        self.db.commit()
        log.info(
            "profiling.refreshed",
            user_id=user.id,
            progress=user.progress,
            tags=user.implicit_tags,
        )
        return user
