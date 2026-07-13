"""Policy CRUD and route-resolution endpoints."""

import logging
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.security import get_tenant_id
from app.models.policy import Policy
from app.models.request_log import RequestLog
from app.schemas.policy import (
    PolicyCreate,
    PolicyRead,
    PolicyUpdate,
    PolicyWeightUpdate,
    RouteRequest,
    RouteResult,
)
from app.services.policy_engine import resolve_route
from app.services.rate_limiter import check_rate_limit

logger = logging.getLogger("control_plane.policies")

router = APIRouter()


async def _persist_request_log(
    tenant_id: str,
    request_type: str,
    resolved_service: str,
    resolution: str,
    policy_name: str | None,
    policy_weight: int | None,
    latency_ms: float,
) -> None:
    """Persist a request-log row in the background (off the critical path).

    Uses a dedicated session so it does not depend on the request-scoped
    session, which is closed as soon as the response is sent.
    """
    try:
        async with AsyncSessionLocal() as session:
            log_entry = RequestLog(
                tenant_id=tenant_id,
                request_type=request_type,
                resolved_service=resolved_service,
                resolution=resolution,
                policy_name=policy_name,
                policy_weight=policy_weight,
                latency_ms=latency_ms,
            )
            session.add(log_entry)
            await session.commit()
    except Exception:
        logger.exception("Failed to persist request log (background).")


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
    """Register a new routing policy with a unique name.

    Phase 5 — Canary Rollout: multiple active policies may now share the same
    priority (forming a canary group). Within a group, `weight` controls the
    traffic split. The old priority-uniqueness constraint has been removed.
    """
    existing_policy = await db.scalar(select(Policy).where(Policy.name == payload.name))
    if existing_policy is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A policy named '{payload.name}' already exists.",
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
    """Partially update a policy.

    Phase 5 — Canary Rollout: the priority-uniqueness re-check has been
    removed. Multiple active policies may now share a priority to form a
    canary group; `weight` controls the split within the group.
    """
    policy = await db.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")

    updates = payload.model_dump(exclude_unset=True)

    for field, value in updates.items():
        setattr(policy, field, value)

    await db.commit()
    await db.refresh(policy)
    return policy


@router.patch(
    "/policies/{policy_id}/weight",
    response_model=PolicyRead,
    tags=["policies"],
    summary="Adjust canary weight (rapid promotion/rollback)",
)
async def update_policy_weight(
    policy_id: uuid.UUID,
    payload: PolicyWeightUpdate,
    db: AsyncSession = Depends(get_db),
) -> Policy:
    """Lightweight weight-only update for canary promotion/rollback.

    This endpoint is optimised for the operational workflow of shifting
    traffic during a canary rollout: 5% → 50% → 100% to promote, or
    5% → 0 to instantly roll back a failing canary. It avoids the full
    PATCH body and the priority-uniqueness re-check, since weight changes
    never affect priority ordering.
    """
    policy = await db.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")

    policy.weight = payload.weight
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
    background_tasks: BackgroundTasks,
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

    # Persist the resolution for the observability dashboard via a background
    # task so the critical path (response latency) is not blocked by the DB
    # write.  Phase 5 — record which policy handled the request and its canary
    # weight so the traffic dashboard can show the canary split.
    background_tasks.add_task(
        _persist_request_log,
        tenant_id=tenant_id,
        request_type=payload.request_type,
        resolved_service=result.resolved_service or "none",
        resolution=result.resolution,
        policy_name=result.policy_name,
        policy_weight=result.policy_weight,
        latency_ms=round(latency_ms, 2),
    )

    return result
