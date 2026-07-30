"""SSE endpoint for real-time updates: scenario run progress + risk pushes.

Clients subscribe with `GET /api/v1/sse?scenario_id=...`. The server emits
`event: scenario_run`, `event: risk_alert`, etc.

Multi-user isolation: the SSE channel is always keyed by the authenticated
user's id — the ``user_id`` query param is ignored. In single-user mode
``CurrentUser`` falls back to the default user.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import get_db

log = get_logger(__name__)

router = APIRouter(prefix="/sse", tags=["sse"])


@router.get("")
async def sse_stream(
    user: CurrentUser,
    scenario_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream server-sent events for the authenticated user.

    Uses Redis pub/sub channels:
      - `lifetree:risk:{user_id}` — risk alerts
      - `lifetree:scenario:{scenario_id}` — run progress (if scenario_id given)
    """
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    resolved_user_id = user.id
    channels = [f"lifetree:risk:{resolved_user_id}"]
    if scenario_id:
        channels.append(f"lifetree:scenario:{scenario_id}")

    async def event_generator():
        # Send a hello to keep the connection open
        hello = {
            "event": "hello",
            "data": {
                "user_id": resolved_user_id,
                "scenario_id": scenario_id,
                "server_time": datetime.now(timezone.utc).isoformat(),
            },
        }
        yield f"event: hello\ndata: {json.dumps(hello['data'])}\n\n"

        pubsub = redis.pubsub()
        for ch in channels:
            await pubsub.subscribe(ch)

        try:
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=15.0
                )
                if msg is None:
                    # Heartbeat
                    yield f": ping {datetime.now(timezone.utc).isoformat()}\n\n"
                    continue
                if msg.get("type") == "message":
                    channel = msg["channel"]
                    event_name = (
                        "scenario_run"
                        if channel.startswith("lifetree:scenario")
                        else "risk_alert"
                    )
                    yield f"event: {event_name}\ndata: {msg['data']}\n\n"
        except asyncio.CancelledError:
            log.info("sse.client_disconnected", user_id=resolved_user_id)
        finally:
            for ch in channels:
                await pubsub.unsubscribe(ch)
            await pubsub.aclose()
            await redis.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
