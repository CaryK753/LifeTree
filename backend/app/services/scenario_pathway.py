"""Resolve the pathway whose factors should drive a scenario."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.goal import Pathway
from app.models.scenario import Scenario

_SEPARATOR_RE = re.compile(r"[\W_]+", re.UNICODE)


def _normalized_name(value: str) -> str:
    return _SEPARATOR_RE.sub("", value.casefold().strip())


def resolve_scenario_pathway(db: Session, scenario: Scenario) -> Pathway | None:
    """Resolve an explicit, inherited, legacy, or unambiguous pathway link."""
    if scenario.pathway_id:
        pathway = db.get(Pathway, scenario.pathway_id)
        if pathway is not None and pathway.goal_id == scenario.goal_id:
            return pathway

    legacy = db.scalar(
        select(Pathway).where(
            Pathway.scenario_id == scenario.id,
            Pathway.goal_id == scenario.goal_id,
        )
    )
    if legacy is not None:
        return legacy

    if scenario.parent_scenario_id:
        parent = db.get(Scenario, scenario.parent_scenario_id)
        if parent is not None and parent.id != scenario.id:
            inherited = resolve_scenario_pathway(db, parent)
            if inherited is not None:
                return inherited

    pathways = list(
        db.scalars(
            select(Pathway)
            .where(Pathway.goal_id == scenario.goal_id)
            .order_by(Pathway.created_at.asc())
        )
    )
    target_name = _normalized_name(scenario.name)
    name_matches = [p for p in pathways if _normalized_name(p.name) == target_name]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(pathways) == 1:
        return pathways[0]
    return None


__all__ = ["resolve_scenario_pathway"]
