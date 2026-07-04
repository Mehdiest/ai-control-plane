"""
Background health-checking engine.

Runs on a scheduled interval (via APScheduler) and pings every
registered service's health endpoint, updating status the same way a
router marks a BGP neighbor up/down based on consecutive keepalive
failures. This module contains no FastAPI-specific code so it can be
tested or reused outside the web layer.
"""

import logging
import time

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.service import Service, ServiceStatus

logger = logging.getLogger("control_plane.health_checker")

settings = get_settings()


async def _check_single_service(client: httpx.AsyncClient, service: Service) -> None:
    """Probe one service's health endpoint and persist the resulting status."""
    url = service.base_url.rstrip("/") + service.health_check_path
    start = time.perf_counter()

    async with AsyncSessionLocal() as session:
        # Re-fetch inside this session to avoid detached-instance issues.
        db_service = await session.get(Service, service.id)
        if db_service is None:
            return  # service was deleted between scheduling and execution

        try:
            response = await client.get(url, timeout=settings.health_check_timeout_seconds)
            latency_ms = (time.perf_counter() - start) * 1000

            if response.is_success:
                db_service.status = ServiceStatus.HEALTHY
                db_service.consecutive_failures = 0
                db_service.last_error = None
            else:
                _record_failure(db_service, f"HTTP {response.status_code}")

            db_service.last_latency_ms = round(latency_ms, 2)

        except httpx.RequestError as exc:
            _record_failure(db_service, str(exc))

        db_service.last_checked_at = _utc_now()
        await session.commit()


def _record_failure(db_service: Service, error_message: str) -> None:
    """Increment the failure counter and demote status once the threshold is crossed."""
    db_service.consecutive_failures += 1
    db_service.last_error = error_message[:1000]

    if db_service.consecutive_failures >= settings.unhealthy_after_failures:
        db_service.status = ServiceStatus.UNHEALTHY
    else:
        db_service.status = ServiceStatus.DEGRADED


def _utc_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


async def run_health_check_cycle() -> None:
    """Fetch all registered services and check them concurrently in one pass."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Service))
        services = result.scalars().all()

    if not services:
        return

    async with httpx.AsyncClient() as client:
        import asyncio

        await asyncio.gather(*(_check_single_service(client, s) for s in services))

    logger.info("Health check cycle completed for %d service(s).", len(services))


def create_scheduler() -> AsyncIOScheduler:
    """Build (but do not start) the APScheduler instance for the app lifespan."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_health_check_cycle,
        trigger="interval",
        seconds=settings.health_check_interval_seconds,
        id="health_check_cycle",
        max_instances=1,  # never overlap a slow cycle with the next tick
        coalesce=True,
    )
    return scheduler
