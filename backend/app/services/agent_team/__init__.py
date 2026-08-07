"""AgentTeam orchestration service (§D of the cross-validation spec).

Multi-agent collaboration layer: the main agent (Orchestrator) decomposes
an objective into subtasks, dispatches them to specialist sub-agents
(each with an independent context and a pruned toolset), aggregates
results, optionally reviews for gaps and dispatches another round
(≤ 2 iterations), then produces a final output.

Public entry points:
- ``AgentTeamJob`` / ``TeamStatus`` / ``TEAM_TEMPLATES`` — data model.
- ``build_team_graph(db, job, ...)`` — compile the StateGraph for one job.
- ``run_agent_team(db, job_id)`` — synchronous runner used by the Celery task.
"""

from app.models.agent_team import AgentTeamJob, TEAM_TEMPLATES, TeamStatus
from app.services.agent_team.graph import build_team_graph, run_agent_team

__all__ = [
    "TEAM_TEMPLATES",
    "AgentTeamJob",
    "TeamStatus",
    "build_team_graph",
    "run_agent_team",
]
