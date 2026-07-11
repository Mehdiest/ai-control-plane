"""Async Redis client management for the rate-limiting counter store."""

import logging

import redis.asyncio as redis

from app.core.config import get_settings

logger = logging.getLogger("control_plane.redis")

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Return the shared Redis client, creating it on first call."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.from_url(settings.redis_url, decode_responses=True)
        logger.info("Redis client initialised (url=%s).", settings.redis_url)
    return _client


def set_redis_client(client: redis.Redis) -> None:
    """Override the Redis client — used by tests to inject a FakeRedis."""
    global _client
    _client = client


async def close_redis() -> None:
    """Close the Redis connection pool on application shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None