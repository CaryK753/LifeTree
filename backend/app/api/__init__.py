"""API router aggregation: registers every sub-router under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.chat import router as chat_router
from app.api.crawler import router as crawler_router
from app.api.dashboard import router as dashboard_router
from app.api.events import router as events_router
from app.api.goals import router as goals_router
from app.api.graph import router as graph_router
from app.api.ingest import router as ingest_router
from app.api.lifecycle import router as lifecycle_router
from app.api.memories import router as memories_router
from app.api.notifications import router as notifications_router
from app.api.plugins import router as plugins_router
from app.api.risk_factors import router as risk_factors_router
from app.api.scenarios import router as scenarios_router
from app.api.settings import router as settings_router
from app.api.sse import router as sse_router
from app.api.system import router as system_router
from app.api.users import router as users_router

api_router = APIRouter()

api_router.include_router(users_router)
api_router.include_router(goals_router)
api_router.include_router(risk_factors_router)
api_router.include_router(events_router)
api_router.include_router(scenarios_router)
api_router.include_router(ingest_router)
api_router.include_router(graph_router)
api_router.include_router(notifications_router)
api_router.include_router(dashboard_router)
api_router.include_router(chat_router)
api_router.include_router(crawler_router)
api_router.include_router(sse_router)
api_router.include_router(settings_router)
api_router.include_router(plugins_router)
api_router.include_router(memories_router)
api_router.include_router(system_router)
api_router.include_router(lifecycle_router)


@api_router.get("/_meta", tags=["meta"])
async def meta() -> dict[str, str]:
    return {"name": "LifeTree API", "phase": "MVP"}
