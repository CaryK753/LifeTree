"""Neo4j graph service: ontology write + risk-propagation read.

Per project plan §4.2: Goal / Pathway / Requirement / RiskFactor / Event
nodes with REQUIRES / AFFECTS / BRANCHES_FROM / SUPERSEDES relationships.

The PG-side models remain the source of truth; Neo4j is used for path
queries and risk-propagation traversals.
"""

from __future__ import annotations

from typing import Any

from neo4j import Driver

from app.core.logging import get_logger
from app.db.neo4j import get_neo4j_driver
from app.models.event import Event, InformationSource
from app.models.goal import Goal, Pathway, Requirement, RiskFactor
from app.models.scenario import Scenario
from app.models.user import UserProfile

log = get_logger(__name__)


# ---------- Cypher templates ----------

MERGE_GOAL = """
MERGE (g:Goal {id: $id})
SET g.title = $title, g.scenario = $scenario, g.status = $status,
    g.target_date = $target_date, g.updated_at = timestamp()
"""

MERGE_PATHWAY = """
MERGE (p:Pathway {id: $id})
SET p.name = $name, p.region = $region, p.status = $status
WITH p
MATCH (g:Goal {id: $goal_id})
MERGE (g)-[:HAS_PATHWAY]->(p)
"""

MERGE_REQUIREMENT = """
MERGE (r:Requirement {id: $id})
SET r.name = $name, r.type = $type, r.gap_status = $gap_status
WITH r
MATCH (p:Pathway {id: $pathway_id})
MERGE (p)-[:REQUIRES]->(r)
"""

MERGE_RISK_FACTOR = """
MERGE (rf:RiskFactor {id: $id})
SET rf.name = $name, rf.type = $type, rf.level = $level, rf.urgency = $urgency
"""

MERGE_EVENT = """
MERGE (e:Event {id: $id})
SET e.subject = $subject, e.action = $action, e.object = $object,
    e.risk_level = $risk_level, e.risk_type = $risk_type, e.risk_urgency = $urgency,
    e.occurred_at = $occurred_at
WITH e
OPTIONAL MATCH (s:InformationSource {id: $source_id})
FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END |
  MERGE (s)-[:EMITTED]->(e)
)
"""

MERGE_SOURCE = """
MERGE (s:InformationSource {id: $id})
SET s.kind = $kind, s.title = $title, s.credibility = $credibility
"""

LINK_EVENT_TO_RISK = """
MATCH (e:Event {id: $event_id}), (rf:RiskFactor {id: $risk_id})
MERGE (e)-[rel:AFFECTS]->(rf)
SET rel.weight = $weight, rel.confidence = $confidence,
    rel.updated_at = timestamp()
"""

LINK_RISK_TO_PATHWAY = """
MATCH (rf:RiskFactor {id: $risk_id}), (p:Pathway {id: $pathway_id})
MERGE (rf)-[:AFFECTS]->(p)
"""

MERGE_SCENARIO = """
MERGE (sc:Scenario {id: $id})
SET sc.name = $name, sc.status = $status, sc.parent_id = $parent_id
"""

LINK_PATHWAY_TO_SCENARIO = """
MATCH (p:Pathway {id: $pathway_id}), (sc:Scenario {id: $scenario_id})
MERGE (p)-[:BELONGS_TO]->(sc)
"""

LINK_EXPECTED_EVENT_TO_SCENARIO = """
MATCH (e:Event {id: $event_id}), (sc:Scenario {id: $scenario_id})
MERGE (e)-[:EXPECTED_IN]->(sc)
"""

PROPAGATE_RISK_FROM_EVENT = """
MATCH path=(e:Event {id: $event_id})-[:AFFECTS]->(rf:RiskFactor)-[:AFFECTS*0..4]->(p:Pathway)<-[:HAS_PATHWAY]-(g:Goal)
RETURN DISTINCT g.id AS goal_id, g.title AS goal_title,
       p.id AS pathway_id, p.name AS pathway_name,
       rf.id AS risk_id, rf.name AS risk_name, rf.level AS level,
       [rel IN relationships(path) | coalesce(rel.weight, 0.0)] AS path_weights,
       [rel IN relationships(path) | coalesce(rel.confidence, 0.5)] AS path_confidences
ORDER BY g.id, rf.level DESC
"""

NEIGHBORHOOD_QUERY = """
MATCH (n)-[r]-(m)
WHERE n.id IN $ids
RETURN n.id AS source_id, labels(n)[0] AS source_type,
       type(r) AS rel_type, r.weight AS weight,
       m.id AS target_id, labels(m)[0] AS target_type,
       coalesce(m.title, m.name, m.subject) AS label
LIMIT $limit
"""


class GraphService:
    """Wraps the Neo4j driver for write-side ontology mutations + reads."""

    def __init__(self, driver: Driver | None = None) -> None:
        self._driver = driver

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = get_neo4j_driver()
        return self._driver

    # ---------------- Writes ----------------

    def _run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        with self.driver.session() as session:
            result = session.run(cypher, **params)
            return [r.data() for r in result]

    def upsert_goal(self, goal: Goal) -> None:
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
                occurred_at=(
                    event.occurred_at.isoformat() if event.occurred_at else ""
                ),
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

    def link_expected_event_to_scenario(
        self, event_id: str, scenario_id: str
    ) -> None:
        try:
            self._run(
                LINK_EXPECTED_EVENT_TO_SCENARIO,
                event_id=event_id,
                scenario_id=scenario_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.link_expected_event_failed", error=str(exc))

    def upsert_scenario(self, scenario: Scenario) -> None:
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
        try:
            return self._run(PROPAGATE_RISK_FROM_EVENT, event_id=event_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.propagate_risk_failed", error=str(exc))
            return []

    def neighborhood(
        self, node_ids: list[str], limit: int = 200
    ) -> list[dict[str, Any]]:
        """Return the immediate neighborhood around the given node IDs."""
        if not node_ids:
            return []
        try:
            return self._run(NEIGHBORHOOD_QUERY, ids=node_ids, limit=limit)
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.neighborhood_failed", error=str(exc))
            return []

    def health(self) -> bool:
        try:
            self.driver.verify_connectivity()
            return True
        except Exception:  # noqa: BLE001
            return False
