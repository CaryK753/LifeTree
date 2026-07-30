"""Persist evolution projections, branch counterfactuals, and score outcomes."""

from __future__ import annotations

import calendar
import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.event import Event, Relationship
from app.models.intelligence import EvolutionMilestone
from app.models.scenario import Scenario, ScenarioStatus
from app.services.graph import GraphService


class EvolutionFeedbackService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.graph = GraphService()

    def persist_projection(
        self, scenario: Scenario, user_id: str, events: list
    ) -> dict[str, int]:
        created = 0
        branches = 0
        now = datetime.now(UTC)
        for projected in events:
            data = projected.model_dump() if hasattr(projected, "model_dump") else projected
            key = self._projection_key(data)
            milestone = self.db.scalar(select(EvolutionMilestone).where(
                EvolutionMilestone.scenario_id == scenario.id,
                EvolutionMilestone.projection_key == key,
            ))
            due_at = self._add_months(now, int(data["month"]))
            if milestone is None:
                expected_event = Event(
                    user_id=user_id,
                    subject=scenario.name,
                    action="expected_milestone",
                    object=data["title"],
                    occurred_at=due_at,
                    effective_at=due_at,
                    extraction_confidence=float(data["probability"]),
                    status="expected",
                    risk_flag_level="high" if data["type"] == "risk" else None,
                    meta={"scenario_id": scenario.id, "projection_key": key},
                )
                self.db.add(expected_event)
                self.db.flush()
                milestone = EvolutionMilestone(
                    user_id=user_id,
                    goal_id=scenario.goal_id,
                    scenario_id=scenario.id,
                    projection_key=key,
                    title=data["title"],
                    event_type=data["type"],
                    description=data.get("description") or "",
                    due_at=due_at,
                    probability=float(data["probability"]),
                    impact=float(data["impact"]),
                    expected_event_id=expected_event.id,
                    meta={"dependencies": data.get("dependencies", [])},
                )
                self.db.add(milestone)
                self.db.flush()
                self.db.add(Relationship(
                    subject_type="Event",
                    subject_id=expected_event.id,
                    object_type="Scenario",
                    object_id=scenario.id,
                    type="EXPECTED_IN",
                    weight=float(data["impact"]),
                    confidence=float(data["probability"]),
                    meta={"projection_key": key},
                ))
                self.graph.upsert_event(expected_event, None)
                self.graph.link_expected_event_to_scenario(expected_event.id, scenario.id)
                created += 1
            else:
                milestone.due_at = due_at
                milestone.probability = float(data["probability"])
                milestone.impact = float(data["impact"])
                milestone.description = data.get("description") or ""
                self.db.add(milestone)

            if self._needs_counterfactual(data):
                branches += int(self._ensure_counterfactual(scenario, milestone))
        self.db.flush()
        return {"milestones_created": created, "branches_created": branches}

    def compare_due(self, now: datetime | None = None) -> dict[str, int]:
        current = now or datetime.now(UTC)
        due = list(self.db.scalars(select(EvolutionMilestone).where(
            EvolutionMilestone.status == "expected",
            EvolutionMilestone.due_at <= current,
        )))
        matched = 0
        for milestone in due:
            candidates = list(self.db.scalars(select(Event).where(
                or_(Event.user_id == milestone.user_id, Event.user_id.is_(None)),
                Event.status == "approved",
                Event.occurred_at >= milestone.due_at - timedelta(days=45),
                Event.occurred_at <= milestone.due_at + timedelta(days=45),
            ).limit(200)))
            best_event, score = self._best_match(milestone, candidates)
            if best_event is not None and score >= 0.55:
                milestone.status = "occurred"
                milestone.matched_event_id = best_event.id
                matched += 1
            else:
                milestone.status = "missed"
            milestone.comparison_score = score
            self.db.add(milestone)
        self.db.commit()
        return {"evaluated": len(due), "matched": matched}

    def calibration(self, user_id: str | None = None) -> dict:
        stmt = select(EvolutionMilestone).where(
            EvolutionMilestone.status.in_(["occurred", "missed"])
        )
        if user_id:
            stmt = stmt.where(EvolutionMilestone.user_id == user_id)
        rows = list(self.db.scalars(stmt))
        if not rows:
            return {"sample_size": 0, "brier_score": 0.0, "calibrated": False}
        score = sum(
            (row.probability - (1.0 if row.status == "occurred" else 0.0)) ** 2
            for row in rows
        ) / len(rows)
        return {
            "sample_size": len(rows),
            "brier_score": round(score, 6),
            "calibrated": len(rows) >= 50,
        }

    def _ensure_counterfactual(
        self, parent: Scenario, milestone: EvolutionMilestone
    ) -> bool:
        children = list(self.db.scalars(select(Scenario).where(
            Scenario.parent_scenario_id == parent.id
        )))
        if any(
            (child.assumptions or {}).get("evolution_milestone_id") == milestone.id
            for child in children
        ):
            return False
        branch = Scenario(
            id=str(uuid.uuid4()),
            goal_id=parent.goal_id,
            pathway_id=parent.pathway_id,
            parent_scenario_id=parent.id,
            status=ScenarioStatus.DRAFT.value,
            name=f"反事实：{milestone.title}"[:255],
            assumptions={
                "evolution_milestone_id": milestone.id,
                "assume_event_occurs": True,
                "projected_probability": milestone.probability,
                "projected_impact": milestone.impact,
            },
            impact_threshold=max(0.05, abs(milestone.impact)),
        )
        self.db.add(branch)
        self.db.flush()
        self.graph.upsert_scenario(branch)
        return True

    @staticmethod
    def _needs_counterfactual(data: dict) -> bool:
        return (
            data.get("type") == "risk"
            and float(data.get("probability", 1.0)) <= 0.35
            and float(data.get("impact", 0.0)) <= -0.2
        )

    @staticmethod
    def _projection_key(data: dict) -> str:
        normalized = re.sub(r"\W+", "", str(data.get("title", "")).lower())
        return hashlib.sha256(f"{data.get('type')}|{normalized}".encode()).hexdigest()

    @staticmethod
    def _add_months(value: datetime, months: int) -> datetime:
        month_index = value.month - 1 + months
        year = value.year + month_index // 12
        month = month_index % 12 + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return value.replace(year=year, month=month, day=day)

    @staticmethod
    def _best_match(
        milestone: EvolutionMilestone, events: list[Event]
    ) -> tuple[Event | None, float]:
        best_event = None
        best_score = 0.0
        expected = f"{milestone.title} {milestone.description}".lower()
        for event in events:
            actual = f"{event.subject} {event.action} {event.object or ''}".lower()
            score = SequenceMatcher(None, expected, actual).ratio()
            if score > best_score:
                best_event, best_score = event, score
        return best_event, round(best_score, 6)
