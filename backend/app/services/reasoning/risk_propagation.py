"""Risk-propagation over the knowledge graph.

Per project plan §4.2 + §4.5: when an Event lands, traverse the graph
Goal ← Pathway ← RiskFactor ← Event, computing a propagated risk score
per (goal, scenario) tuple and emitting personalized notifications.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.redis import get_redis
from app.models.event import Event
from app.models.goal import Goal
from app.models.notification import RiskAssessment, RiskPropagationLog
from app.models.user import UserProfile
from app.services.graph import GraphService
from app.services.profiling import ProfilingService

log = get_logger(__name__)


class RiskPropagationEngine:
    """Graph-traversal risk propagation + audit log writer."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.graph = GraphService()
        self.profiling = ProfilingService(db)

    # ---------------- Public API ----------------

    def propagate_from_event(self, event: Event) -> list[RiskAssessment]:
        """Walk the graph from `event` and refresh affected RiskAssessments."""
        if event.risk_flag_level is None:
            return []

        started = datetime.now(UTC)
        impacted = self.graph.propagate_risk(event.id)

        if not impacted:
            log.info("risk_propagation.no_impact", event_id=event.id)
            return []

        # Find users owning the impacted goals
        assessments: list[RiskAssessment] = []
        for row in impacted:
            goal = self.db.get(Goal, row.get("goal_id"))
            if goal is None:
                continue
            user = self.db.get(UserProfile, goal.user_id)
            if user is None:
                continue

            personalized_level = self.profiling.personalize_risk_level(
                base_level=row.get("level", "low"),
                user=user,
                risk_type=row.get("type", "other"),
            )
            overall_risk = self._level_to_score(personalized_level)

            assessment = self._upsert_assessment(
                user_id=user.id,
                goal_id=goal.id,
                scenario_id=None,
                overall_risk=overall_risk,
                factor_scores=[
                    {
                        "factor_id": row.get("risk_id"),
                        "name": row.get("risk_name"),
                        "level": personalized_level,
                        "contribution": overall_risk,
                    }
                ],
            )
            assessments.append(assessment)

        # Audit log
        elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        self.db.add(
            RiskPropagationLog(
                event_id=event.id,
                goal_id=impacted[0].get("goal_id") if impacted else None,
                path=[{"row": r} for r in impacted],
                initial_risk=self._level_to_score(impacted[0].get("level", "low")),
                final_risk=assessments[0].overall_risk if assessments else 0.0,
                duration_ms=elapsed_ms,
            )
        )
        self.db.commit()
        log.info(
            "risk_propagation.completed",
            event_id=event.id,
            impacted=len(impacted),
            assessments=len(assessments),
            ms=elapsed_ms,
        )
        # Best-effort SSE push so connected clients refresh their risk view.
        # A Redis hiccup must never break the propagation pipeline.
        for a in assessments:
            self._publish_sse(a)
        return assessments

    # ---------------- SSE push ----------------

    def _publish_sse(self, assessment: RiskAssessment) -> None:
        """Publish a risk_alert event to the user's SSE channel."""
        if get_settings().lifetree_storage_mode == "local":
            return
        try:
            payload = {
                "type": "risk_alert",
                "data": {
                    "id": assessment.id,
                    "user_id": assessment.user_id,
                    "goal_id": assessment.goal_id,
                    "scenario_id": assessment.scenario_id,
                    "overall_risk": assessment.overall_risk,
                    "factor_scores": assessment.factor_scores or [],
                    "computed_at": assessment.computed_at.isoformat()
                    if assessment.computed_at
                    else None,
                },
            }
            get_redis().publish(
                f"lifetree:risk:{assessment.user_id}",
                json.dumps(payload, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "risk_propagation.sse_publish_failed",
                user_id=assessment.user_id,
                error=str(exc),
            )

    # ---------------- Helpers ----------------

    def _upsert_assessment(
        self,
        *,
        user_id: str,
        goal_id: str,
        scenario_id: str | None,
        overall_risk: float,
        factor_scores: list[dict[str, Any]],
    ) -> RiskAssessment:
        existing = self.db.scalar(
            select(RiskAssessment).where(
                RiskAssessment.user_id == user_id,
                RiskAssessment.goal_id == goal_id,
                RiskAssessment.scenario_id == scenario_id,
            )
        )
        if existing is not None:
            existing.overall_risk = overall_risk
            existing.factor_scores = factor_scores
            existing.computed_at = datetime.now(UTC)
            self.db.add(existing)
            return existing
        assessment = RiskAssessment(
            user_id=user_id,
            goal_id=goal_id,
            scenario_id=scenario_id,
            overall_risk=overall_risk,
            factor_scores=factor_scores,
        )
        self.db.add(assessment)
        return assessment

    @staticmethod
    def _level_to_score(level: str) -> float:
        return {"low": 0.2, "medium": 0.5, "high": 0.8}.get(level, 0.2)
