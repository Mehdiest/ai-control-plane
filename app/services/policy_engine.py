"""
Policy Engine — the routing brain of the control plane.

Resolves which downstream service should handle a request by evaluating
active policies in priority order (lowest number first), then verifying
the target's current health before committing to the route.

The logic mirrors policy-based routing in traditional networking:
  1. Walk the policy list top-to-bottom (priority ascending).
  2. On first match, attempt the primary target.
  3. If the primary is unhealthy, try the fallback.
  4. If neither is usable, surface a clear resolution code to the caller
     rather than silently failing.

No FastAPI dependencies live here — this module is pure business logic
and can be unit-tested without spinning up the web layer.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import Policy
from app.models.service import Service, ServiceStatus
from app.schemas.policy import RouteResult

logger = logging.getLogger("control_plane.policy_engine")

# Statuses that are safe to route to. DEGRADED is deliberately included
# because the service is still responding — just with some recent failures.
_ROUTABLE_STATUSES = {ServiceStatus.HEALTHY, ServiceStatus.DEGRADED}


async def resolve_route(request_type: str, db: AsyncSession) -> RouteResult:
    """Return the best available service for the given request type.

    Evaluates all active policies whose `match_request_type` equals the
    supplied value, ordered by priority. For each candidate policy the
    engine checks the primary target's health and falls back to the
    secondary when needed.

    Args:
        request_type: Logical category supplied by the caller (e.g. "analytics").
        db: Active async database session (injected by FastAPI).

    Returns:
        A RouteResult describing which service was chosen and why.
    """
    policies = await _fetch_matching_policies(request_type, db)

    if not policies:
        logger.warning("No active policy found for request_type='%s'.", request_type)
        return RouteResult(
            request_type=request_type,
            resolved_service="",
            resolution="no_policy",
            policy_name=None,
            message=f"No active policy matches request type '{request_type}'.",
        )

    for policy in policies:
        result = await _evaluate_policy(policy, request_type, db)
        if result.resolution in ("primary", "fallback"):
            return result

    # Every matching policy had both targets unavailable.
    logger.error(
        "All %d matching policy/policies exhausted for request_type='%s' — no healthy service.",
        len(policies),
        request_type,
    )
    return RouteResult(
        request_type=request_type,
        resolved_service="",
        resolution="no_healthy_service",
        policy_name=None,
        message="All matching policies were evaluated but no healthy service is available.",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_matching_policies(request_type: str, db: AsyncSession) -> list[Policy]:
    """Load active policies that match the given request type, sorted by priority."""
    result = await db.execute(
        select(Policy)
        .where(Policy.is_active.is_(True))
        .where(Policy.match_request_type == request_type)
        .order_by(Policy.priority.asc())
    )
    return list(result.scalars().all())


async def _evaluate_policy(
    policy: Policy, request_type: str, db: AsyncSession
) -> RouteResult:
    """Try the primary target of a single policy, then its fallback if needed."""
    primary = await _fetch_service(policy.target_service_name, db)

    if _is_routable(primary):
        logger.info(
            "Policy '%s' resolved '%s' → primary '%s' (status=%s).",
            policy.name, request_type, policy.target_service_name, primary.status,
        )
        return RouteResult(
            request_type=request_type,
            resolved_service=policy.target_service_name,
            resolution="primary",
            policy_name=policy.name,
            message=f"Routed to primary service '{policy.target_service_name}' "
                    f"(status={primary.status.value}).",
        )

    # Primary is down — try fallback if one is configured.
    if policy.fallback_service_name:
        fallback = await _fetch_service(policy.fallback_service_name, db)

        if _is_routable(fallback):
            logger.warning(
                "Policy '%s': primary '%s' is %s — failing over to '%s'.",
                policy.name,
                policy.target_service_name,
                primary.status if primary else "not found",
                policy.fallback_service_name,
            )
            return RouteResult(
                request_type=request_type,
                resolved_service=policy.fallback_service_name,
                resolution="fallback",
                policy_name=policy.name,
                message=f"Primary '{policy.target_service_name}' is unavailable "
                        f"({primary.status.value if primary else 'not registered'}). "
                        f"Failed over to '{policy.fallback_service_name}'.",
            )

    # Neither primary nor fallback is routable — signal the caller to try the next policy.
    primary_status = primary.status.value if primary else "not registered"
    logger.warning(
        "Policy '%s': primary '%s' is %s and no usable fallback — skipping.",
        policy.name, policy.target_service_name, primary_status,
    )
    return RouteResult(
        request_type=request_type,
        resolved_service="",
        resolution="no_healthy_service",
        policy_name=policy.name,
        message=f"Primary '{policy.target_service_name}' is {primary_status} "
                "and no usable fallback is configured.",
    )


async def _fetch_service(name: str, db: AsyncSession) -> Service | None:
    """Look up a service by name; returns None if it is not registered."""
    return await db.scalar(select(Service).where(Service.name == name))


def _is_routable(service: Service | None) -> bool:
    """Return True if the service exists and its status allows routing."""
    return service is not None and service.status in _ROUTABLE_STATUSES
