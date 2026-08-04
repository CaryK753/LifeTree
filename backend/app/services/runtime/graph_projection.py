"""Low-level mutation and rebuild helpers for the embedded graph projection."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.postgres import SessionLocal
from app.models.event import Event, InformationSource, Relationship
from app.models.goal import (
    Goal,
    Pathway,
    Requirement,
    RiskFactor,
    pathway_requirements,
    pathway_risk_factors,
)
from app.models.local_graph import LocalGraphEdge, LocalGraphNode
from app.models.scenario import Scenario


def upsert_node(
    db: Session,
    node_id: str,
    node_type: str,
    label: str,
    user_id: str | None,
    properties: dict[str, Any],
) -> None:
    node = db.get(LocalGraphNode, node_id) or LocalGraphNode(node_id=node_id)
    node.node_type, node.label, node.user_id, node.properties = (
        node_type,
        label,
        user_id,
        properties,
    )
    db.add(node)


def upsert_edge(
    db: Session,
    source: str,
    relation: str,
    target: str,
    weight: float = 0.0,
    confidence: float = 0.5,
) -> None:
    edge_id = hashlib.sha256(f"{source}\0{relation}\0{target}".encode()).hexdigest()
    edge = db.get(LocalGraphEdge, edge_id) or LocalGraphEdge(
        edge_id=edge_id,
        source_id=source,
        relation=relation,
        target_id=target,
    )
    edge.weight, edge.confidence = weight or 0.0, confidence or 0.5
    db.add(edge)


def mirror_source_node(db: Session, source: InformationSource) -> None:
    upsert_node(
        db,
        source.id,
        "InformationSource",
        source.title,
        source.user_id,
        {"kind": source.kind, "credibility": source.credibility},
    )


def requirement_pathway_ids(db: Session, requirement: Requirement) -> list[str]:
    ids = list(
        db.scalars(
            select(pathway_requirements.c.pathway_id).where(
                pathway_requirements.c.requirement_id == requirement.id
            )
        )
    )
    if requirement.pathway_id and requirement.pathway_id not in ids:
        ids.append(requirement.pathway_id)
    return ids


def user_for_pathways(db: Session, pathway_ids: list[str]) -> str | None:
    pathway = db.get(Pathway, pathway_ids[0]) if pathway_ids else None
    goal = db.get(Goal, pathway.goal_id) if pathway else None
    return goal.user_id if goal else None


def neighborhood_row(
    edge: LocalGraphEdge,
    nodes: dict[str, LocalGraphNode],
    requested: set[str],
) -> dict[str, Any]:
    reverse = edge.source_id not in requested and edge.target_id in requested
    source_id, target_id = (
        (edge.target_id, edge.source_id) if reverse else (edge.source_id, edge.target_id)
    )
    source, target = nodes.get(source_id), nodes.get(target_id)
    return {
        "source_id": source_id,
        "source_type": source.node_type if source else "Unknown",
        "rel_type": edge.relation,
        "weight": edge.weight,
        "target_id": target_id,
        "target_type": target.node_type if target else "Unknown",
        "label": target.label if target else "",
    }


def risk_row(
    goal: LocalGraphNode,
    pathway: LocalGraphNode,
    risk: LocalGraphNode,
    event_edge: LocalGraphEdge,
    risk_edge: LocalGraphEdge,
) -> dict[str, Any]:
    return {
        "goal_id": goal.node_id,
        "goal_title": goal.label,
        "pathway_id": pathway.node_id,
        "pathway_name": pathway.label,
        "risk_id": risk.node_id,
        "risk_name": risk.label,
        "level": risk.properties.get("level", "low"),
        "type": risk.properties.get("type", "other"),
        "path_weights": [event_edge.weight, risk_edge.weight],
        "path_confidences": [event_edge.confidence, risk_edge.confidence],
    }


def rebuild_projection() -> None:
    with SessionLocal.begin() as db:
        db.execute(delete(LocalGraphEdge))
        db.execute(delete(LocalGraphNode))
        _rebuild_goals_and_pathways(db)
        _rebuild_requirements_and_risks(db)
        _rebuild_evidence_and_scenarios(db)


def _rebuild_goals_and_pathways(db: Session) -> None:
    for goal in db.scalars(select(Goal)):
        upsert_node(db, goal.id, "Goal", goal.title, goal.user_id, {"status": goal.status})
    for pathway in db.scalars(select(Pathway)):
        goal = db.get(Goal, pathway.goal_id)
        upsert_node(
            db,
            pathway.id,
            "Pathway",
            pathway.name,
            goal.user_id if goal else None,
            {"status": pathway.status},
        )
        upsert_edge(db, pathway.goal_id, "HAS_PATHWAY", pathway.id, 1.0)


def _rebuild_requirements_and_risks(db: Session) -> None:
    for requirement in db.scalars(select(Requirement)):
        pathway_ids = requirement_pathway_ids(db, requirement)
        upsert_node(
            db,
            requirement.id,
            "Requirement",
            requirement.name,
            user_for_pathways(db, pathway_ids),
            {"type": requirement.type},
        )
        for pathway_id in pathway_ids:
            upsert_edge(db, pathway_id, "REQUIRES", requirement.id, requirement.weight)
    for risk in db.scalars(select(RiskFactor)):
        upsert_node(
            db,
            risk.id,
            "RiskFactor",
            risk.name,
            risk.user_id,
            {"type": risk.type, "level": risk.level},
        )
        pathway_ids = db.scalars(
            select(pathway_risk_factors.c.pathway_id).where(
                pathway_risk_factors.c.risk_factor_id == risk.id
            )
        )
        for pathway_id in pathway_ids:
            upsert_edge(db, risk.id, "AFFECTS", pathway_id, risk.impact or 0.0)


def _rebuild_evidence_and_scenarios(db: Session) -> None:
    for source in db.scalars(select(InformationSource)):
        mirror_source_node(db, source)
    for event in db.scalars(select(Event)):
        upsert_node(
            db,
            event.id,
            "Event",
            f"{event.subject} {event.action}",
            event.user_id,
            {"risk_level": event.risk_flag_level},
        )
        if event.source_id:
            upsert_edge(db, event.source_id, "EMITTED", event.id, 1.0)
    for scenario in db.scalars(select(Scenario)):
        goal = db.get(Goal, scenario.goal_id)
        upsert_node(
            db,
            scenario.id,
            "Scenario",
            scenario.name,
            goal.user_id if goal else None,
            {"status": scenario.status},
        )
    for relation in db.scalars(select(Relationship)):
        upsert_edge(
            db,
            relation.subject_id,
            relation.type,
            relation.object_id,
            relation.weight,
            relation.confidence,
        )


__all__ = [
    "mirror_source_node",
    "neighborhood_row",
    "rebuild_projection",
    "requirement_pathway_ids",
    "risk_row",
    "upsert_edge",
    "upsert_node",
    "user_for_pathways",
]
