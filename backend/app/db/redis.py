"""Redis client singleton (for Celery broker, cache, pub/sub)."""

from __future__ import annotations

from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    """Return a singleton Redis client."""
    s = get_settings()
    return Redis.from_url(s.redis_url, decode_responses=True)


def close_redis() -> None:
    if get_redis.cache_info().currsize > 0:
        get_redis().close()
        get_redis.cache_clear()
