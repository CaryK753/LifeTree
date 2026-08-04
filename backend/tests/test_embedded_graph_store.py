from __future__ import annotations

from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.postgres import Base
from app.models.event import Event, InformationSource, Relationship
from app.models.goal import Goal, Pathway, RiskFactor, pathway_risk_factors
from app.models.local_graph import LocalGraphBase, LocalGraphEdge, LocalGraphNode
from app.models.user import UserProfile
from app.services.runtime import graph_projection, graph_store
from app.services.runtime.graph_store import EmbeddedGraphStore


def _session_factory(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    LocalGraphBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(graph_store, "SessionLocal", factory)
    monkeypatch.setattr(graph_projection, "SessionLocal", factory)
    return factory


def _seed_relational_graph(factory):
    with factory.begin() as db:
        user = UserProfile(display_name="Graph User", email="graph@example.com")
        db.add(user)
        db.flush()
        goal = Goal(user_id=user.id, title="Graph Goal", scenario="generic")
        db.add(goal)
        db.flush()
        pathway = Pathway(goal_id=goal.id, name="Graph Pathway")
        risk = RiskFactor(
            user_id=user.id,
            name="Graph Risk",
            type="policy",
            level="high",
            impact=0.8,
        )
        source = InformationSource(user_id=user.id, title="Graph Source")
        db.add_all([pathway, risk, source])
        db.flush()
        event = Event(
            user_id=user.id,
            source_id=source.id,
            subject="Policy",
            action="changed",
            risk_flag_level="high",
        )
        db.add(event)
        db.flush()
        db.execute(
            insert(pathway_risk_factors).values(
                pathway_id=pathway.id,
                risk_factor_id=risk.id,
            )
        )
        db.add(
            Relationship(
                source_id=source.id,
                subject_type="Event",
                subject_id=event.id,
                object_type="RiskFactor",
                object_id=risk.id,
                type="AFFECTS",
                weight=0.7,
                confidence=0.9,
            )
        )
    return goal, pathway, risk, source, event


def test_embedded_graph_incremental_neighborhood_and_propagation(monkeypatch) -> None:
    factory = _session_factory(monkeypatch)
    goal, pathway, risk, source, event = _seed_relational_graph(factory)
    store = EmbeddedGraphStore()

    store.mirror_goal(goal)
    store.mirror_pathway(pathway)
    store.mirror_risk_factor(risk)
    store.mirror_source(source)
    store.mirror_event(event, source)
    store.link_event_to_risk(event.id, risk.id, 0.7, 0.9)

    neighborhood = store.neighborhood([goal.id], limit=20)
    impacted = store.propagate_risk(event.id)
    assert any(row["rel_type"] == "HAS_PATHWAY" for row in neighborhood)
    assert impacted[0]["goal_id"] == goal.id
    assert impacted[0]["pathway_id"] == pathway.id
    assert impacted[0]["risk_id"] == risk.id
    assert impacted[0]["level"] == "high"


def test_embedded_graph_rebuilds_from_relational_facts(monkeypatch) -> None:
    factory = _session_factory(monkeypatch)
    goal, pathway, risk, _source, event = _seed_relational_graph(factory)

    EmbeddedGraphStore().rebuild()

    with factory() as db:
        node_types = {
            node.node_id: node.node_type for node in db.scalars(select(LocalGraphNode))
        }
        relations = {edge.relation for edge in db.scalars(select(LocalGraphEdge))}
    assert node_types[goal.id] == "Goal"
    assert node_types[pathway.id] == "Pathway"
    assert node_types[risk.id] == "RiskFactor"
    assert node_types[event.id] == "Event"
    assert {"HAS_PATHWAY", "AFFECTS", "EMITTED"} <= relations


def test_embedded_graph_rebuild_is_idempotent(monkeypatch) -> None:
    factory = _session_factory(monkeypatch)
    _seed_relational_graph(factory)
    store = EmbeddedGraphStore()

    store.rebuild()
    store.rebuild()

    with factory() as db:
        node_count = len(list(db.scalars(select(LocalGraphNode))))
        edge_count = len(list(db.scalars(select(LocalGraphEdge))))
    assert node_count == 5
    assert edge_count == 4
