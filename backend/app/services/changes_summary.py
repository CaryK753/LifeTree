"""Changes-summary aggregate service.

Computes a "since last visit" digest of everything that changed for a user:
new events / sources / goals / actions / risk factors / scenarios /
source proposals, completed actions, and the names of risk factors whose
level was touched recently (we can't reconstruct the old level without an
audit log, so we report the current level alongside the name).

Used by the dashboard "变更摘要" banner so the user can see at a glance
what happened while they were away.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.action import Action
from app.models.event import Event, InformationSource
from app.models.goal import Goal, RiskFactor
from app.models.scenario import Scenario
from app.models.source_proposal import SourceProposal
from app.services.risk_scope import risk_scope_clause

log = get_logger(__name__)


class ChangesSummaryService:
    """Aggregate changes for a user since a given timestamp."""

    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _user_or_legacy(self, model):
        """Return a filter clause matching rows owned by ``self.user_id``
        or legacy NULL-user rows (created before per-user isolation).

        Mirrors the scope helper used in ``app.api.events`` so legacy
        global rows remain visible to everyone.
        """
        return or_(model.user_id == self.user_id, model.user_id.is_(None))

    def _count(self, stmt) -> int:
        """Execute a count scalar query."""
        return int(self.db.scalar(stmt) or 0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_summary(self, since: datetime) -> dict[str, Any]:
        """Return an aggregate changes digest since ``since``.

        Counts are user-scoped where the underlying model carries a
        ``user_id`` (events, sources, goals, actions, source proposals).
        Global risk templates remain visible alongside the user's personal
        risks. ``Scenario`` is scoped via its parent ``Goal.user_id``.
        """
        # ---------- Counts ----------
        new_events = self._count(
            select(func.count())
            .select_from(Event)
            .where(self._user_or_legacy(Event), Event.created_at > since)
        )

        new_sources = self._count(
            select(func.count())
            .select_from(InformationSource)
            .where(
                self._user_or_legacy(InformationSource),
                InformationSource.created_at > since,
            )
        )

        new_goals = self._count(
            select(func.count())
            .select_from(Goal)
            .where(Goal.user_id == self.user_id, Goal.created_at > since)
        )

        new_actions = self._count(
            select(func.count())
            .select_from(Action)
            .where(Action.user_id == self.user_id, Action.created_at > since)
        )

        # ``Action.completed_at`` is a String column holding an ISO-8601
        # timestamp (see model). Comparing it to a datetime via SQLAlchemy
        # would require a cast; the spec explicitly allows filtering on
        # ``updated_at`` instead, which is a proper DateTime column.
        completed_actions = self._count(
            select(func.count())
            .select_from(Action)
            .where(
                Action.user_id == self.user_id,
                Action.status == "completed",
                Action.updated_at > since,
            )
        )

        new_risk_factors = self._count(
            select(func.count())
            .select_from(RiskFactor)
            .where(
                RiskFactor.deleted_at.is_(None),
                risk_scope_clause(self.user_id),
                RiskFactor.created_at > since,
            )
        )

        # Scenario is user-scoped via its parent Goal.
        updated_scenarios = self._count(
            select(func.count())
            .select_from(Scenario)
            .join(Goal, Goal.id == Scenario.goal_id)
            .where(
                Goal.user_id == self.user_id,
                Scenario.computed_at.is_not(None),
                Scenario.computed_at > since,
            )
        )

        new_source_proposals = self._count(
            select(func.count())
            .select_from(SourceProposal)
            .where(
                SourceProposal.user_id == self.user_id,
                SourceProposal.created_at > since,
            )
        )

        # ---------- risk_level_changes ----------
        # We can't reconstruct the previous level without an audit log,
        # so we return the names of risk factors touched since with their
        # current level. The frontend treats this as "recently adjusted".
        risk_level_changes: list[dict[str, Any]] = []
        recent_rfs = list(
            self.db.scalars(
                select(RiskFactor).where(
                    RiskFactor.deleted_at.is_(None),
                    risk_scope_clause(self.user_id),
                    RiskFactor.updated_at > since,
                )
            )
        )
        for rf in recent_rfs:
            risk_level_changes.append(
                {
                    "risk_factor_name": rf.name,
                    "old_level": None,  # unknown without audit log
                    "new_level": rf.level,
                }
            )

        # ---------- recent_high_risk_events ----------
        high_risk_rows = list(
            self.db.scalars(
                select(Event)
                .where(
                    self._user_or_legacy(Event),
                    Event.risk_flag_level == "high",
                    Event.created_at > since,
                )
                .order_by(Event.created_at.desc())
                .limit(5)
            )
        )
        recent_high_risk_events: list[dict[str, Any]] = [
            {
                "subject": ev.subject,
                "action": ev.action,
                "occurred_at": ev.occurred_at.isoformat()
                if ev.occurred_at
                else None,
            }
            for ev in high_risk_rows
        ]

        return {
            "since": since.isoformat(),
            "new_events": new_events,
            "new_sources": new_sources,
            "new_goals": new_goals,
            "new_actions": new_actions,
            "completed_actions": completed_actions,
            "new_risk_factors": new_risk_factors,
            "updated_scenarios": updated_scenarios,
            "new_source_proposals": new_source_proposals,
            "risk_level_changes": risk_level_changes,
            "recent_high_risk_events": recent_high_risk_events,
        }
