"""Knowledge graph snapshot endpoint for the frontend graph view."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.event import Event, InformationSource, Relationship
from app.models.goal import (
    Goal,
    Pathway,
    Requirement,
    RiskFactor,
    pathway_requirements,
    pathway_risk_factors,
)
from app.schemas.api import GraphEdge, GraphNode, GraphSnapshot
from app.services.graph import GraphService
from app.services.risk_scope import risk_scope_clause

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/{goal_id}", response_model=GraphSnapshot)
def get_graph(
    goal_id: str,
    user: CurrentUser,
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

    # Goal — verify ownership before returning any data.
    goal = db.get(Goal, goal_id)
    if goal is None:
        return GraphSnapshot(nodes=[], edges=[], scenario_id=scenario_id)
    if goal.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this goal")
    nodes.append(
        GraphNode(
            id=goal.id,
            type="Goal",
            label=goal.title,
            properties={
                "scenario": goal.scenario,
                "status": goal.status,
                "target_date": str(goal.target_date) if goal.target_date else None,
            },
        )
    )

    # Pathways
    pathway_stmt = select(Pathway).where(Pathway.goal_id == goal_id)
    if scenario_id:
        pathway_stmt = pathway_stmt.where(Pathway.scenario_id == scenario_id)
    pathways = list(db.scalars(pathway_stmt.limit(limit)))
    pathway_ids = [p.id for p in pathways]
    for p in pathways:
        nodes.append(
            GraphNode(
                id=p.id,
                type="Pathway",
                label=p.name,
                properties={
                    "region": p.region,
                    "status": p.status,
                },
            )
        )
        edges.append(
            GraphEdge(
                id=f"{goal.id}->{p.id}",
                source=goal.id,
                target=p.id,
                type="HAS_PATHWAY",
                weight=1.0,
            )
        )

    # Requirements via M2M, with a legacy pathway_id fallback.
    requirement_links: dict[str, set[str]] = {pid: set() for pid in pathway_ids}
    requirements: dict[str, Requirement] = {}
    if pathway_ids:
        rows = db.execute(
            select(pathway_requirements.c.pathway_id, Requirement)
            .join(
                Requirement,
                Requirement.id == pathway_requirements.c.requirement_id,
            )
            .where(pathway_requirements.c.pathway_id.in_(pathway_ids))
            .limit(limit)
        ).all()
        for pathway_id, requirement in rows:
            requirement_links[pathway_id].add(requirement.id)
            requirements[requirement.id] = requirement
        missing_ids = [pid for pid, ids in requirement_links.items() if not ids]
        if missing_ids:
            for requirement in db.scalars(
                select(Requirement).where(Requirement.pathway_id.in_(missing_ids)).limit(limit)
            ):
                requirement_links[requirement.pathway_id].add(requirement.id)
                requirements[requirement.id] = requirement
    for requirement in requirements.values():
        nodes.append(
            GraphNode(
                id=requirement.id,
                type="Requirement",
                label=requirement.name,
                properties={"type": requirement.type, "gap_status": requirement.gap_status},
            )
        )
    for pathway_id, requirement_ids in requirement_links.items():
        for requirement_id in requirement_ids:
            requirement = requirements[requirement_id]
            edges.append(
                GraphEdge(
                    id=f"{pathway_id}->{requirement_id}",
                    source=pathway_id,
                    target=requirement_id,
                    type="REQUIRES",
                    weight=requirement.weight or 1.0,
                )
            )

    # Only risk factors linked to this goal's visible pathways are relevant.
    risk_links: dict[str, set[str]] = {pid: set() for pid in pathway_ids}
    risks: dict[str, RiskFactor] = {}
    if pathway_ids:
        rows = db.execute(
            select(pathway_risk_factors.c.pathway_id, RiskFactor)
            .join(
                RiskFactor,
                RiskFactor.id == pathway_risk_factors.c.risk_factor_id,
            )
            .where(
                pathway_risk_factors.c.pathway_id.in_(pathway_ids),
                RiskFactor.deleted_at.is_(None),
                risk_scope_clause(goal.user_id),
            )
            .limit(limit)
        ).all()
        for pathway_id, risk in rows:
            risk_links[pathway_id].add(risk.id)
            risks[risk.id] = risk
    for risk in risks.values():
        nodes.append(
            GraphNode(
                id=risk.id,
                type="RiskFactor",
                label=risk.name,
                properties={
                    "level": risk.level,
                    "urgency": risk.urgency,
                    "type": risk.type,
                },
            )
        )
    for pathway_id, risk_ids in risk_links.items():
        for risk_id in risk_ids:
            edges.append(
                GraphEdge(
                    id=f"{pathway_id}->{risk_id}",
                    source=pathway_id,
                    target=risk_id,
                    type="HAS_RISK",
                    weight=1.0,
                )
            )

    # Events (recent)
    events = list(
        db.scalars(
            select(Event)
            .where(or_(Event.user_id == goal.user_id, Event.user_id.is_(None)))
            .order_by(Event.created_at.desc())
            .limit(limit)
        )
    )
    for ev in events:
        nodes.append(
            GraphNode(
                id=ev.id,
                type="Event",
                label=f"{ev.subject} {ev.action}",
                properties={
                    "risk_level": ev.risk_flag_level,
                    "risk_type": ev.risk_flag_type,
                    "occurred_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
                },
            )
        )

    # Sources complete the evidence chain: source -> extracted event ->
    # requirement/risk/pathway relationships. Keep ownership scoped even
    # for admin users because the selected goal defines the tenant context.
    event_ids_by_source: dict[str, list[str]] = {}
    for event in events:
        if event.source_id:
            event_ids_by_source.setdefault(event.source_id, []).append(event.id)
    if event_ids_by_source:
        sources = list(
            db.scalars(
                select(InformationSource).where(
                    InformationSource.id.in_(event_ids_by_source),
                    or_(
                        InformationSource.user_id == goal.user_id,
                        InformationSource.user_id.is_(None),
                    ),
                )
            )
        )
        for source in sources:
            nodes.append(
                GraphNode(
                    id=source.id,
                    type="InformationSource",
                    label=source.title,
                    properties={
                        "kind": source.kind,
                        "publisher": source.publisher,
                        "url": source.url,
                        "credibility": source.credibility,
                        "credibility_score": source.credibility_score,
                    },
                )
            )
            for event_id in event_ids_by_source[source.id]:
                edges.append(
                    GraphEdge(
                        id=f"{source.id}->source-of->{event_id}",
                        source=source.id,
                        target=event_id,
                        type="SOURCE_OF",
                        weight=source.credibility_score,
                    )
                )

    # Relationships are returned only when both endpoints are visible.
    node_ids = {node.id for node in nodes}
    if node_ids:
        rels = list(
            db.scalars(
                select(Relationship)
                .where(
                    Relationship.subject_id.in_(node_ids),
                    Relationship.object_id.in_(node_ids),
                )
                .limit(limit)
            )
        )
        for rel in rels:
            edges.append(
                GraphEdge(
                    id=rel.id,
                    source=rel.subject_id,
                    target=rel.object_id,
                    type=rel.type,
                    weight=rel.weight,
                )
            )

    # Optionally augment with Neo4j neighborhood (best-effort)
    try:
        graph_service = GraphService()
        all_ids = [n.id for n in nodes]
        neighborhood = graph_service.neighborhood(all_ids, limit=limit * 2)
        for row in neighborhood:
            if row.get("source_id") and row.get("target_id"):
                if row["source_id"] not in node_ids or row["target_id"] not in node_ids:
                    continue
                edges.append(
                    GraphEdge(
                        id=f"neo-{row['source_id']}-{row['rel_type']}-{row['target_id']}",
                        source=row["source_id"],
                        target=row["target_id"],
                        type=row["rel_type"],
                        weight=float(row.get("weight") or 0.0),
                    )
                )
    except Exception:  # noqa: BLE001
        pass

    return GraphSnapshot(nodes=nodes, edges=edges, scenario_id=scenario_id)
