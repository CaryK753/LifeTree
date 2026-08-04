"""Neo4j graph service: ontology write + risk-propagation read.

Per project plan §4.2: Goal / Pathway / Requirement / RiskFactor / Event
nodes with REQUIRES / AFFECTS / BRANCHES_FROM / SUPERSEDES relationships.

The PG-side models remain the source of truth; Neo4j is used for path
queries and risk-propagation traversals.
"""

from __future__ import annotations

from typing import Any

from neo4j import Driver

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.neo4j import get_neo4j_driver
from app.models.event import Event, InformationSource
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.models.scenario import Scenario
from app.services.graph_queries import (
    LINK_EVENT_TO_RISK,
    LINK_EXPECTED_EVENT_TO_SCENARIO,
    MERGE_EVENT,
    MERGE_GOAL,
    MERGE_PATHWAY,
    MERGE_REQUIREMENT,
    MERGE_RISK_FACTOR,
    MERGE_SCENARIO,
    MERGE_SOURCE,
    NEIGHBORHOOD_QUERY,
    PROPAGATE_RISK_FROM_EVENT,
)
from app.services.runtime.graph_store import EmbeddedGraphStore

log = get_logger(__name__)


class GraphService:
    """Wraps the Neo4j driver for write-side ontology mutations + reads."""

    def __init__(self, driver: Driver | None = None) -> None:
        self._driver = driver
        self._embedded_store: EmbeddedGraphStore | None = None

    @property
    def embedded_store(self) -> EmbeddedGraphStore:
        if self._embedded_store is None:
            self._embedded_store = EmbeddedGraphStore()
        return self._embedded_store

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = get_neo4j_driver()
        return self._driver

    # ---------------- Writes ----------------

    def _run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        if get_settings().lifetree_storage_mode == "local":
            return []
        with self.driver.session() as session:
            result = session.run(cypher, **params)
            return [r.data() for r in result]

    def upsert_goal(self, goal: Goal) -> None:
        if get_settings().lifetree_storage_mode == "local":
            self.embedded_store.mirror_goal(goal)
            return
        try:
            self._run(
                MERGE_GOAL,
                id=goal.id,
                title=goal.title,
                scenario=goal.scenario,
                status=goal.status,
                target_date=str(goal.target_date) if goal.target_date else None,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.upsert_goal_failed", error=str(exc))

    def upsert_pathway(self, pathway: Pathway) -> None:
        if get_settings().lifetree_storage_mode == "local":
            self.embedded_store.mirror_pathway(pathway)
            return
        try:
            self._run(
                MERGE_PATHWAY,
                id=pathway.id,
                name=pathway.name,
                region=pathway.region or "",
                status=pathway.status,
                goal_id=pathway.goal_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.upsert_pathway_failed", error=str(exc))

    def upsert_requirement(self, req: Requirement) -> None:
        if get_settings().lifetree_storage_mode == "local":
            self.embedded_store.mirror_requirement(req)
            return
        try:
            self._run(
                MERGE_REQUIREMENT,
                id=req.id,
                name=req.name,
                type=req.type,
                gap_status=req.gap_status,
                pathway_id=req.pathway_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.upsert_requirement_failed", error=str(exc))

    def upsert_risk_factor(self, rf: RiskFactor) -> None:
        if get_settings().lifetree_storage_mode == "local":
            self.embedded_store.mirror_risk_factor(rf)
            return
        try:
            self._run(
                MERGE_RISK_FACTOR,
                id=rf.id,
                name=rf.name,
                type=rf.type,
                level=rf.level,
                urgency=rf.urgency,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.upsert_risk_factor_failed", error=str(exc))

    def upsert_source(self, source: InformationSource) -> None:
        if get_settings().lifetree_storage_mode == "local":
            self.embedded_store.mirror_source(source)
            return
        try:
            self._run(
                MERGE_SOURCE,
                id=source.id,
                kind=source.kind,
                title=source.title,
                credibility=source.credibility,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.upsert_source_failed", error=str(exc))

    def upsert_event(self, event: Event, source: InformationSource | None) -> None:
        if get_settings().lifetree_storage_mode == "local":
            self.embedded_store.mirror_event(event, source)
            return
        try:
            if source is not None:
                self.upsert_source(source)
            self._run(
                MERGE_EVENT,
                id=event.id,
                subject=event.subject,
                action=event.action,
                object=event.object or "",
                risk_level=event.risk_flag_level or "",
                risk_type=event.risk_flag_type or "",
                urgency=event.risk_flag_urgency or "",
                occurred_at=(event.occurred_at.isoformat() if event.occurred_at else ""),
                source_id=event.source_id or "",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.upsert_event_failed", error=str(exc))

    def link_event_to_risk(
        self,
        event_id: str,
        risk_id: str,
        weight: float = 0.0,
        confidence: float = 0.5,
    ) -> None:
        if get_settings().lifetree_storage_mode == "local":
            self.embedded_store.link_event_to_risk(event_id, risk_id, weight, confidence)
            return
        try:
            self._run(
                LINK_EVENT_TO_RISK,
                event_id=event_id,
                risk_id=risk_id,
                weight=weight,
                confidence=confidence,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.link_event_risk_failed", error=str(exc))

    def link_expected_event_to_scenario(self, event_id: str, scenario_id: str) -> None:
        if get_settings().lifetree_storage_mode == "local":
            self.embedded_store.link_expected_event(event_id, scenario_id)
            return
        try:
            self._run(
                LINK_EXPECTED_EVENT_TO_SCENARIO,
                event_id=event_id,
                scenario_id=scenario_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.link_expected_event_failed", error=str(exc))

    def upsert_scenario(self, scenario: Scenario) -> None:
        if get_settings().lifetree_storage_mode == "local":
            self.embedded_store.mirror_scenario(scenario)
            return
        try:
            self._run(
                MERGE_SCENARIO,
                id=scenario.id,
                name=scenario.name,
                status=scenario.status,
                parent_id=scenario.parent_scenario_id or "",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.upsert_scenario_failed", error=str(exc))

    # ---------------- Reads ----------------

    def propagate_risk(self, event_id: str) -> list[dict[str, Any]]:
        """Traverse the graph from an event and return impacted goals/pathways."""
        if get_settings().lifetree_storage_mode == "local":
            return self.embedded_store.propagate_risk(event_id)
        try:
            return self._run(PROPAGATE_RISK_FROM_EVENT, event_id=event_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.propagate_risk_failed", error=str(exc))
            return []

    def neighborhood(self, node_ids: list[str], limit: int = 200) -> list[dict[str, Any]]:
        """Return the immediate neighborhood around the given node IDs."""
        if not node_ids:
            return []
        if get_settings().lifetree_storage_mode == "local":
            return self.embedded_store.neighborhood(node_ids, limit)
        try:
            return self._run(NEIGHBORHOOD_QUERY, ids=node_ids, limit=limit)
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.neighborhood_failed", error=str(exc))
            return []

    def health(self) -> bool:
        if get_settings().lifetree_storage_mode == "local":
            return True
        try:
            self.driver.verify_connectivity()
            return True
        except Exception:  # noqa: BLE001
            return False
