"""
Policy management and route-resolution endpoints.

/api/v1/policies  — CRUD for routing policies.
/api/v1/route     — Single endpoint that the caller hits to ask the control
                    plane "which service should handle this request?".
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.policy import Policy
from app.schemas.policy import PolicyCreate, PolicyRead, PolicyUpdate, RouteRequest, RouteResult
from app.services.policy_engine import resolve_route

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
    """Register a new routing policy.

    Priority values are unique per request type — a conflict raises 409
    so the caller is forced to make the ordering explicit.
    """
    existing = await db.scalar(select(Policy).where(Policy.name == payload.name))
    if existing is not None:
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
    """Partially update a policy (e.g. change priority, toggle active flag).

    Only fields explicitly supplied in the request body are modified;
    omitted fields retain their current values.
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
async def resolve(payload: RouteRequest, db: AsyncSession = Depends(get_db)) -> RouteResult:
    """Ask the policy engine which service should handle a given request type.

    The engine evaluates active policies in priority order and checks
    live health status before committing to a route. The caller receives
    a resolution code alongside the chosen service name so it can decide
    how to handle degraded or unavailable outcomes.

    Resolution codes:
    - **primary**           — routed to the first-choice service.
    - **fallback**          — primary was down; routed to the configured fallback.
    - **no_policy**         — no active policy matches this request type.
    - **no_healthy_service** — matching policies exist but all targets are unavailable.
    """
    return await resolve_route(payload.request_type, db)
