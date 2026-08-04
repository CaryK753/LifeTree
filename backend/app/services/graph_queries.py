"""Cypher templates used by the server Neo4j graph adapter."""

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

MERGE_SCENARIO = """
MERGE (sc:Scenario {id: $id})
SET sc.name = $name, sc.status = $status, sc.parent_id = $parent_id
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

__all__ = [
    "LINK_EVENT_TO_RISK",
    "LINK_EXPECTED_EVENT_TO_SCENARIO",
    "MERGE_EVENT",
    "MERGE_GOAL",
    "MERGE_PATHWAY",
    "MERGE_REQUIREMENT",
    "MERGE_RISK_FACTOR",
    "MERGE_SCENARIO",
    "MERGE_SOURCE",
    "NEIGHBORHOOD_QUERY",
    "PROPAGATE_RISK_FROM_EVENT",
]
