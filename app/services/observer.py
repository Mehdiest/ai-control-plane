"""Query logic for the observability dashboard, isolated from the API layer."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import Policy
from app.models.request_log import RequestLog
from app.models.service import Service, ServiceStatus
from app.schemas.observe import (
    ErrorStats,
    LatencyStats,
    ObserveSummary,
    TrafficEntry,
)

logger = logging.getLogger("control_plane.observer")


async def get_summary(db: AsyncSession) -> ObserveSummary:
    """Return a snapshot of services, policies, and recent request volume."""
    services = await db.execute(select(Service))
    svc_list = list(services.scalars().all())

    def count_by(status: ServiceStatus) -> int:
        return sum(1 for s in svc_list if s.status == status)

    policy_count = await db.scalar(
        select(func.count()).select_from(Policy).where(Policy.is_active.is_(True))
    )

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_requests = await db.scalar(
        select(func.count()).select_from(RequestLog).where(RequestLog.created_at >= since)
    )

    return ObserveSummary(
        total_services=len(svc_list),
        healthy=count_by(ServiceStatus.HEALTHY),
        degraded=count_by(ServiceStatus.DEGRADED),
        unhealthy=count_by(ServiceStatus.UNHEALTHY),
        unknown=count_by(ServiceStatus.UNKNOWN),
        active_policies=policy_count or 0,
        requests_last_hour=recent_requests or 0,
    )


async def get_traffic(db: AsyncSession, hours: int = 1) -> list[TrafficEntry]:
    """Return traffic distribution by resolution code within the time window.

    Phase 5 — includes the policy name and weight for each group so
    operators can verify the canary split from the traffic dashboard.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await db.execute(
        select(
            RequestLog.resolved_service,
            RequestLog.resolution,
            RequestLog.policy_name,
            RequestLog.policy_weight,
            func.count().label("count"),
        )
        .where(RequestLog.created_at >= since)
        .group_by(
            RequestLog.resolved_service,
            RequestLog.resolution,
            RequestLog.policy_name,
            RequestLog.policy_weight,
        )
        .order_by(func.count().desc())
    )
    rows = result.all()
    return [
        TrafficEntry(
            resolved_service=row.resolved_service,
            resolution=row.resolution,
            count=row.count,
            policy_name=row.policy_name,
            policy_weight=row.policy_weight,
        )
        for row in rows
    ]


async def get_errors(db: AsyncSession, hours: int = 1) -> list[ErrorStats]:
    """Return error counts per service and resolution code."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    error_resolutions = ("no_policy", "no_healthy_service")
    result = await db.execute(
        select(
            RequestLog.resolved_service,
            RequestLog.resolution,
            func.count().label("count"),
        )
        .where(RequestLog.created_at >= since)
        .where(RequestLog.resolution.in_(error_resolutions))
        .group_by(RequestLog.resolved_service, RequestLog.resolution)
        .order_by(func.count().desc())
    )
    rows = result.all()
    return [
        ErrorStats(
            resolved_service=row.resolved_service,
            resolution=row.resolution,
            count=row.count,
        )
        for row in rows
    ]


async def get_latency(db: AsyncSession, hours: int = 1) -> list[LatencyStats]:
    """Return average latency per service within the time window."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await db.execute(
        select(
            RequestLog.resolved_service,
            func.avg(RequestLog.latency_ms).label("avg_latency"),
            func.count().label("count"),
        )
        .where(RequestLog.created_at >= since)
        .where(RequestLog.latency_ms.is_not(None))
        .group_by(RequestLog.resolved_service)
        .order_by(func.avg(RequestLog.latency_ms).asc())
    )
    rows = result.all()
    return [
        LatencyStats(
            resolved_service=row.resolved_service,
            avg_latency_ms=round(row.avg_latency, 2) if row.avg_latency else 0.0,
            sample_count=row.count,
        )
        for row in rows
    ]