"""Redis-backed fixed-window rate limiter for per-tenant request quotas."""

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.quota import Quota
from app.schemas.quota import QuotaStatus

logger = logging.getLogger("control_plane.rate_limiter")


class RateLimitResult:
    """Outcome of a rate-limit check."""

    def __init__(self, allowed: bool, quota: Quota | None, count: int = 0):
        self.allowed = allowed
        self.quota = quota
        self.count = count


async def check_rate_limit(
    tenant_id: str,
    db: AsyncSession,
) -> RateLimitResult:
    """Check and increment the tenant's request counter.

    Returns a RateLimitResult indicating whether the request is allowed.
    """
    quota = await _fetch_quota(tenant_id, db)

    if quota is None or not quota.is_active:
        return RateLimitResult(allowed=True, quota=quota)

    redis = get_redis()
    key, window_start = _build_key(tenant_id, quota.window_seconds)

    count = await redis.incr(key)

    if count == 1:
        await redis.expire(key, quota.window_seconds)
        logger.debug("New rate-limit window for tenant '%s' (key=%s).", tenant_id, key)

    if count > quota.max_requests:
        logger.warning(
            "Tenant '%s' exceeded quota (%d/%d in %ds window).",
            tenant_id, count, quota.max_requests, quota.window_seconds,
        )
        return RateLimitResult(allowed=False, quota=quota, count=count)

    return RateLimitResult(allowed=True, quota=quota, count=count)


async def get_quota_status(tenant_id: str, db: AsyncSession) -> QuotaStatus | None:
    """Return the tenant's quota with live consumption from Redis."""
    quota = await _fetch_quota(tenant_id, db)
    if quota is None:
        return None

    redis = get_redis()
    key, _ = _build_key(tenant_id, quota.window_seconds)

    count_str = await redis.get(key)
    count = int(count_str) if count_str else 0
    ttl = await redis.ttl(key)
    reset_seconds = ttl if ttl > 0 else None

    return QuotaStatus(
        tenant_id=tenant_id,
        max_requests=quota.max_requests,
        window_seconds=quota.window_seconds,
        is_active=quota.is_active,
        current_count=count,
        remaining=max(0, quota.max_requests - count),
        window_reset_seconds=reset_seconds,
    )


async def reset_tenant_counter(tenant_id: str, db: AsyncSession) -> bool:
    """Delete the Redis counter for a tenant. Returns True if a quota exists."""
    quota = await _fetch_quota(tenant_id, db)
    if quota is None:
        return False

    redis = get_redis()
    key, _ = _build_key(tenant_id, quota.window_seconds)
    await redis.delete(key)
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_quota(tenant_id: str, db: AsyncSession) -> Quota | None:
    """Look up the active-or-inactive quota row for a tenant."""
    return await db.scalar(select(Quota).where(Quota.tenant_id == tenant_id))


def _build_key(tenant_id: str, window_seconds: int) -> tuple[str, int]:
    """Build the Redis key and its window-start epoch for the current window."""
    now = int(time.time())
    window_start = now - (now % window_seconds)
    key = f"quota:{tenant_id}:{window_start}"
    return key, window_start