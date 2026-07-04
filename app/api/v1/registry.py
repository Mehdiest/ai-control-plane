"""
Service registry endpoints.

Exposes CRUD operations for services the control plane governs, plus
a summary view intended to back a dashboard. Health data is populated
asynchronously by the background scheduler, not by these endpoints.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.service import Service, ServiceStatus
from app.schemas.service import RegistrySummary, ServiceCreate, ServiceRead

router = APIRouter(prefix="/registry", tags=["registry"])


@router.post("", response_model=ServiceRead, status_code=status.HTTP_201_CREATED)
async def register_service(payload: ServiceCreate, db: AsyncSession = Depends(get_db)) -> Service:
    """Register a new service with the control plane.

    The service starts in UNKNOWN status until the next health-check
    cycle runs, at which point it is promoted to HEALTHY, DEGRADED, or
    UNHEALTHY based on its actual response.
    """
    existing = await db.scalar(select(Service).where(Service.name == payload.name))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A service named '{payload.name}' is already registered.",
        )

    service = Service(
        name=payload.name,
        base_url=str(payload.base_url),
        health_check_path=payload.health_check_path,
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service


@router.get("", response_model=RegistrySummary)
async def list_services(db: AsyncSession = Depends(get_db)) -> RegistrySummary:
    """Return every registered service along with an aggregate health summary."""
    result = await db.execute(select(Service).order_by(Service.name))
    services = result.scalars().all()

    def count(s: ServiceStatus) -> int:
        return sum(1 for svc in services if svc.status == s)

    return RegistrySummary(
        total=len(services),
        healthy=count(ServiceStatus.HEALTHY),
        degraded=count(ServiceStatus.DEGRADED),
        unhealthy=count(ServiceStatus.UNHEALTHY),
        unknown=count(ServiceStatus.UNKNOWN),
        services=services,
    )


@router.get("/{service_id}", response_model=ServiceRead)
async def get_service(service_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Service:
    """Fetch a single service by its ID."""
    service = await db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found.")
    return service


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deregister_service(service_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Remove a service from the registry. It will no longer be health-checked or routed to."""
    service = await db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found.")
    await db.delete(service)
    await db.commit()
