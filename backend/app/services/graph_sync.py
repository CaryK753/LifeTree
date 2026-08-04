"""Cross-adapter graph synchronization helpers for relational aggregates."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.goal import Goal, Pathway, Requirement
from app.services.graph import GraphService


def sync_goal_tree(graph: GraphService, db: Session, goal: Goal) -> None:
    """Mirror a goal and nested pathway/requirement rows after one commit."""
    graph.upsert_goal(goal)
    pathways = list(db.scalars(select(Pathway).where(Pathway.goal_id == goal.id)))
    for pathway in pathways:
        graph.upsert_pathway(pathway)
        requirement_ids: set[str] = set()
        for requirement in pathway.requirements:
            graph.upsert_requirement(requirement)
            requirement_ids.add(requirement.id)
        legacy_requirements = db.scalars(
            select(Requirement).where(Requirement.pathway_id == pathway.id)
        )
        for requirement in legacy_requirements:
            if requirement.id not in requirement_ids:
                graph.upsert_requirement(requirement)


__all__ = ["sync_goal_tree"]
