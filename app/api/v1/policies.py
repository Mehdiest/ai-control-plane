"""Policy CRUD and route-resolution endpoints."""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_tenant_id
from app.models.policy import Policy
from app.models.request_log import RequestLog
from app.schemas.policy import PolicyCreate, PolicyRead, PolicyUpdate, RouteRequest, RouteResult
from app.services.policy_engine import resolve_route
from app.services.rate_limiter import check_rate_limit

router = APIRouter()


# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------

@router.post(
    "/policies",
    response_model=PolicyRead,
    status_code=status.HTTP_201_CREATED,
    tags=["policies"],
)
async def create_policy(payload: PolicyCreate, db: AsyncSession = Depends(get_db)) -> Policy:
    """Register a new routing policy with unique name and priority."""
    existing_policy = await db.scalar(select(Policy).where(Policy.name == payload.name))
    if existing_policy is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A policy named '{payload.name}' already exists.",
        )

    priority_conflict = await db.scalar(
        select(Policy).where(
            Policy.match_request_type == payload.match_request_type,
            Policy.priority == payload.priority,
            Policy.is_active.is_(True),
        )
    )
    if priority_conflict is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"An active policy for request type '{payload.match_request_type}' "
                f"already uses priority {payload.priority}. "
                "Choose a different priority value."
            ),
        )

    policy = Policy(**payload.model_dump())
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return policy


@router.get("/policies", response_model=list[PolicyRead], tags=["policies"])
async def list_policies(db: AsyncSession = Depends(get_db)) -> list[Policy]:
    """Return all policies ordered by priority (active first, then inactive)."""
    result = await db.execute(
        select(Policy).order_by(Policy.is_active.desc(), Policy.priority.asc())
    )
    return list(result.scalars().all())


@router.get("/policies/{policy_id}", response_model=PolicyRead, tags=["policies"])
async def get_policy(policy_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Policy:
    """Fetch a single policy by ID."""
    policy = await db.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    return policy


@router.patch("/policies/{policy_id}", response_model=PolicyRead, tags=["policies"])
async def update_policy(
    policy_id: uuid.UUID, payload: PolicyUpdate, db: AsyncSession = Depends(get_db)
) -> Policy:
    """Partially update a policy; re-checks priority uniqueness on active policies."""
    policy = await db.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")

    updates = payload.model_dump(exclude_unset=True)

    effective_request_type = updates.get("match_request_type", policy.match_request_type)
    effective_priority = updates.get("priority", policy.priority)
    effective_is_active = updates.get("is_active", policy.is_active)

    if effective_is_active and (
        "priority" in updates or "match_request_type" in updates or "is_active" in updates
    ):
        priority_conflict = await db.scalar(
            select(Policy).where(
                Policy.match_request_type == effective_request_type,
                Policy.priority == effective_priority,
                Policy.is_active.is_(True),
                Policy.id != policy_id,
            )
        )
        if priority_conflict is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"An active policy for request type '{effective_request_type}' "
                    f"already uses priority {effective_priority}. "
                    "Choose a different priority value."
                ),
            )

    for field, value in updates.items():
        setattr(policy, field, value)

    await db.commit()
    await db.refresh(policy)
    return policy


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["policies"])
async def delete_policy(policy_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Permanently remove a policy. Use PATCH with is_active=false for soft disable."""
    policy = await db.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    await db.delete(policy)
    await db.commit()


# ---------------------------------------------------------------------------
# Route resolution
# ---------------------------------------------------------------------------

@router.post("/route", response_model=RouteResult, tags=["routing"])
async def resolve(
    payload: RouteRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> RouteResult:
    """Resolve a route by request type, checking rate limit before policy evaluation."""
    settings = get_settings()
    if settings.rate_limit_enabled:
        rate_result = await check_rate_limit(tenant_id, db)
        if not rate_result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Rate limit exceeded for tenant '{tenant_id}': "
                    f"{rate_result.count}/{rate_result.quota.max_requests} requests in "
                    f"{rate_result.quota.window_seconds}s window."
                ),
                headers={
                    "Retry-After": str(rate_result.quota.window_seconds),
                    "X-RateLimit-Limit": str(rate_result.quota.max_requests),
                    "X-RateLimit-Remaining": "0",
                },
            )

    start = time.perf_counter()
    result = await resolve_route(payload.request_type, db)
    latency_ms = (time.perf_counter() - start) * 1000

    # Persist the resolution for the observability dashboard.
    log_entry = RequestLog(
        tenant_id=tenant_id,
        request_type=payload.request_type,
        resolved_service=result.resolved_service or "none",
        resolution=result.resolution,
        latency_ms=round(latency_ms, 2),
    )
    db.add(log_entry)
    await db.commit()

    return result