"""Observability dashboard endpoints — read-only analytics over request logs."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.observe import (
    ErrorStats,
    LatencyStats,
    ObserveSummary,
    TrafficEntry,
)
from app.services.observer import (
    get_errors,
    get_latency,
    get_summary,
    get_traffic,
)

router = APIRouter(prefix="/observe", tags=["observability"])


@router.get("/summary", response_model=ObserveSummary)
async def observe_summary(db: AsyncSession = Depends(get_db)) -> ObserveSummary:
    """High-level snapshot: service counts, active policies, recent request volume."""
    return await get_summary(db)


@router.get("/traffic", response_model=list[TrafficEntry])
async def observe_traffic(
    hours: int = Query(default=1, ge=1, le=168, description="Time window in hours."),
    db: AsyncSession = Depends(get_db),
) -> list[TrafficEntry]:
    """Traffic distribution grouped by resolved service and resolution."""
    return await get_traffic(db, hours=hours)


@router.get("/errors", response_model=list[ErrorStats])
async def observe_errors(
    hours: int = Query(default=1, ge=1, le=168, description="Time window in hours."),
    db: AsyncSession = Depends(get_db),
) -> list[ErrorStats]:
    """Error breakdown — only rows with error-class resolutions."""
    return await get_errors(db, hours=hours)


@router.get("/latency", response_model=list[LatencyStats])
async def observe_latency(
    hours: int = Query(default=1, ge=1, le=168, description="Time window in hours."),
    db: AsyncSession = Depends(get_db),
) -> list[LatencyStats]:
    """Average latency per resolved service, ordered fastest first."""
    return await get_latency(db, hours=hours)
