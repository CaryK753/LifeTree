"""SQLite-backed graph projection for the local desktop runtime."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select

from app.db.postgres import SessionLocal
from app.models.event import Event, InformationSource, Relationship
from app.models.goal import (
    Goal,
    Pathway,
    Requirement,
    RiskFactor,
    pathway_risk_factors,
)
from app.models.local_graph import LocalGraphEdge, LocalGraphNode
from app.models.scenario import Scenario
from app.services.runtime.graph_projection import (
    mirror_source_node,
    neighborhood_row,
    rebuild_projection,
    requirement_pathway_ids,
    risk_row,
    upsert_edge,
    upsert_node,
    user_for_pathways,
)


class EmbeddedGraphStore:
    """Maintain a rebuildable node/edge projection in the local SQLite DB."""

    def mirror_goal(self, goal: Goal) -> None:
        with SessionLocal.begin() as db:
            upsert_node(
                db,
                goal.id,
                "Goal",
                goal.title,
                goal.user_id,
                {
                    "scenario": goal.scenario,
                    "status": goal.status,
                    "target_date": str(goal.target_date) if goal.target_date else None,
                },
            )

    def mirror_pathway(self, pathway: Pathway) -> None:
        with SessionLocal.begin() as db:
            goal = db.get(Goal, pathway.goal_id)
            user_id = goal.user_id if goal else None
            upsert_node(
                db,
                pathway.id,
                "Pathway",
                pathway.name,
                user_id,
                {
                    "region": pathway.region,
                    "status": pathway.status,
                },
            )
            upsert_edge(db, pathway.goal_id, "HAS_PATHWAY", pathway.id, 1.0)

    def mirror_requirement(self, requirement: Requirement) -> None:
        with SessionLocal.begin() as db:
            pathway_ids = requirement_pathway_ids(db, requirement)
            user_id = user_for_pathways(db, pathway_ids)
            upsert_node(
                db,
                requirement.id,
                "Requirement",
                requirement.name,
                user_id,
                {
                    "type": requirement.type,
                    "gap_status": requirement.gap_status,
                },
            )
            for pathway_id in pathway_ids:
                upsert_edge(db, pathway_id, "REQUIRES", requirement.id, requirement.weight)

    def mirror_risk_factor(self, risk: RiskFactor) -> None:
        with SessionLocal.begin() as db:
            upsert_node(
                db,
                risk.id,
                "RiskFactor",
                risk.name,
                risk.user_id,
                {
                    "type": risk.type,
                    "level": risk.level,
                    "urgency": risk.urgency,
                },
            )
            pathway_ids = db.scalars(
                select(pathway_risk_factors.c.pathway_id).where(
                    pathway_risk_factors.c.risk_factor_id == risk.id
                )
            )
            for pathway_id in pathway_ids:
                upsert_edge(db, risk.id, "AFFECTS", pathway_id, risk.impact or 0.0)

    def mirror_source(self, source: InformationSource) -> None:
        with SessionLocal.begin() as db:
            mirror_source_node(db, source)

    def mirror_event(self, event: Event, source: InformationSource | None) -> None:
        with SessionLocal.begin() as db:
            if source is not None:
                mirror_source_node(db, source)
            upsert_node(
                db,
                event.id,
                "Event",
                f"{event.subject} {event.action}",
                event.user_id,
                {
                    "object": event.object,
                    "risk_level": event.risk_flag_level,
                    "risk_type": event.risk_flag_type,
                    "urgency": event.risk_flag_urgency,
                },
            )
            if event.source_id:
                upsert_edge(db, event.source_id, "EMITTED", event.id, 1.0)

    def mirror_scenario(self, scenario: Scenario) -> None:
        with SessionLocal.begin() as db:
            goal = db.get(Goal, scenario.goal_id)
            upsert_node(
                db,
                scenario.id,
                "Scenario",
                scenario.name,
                goal.user_id if goal else None,
                {
                    "status": scenario.status,
                    "parent_id": scenario.parent_scenario_id,
                },
            )
            if scenario.parent_scenario_id:
                upsert_edge(db, scenario.parent_scenario_id, "BRANCHES_TO", scenario.id, 1.0)
            if scenario.pathway_id:
                upsert_edge(db, scenario.pathway_id, "BELONGS_TO", scenario.id, 1.0)

    def link_event_to_risk(
        self, event_id: str, risk_id: str, weight: float, confidence: float
    ) -> None:
        with SessionLocal.begin() as db:
            upsert_edge(db, event_id, "AFFECTS", risk_id, weight, confidence)

    def link_expected_event(self, event_id: str, scenario_id: str) -> None:
        with SessionLocal.begin() as db:
            upsert_edge(db, event_id, "EXPECTED_IN", scenario_id, 1.0)

    def neighborhood(self, node_ids: list[str], limit: int) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            edges = list(
                db.scalars(
                    select(LocalGraphEdge)
                    .where(
                        or_(
                            LocalGraphEdge.source_id.in_(node_ids),
                            LocalGraphEdge.target_id.in_(node_ids),
                        )
                    )
                    .limit(limit)
                )
            )
            ids = {item for edge in edges for item in (edge.source_id, edge.target_id)}
            nodes = {
                node.node_id: node
                for node in db.scalars(
                    select(LocalGraphNode).where(LocalGraphNode.node_id.in_(ids))
                )
            }
            return [neighborhood_row(edge, nodes, set(node_ids)) for edge in edges]

    def propagate_risk(self, event_id: str) -> list[dict[str, Any]]:
        with SessionLocal.begin() as db:
            relationships = db.scalars(
                select(Relationship).where(Relationship.subject_id == event_id)
            )
            for relationship in relationships:
                upsert_edge(
                    db,
                    relationship.subject_id,
                    relationship.type,
                    relationship.object_id,
                    relationship.weight,
                    relationship.confidence,
                )
            db.flush()
            event_edges = list(
                db.scalars(
                    select(LocalGraphEdge).where(
                        LocalGraphEdge.source_id == event_id,
                        LocalGraphEdge.relation == "AFFECTS",
                    )
                )
            )
            rows: list[dict[str, Any]] = []
            for event_edge in event_edges:
                risk = db.get(LocalGraphNode, event_edge.target_id)
                if risk is None or risk.node_type != "RiskFactor":
                    continue
                for risk_edge in db.scalars(
                    select(LocalGraphEdge).where(
                        LocalGraphEdge.source_id == risk.node_id,
                        LocalGraphEdge.relation == "AFFECTS",
                    )
                ):
                    pathway = db.get(LocalGraphNode, risk_edge.target_id)
                    if pathway is None or pathway.node_type != "Pathway":
                        continue
                    goal_edges = db.scalars(
                        select(LocalGraphEdge).where(
                            LocalGraphEdge.target_id == pathway.node_id,
                            LocalGraphEdge.relation == "HAS_PATHWAY",
                        )
                    )
                    for goal_edge in goal_edges:
                        goal = db.get(LocalGraphNode, goal_edge.source_id)
                        if goal is not None:
                            rows.append(risk_row(goal, pathway, risk, event_edge, risk_edge))
            return rows

    def rebuild(self) -> None:
        rebuild_projection()


__all__ = ["EmbeddedGraphStore"]
