"""Knowledge graph snapshot endpoint for the frontend graph view."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.models.event import Event, Relationship
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.schemas.api import GraphEdge, GraphNode, GraphSnapshot
from app.services.graph import GraphService

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/{goal_id}", response_model=GraphSnapshot)
def get_graph(
    goal_id: str,
    scenario_id: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> GraphSnapshot:
    """Build a graph snapshot for the frontend visualization.

    Pulls nodes/edges from PostgreSQL and falls back to the Neo4j
    neighborhood query if available.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # Goal
    goal = db.get(Goal, goal_id)
    if goal is None:
        return GraphSnapshot(nodes=[], edges=[], scenario_id=scenario_id)
    nodes.append(GraphNode(id=goal.id, type="Goal", label=goal.title, properties={
        "scenario": goal.scenario, "status": goal.status,
        "target_date": str(goal.target_date) if goal.target_date else None,
    }))

    # Pathways
    pathways = list(db.scalars(
        select(Pathway).where(Pathway.goal_id == goal_id)
    ))
    for p in pathways:
        if scenario_id and p.scenario_id and p.scenario_id != scenario_id:
            continue
        nodes.append(GraphNode(id=p.id, type="Pathway", label=p.name, properties={
            "region": p.region, "status": p.status,
        }))
        edges.append(GraphEdge(id=f"{goal.id}->{p.id}", source=goal.id, target=p.id, type="HAS_PATHWAY", weight=1.0))

    # Requirements
    for p in pathways:
        reqs = list(db.scalars(
            select(Requirement).where(Requirement.pathway_id == p.id)
        ))
        for r in reqs:
            nodes.append(GraphNode(id=r.id, type="Requirement", label=r.name, properties={
                "type": r.type, "gap_status": r.gap_status,
            }))
            edges.append(GraphEdge(id=f"{p.id}->{r.id}", source=p.id, target=r.id, type="REQUIRES", weight=r.weight or 1.0))

    # RiskFactors (unfiltered — global risks apply to all goals)
    rfs = list(db.scalars(select(RiskFactor).limit(limit)))
    for rf in rfs:
        nodes.append(GraphNode(id=rf.id, type="RiskFactor", label=rf.name, properties={
            "level": rf.level, "urgency": rf.urgency, "type": rf.type,
        }))

    # Relationships from PG (subject → object)
    rels = list(db.scalars(select(Relationship).limit(limit)))
    for rel in rels:
        edges.append(GraphEdge(
            id=rel.id,
            source=rel.subject_id,
            target=rel.object_id,
            type=rel.type,
            weight=rel.weight,
        ))

    # Events (recent)
    events = list(db.scalars(
        select(Event).order_by(Event.created_at.desc()).limit(limit)
    ))
    for ev in events:
        nodes.append(GraphNode(
            id=ev.id,
            type="Event",
            label=f"{ev.subject} {ev.action}",
            properties={
                "risk_level": ev.risk_flag_level,
                "risk_type": ev.risk_flag_type,
                "occurred_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
            },
        ))

    # Optionally augment with Neo4j neighborhood (best-effort)
    try:
        graph_service = GraphService()
        all_ids = [n.id for n in nodes]
        neighborhood = graph_service.neighborhood(all_ids, limit=limit * 2)
        for row in neighborhood:
            if row.get("source_id") and row.get("target_id"):
                edges.append(GraphEdge(
                    id=f"neo-{row['source_id']}-{row['rel_type']}-{row['target_id']}",
                    source=row["source_id"],
                    target=row["target_id"],
                    type=row["rel_type"],
                    weight=float(row.get("weight") or 0.0),
                ))
    except Exception:  # noqa: BLE001
        pass

    return GraphSnapshot(nodes=nodes, edges=edges, scenario_id=scenario_id)
