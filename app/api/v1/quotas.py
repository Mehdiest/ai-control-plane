"""Quota management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.quota import Quota
from app.schemas.quota import QuotaCreate, QuotaRead, QuotaStatus, QuotaUpdate
from app.services.rate_limiter import get_quota_status, reset_tenant_counter

router = APIRouter(prefix="/quotas", tags=["quotas"])


@router.post("", response_model=QuotaRead, status_code=status.HTTP_201_CREATED)
async def create_quota(payload: QuotaCreate, db: AsyncSession = Depends(get_db)) -> Quota:
    """Create a rate-limit quota for a tenant."""
    existing_quota = await db.scalar(select(Quota).where(Quota.tenant_id == payload.tenant_id))
    if existing_quota is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A quota for tenant '{payload.tenant_id}' already exists.",
        )

    quota = Quota(**payload.model_dump())
    db.add(quota)
    await db.commit()
    await db.refresh(quota)
    return quota


@router.get("/{tenant_id}", response_model=QuotaStatus)
async def get_quota(tenant_id: str, db: AsyncSession = Depends(get_db)) -> QuotaStatus:
    """Return a tenant's quota with current Redis consumption."""
    quota_status = await get_quota_status(tenant_id, db)
    if quota_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No quota defined for tenant '{tenant_id}'.",
        )
    return quota_status


@router.patch("/{tenant_id}", response_model=QuotaRead)
async def update_quota(
    tenant_id: str, payload: QuotaUpdate, db: AsyncSession = Depends(get_db)
) -> Quota:
    """Partially update a tenant's quota."""
    quota = await db.scalar(select(Quota).where(Quota.tenant_id == tenant_id))
    if quota is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No quota defined for tenant '{tenant_id}'.",
        )

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(quota, field, value)

    await db.commit()
    await db.refresh(quota)
    return quota


@router.delete("/{tenant_id}/counter", status_code=status.HTTP_204_NO_CONTENT)
async def reset_counter(tenant_id: str, db: AsyncSession = Depends(get_db)) -> None:
    """Reset the Redis counter for a tenant (does not delete the quota)."""
    deleted = await reset_tenant_counter(tenant_id, db)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No quota defined for tenant '{tenant_id}'.",
        )