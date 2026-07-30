"""Persistence adapter for structured reasoning action recommendations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action import Action
from app.models.goal import Goal, Pathway, Requirement
from app.models.scenario import Scenario


def _recommendation_text(item: str | dict[str, Any]) -> tuple[str, str | None]:
    if isinstance(item, dict):
        text = str(item.get("action") or item.get("name") or "")
        requirement_id = item.get("requirement_id")
        return text, str(requirement_id) if requirement_id else None
    return str(item), None


def persist_recommended_actions(
    db: Session,
    *,
    goal: Goal,
    pathway: Pathway | None,
    scenario: Scenario,
    run_id: str,
    recommendations: list[str | dict[str, Any]],
    requirements: list[Requirement],
) -> list[Action]:
    """Persist new recommendations while reusing equivalent open actions."""
    if not recommendations:
        return []

    existing_titles = {
        row.title.casefold().strip()
        for row in db.scalars(
            select(Action).where(
                Action.goal_id == goal.id,
                Action.scenario_id == scenario.id,
                Action.deleted_at.is_(None),
                Action.status.in_(["pending", "in_progress", "deferred"]),
            )
        )
    }
    requirements_by_id = {requirement.id: requirement for requirement in requirements}
    requirements_by_token: dict[str, Requirement] = {}
    for requirement in requirements:
        for token in requirement.name.casefold().split():
            if len(token) >= 4:
                requirements_by_token[token] = requirement

    created: list[Action] = []
    for index, recommendation in enumerate(recommendations):
        description, requirement_id = _recommendation_text(recommendation)
        title = description.strip().split("\n")[0][:255]
        title_identity = title.casefold().strip()
        if not title or title_identity in existing_titles:
            continue

        linked_requirement = requirements_by_id.get(requirement_id or "")
        if linked_requirement is None:
            linked_requirement = next(
                (
                    requirements_by_token[token]
                    for token in title.casefold().split()
                    if token in requirements_by_token
                ),
                None,
            )
        lift = 0.02
        if linked_requirement and linked_requirement.gap_delta is not None:
            lift = max(
                0.02,
                min(0.2, abs(float(linked_requirement.gap_delta)) * 0.1),
            )

        action = Action(
            user_id=goal.user_id,
            goal_id=goal.id,
            scenario_id=scenario.id,
            pathway_id=pathway.id if pathway else None,
            requirement_id=linked_requirement.id if linked_requirement else None,
            title=title,
            description=description,
            status="pending",
            cost=0.5,
            expected_prob_lift=lift,
            source="reasoning",
            source_run_id=run_id,
            meta={"order": index},
        )
        db.add(action)
        created.append(action)
        existing_titles.add(title_identity)

    if created:
        db.flush()
    return created


__all__ = ["persist_recommended_actions"]
