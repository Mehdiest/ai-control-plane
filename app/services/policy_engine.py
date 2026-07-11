"""
Policy Engine — the routing brain of the control plane.

Resolves which downstream service should handle a request by evaluating
active policies in priority order, then applying a two-stage match:

  Stage 1 — Request match (inherited from Phase 2):
    Match the policy's `match_request_type` against the caller's
    `request_type`. This is the top-level classifier, equivalent to
    an ACL match at the top of a route-map clause.

  Stage 2 — Network topology match (added in Phase 2.1):
    Verify that the resolved service's network attributes satisfy the
    policy's optional constraints:

      match_region       → service.region must equal this value
                           (analogous to BGP community filtering —
                            "only use paths advertised from AS X")

      match_latency_zone → service.latency_zone must equal this value
                           (analogous to OSPF link-cost preference —
                            "only use links with cost ≤ N")

    When a network constraint is set and the primary target does not
    satisfy it, the engine treats that target as ineligible and tries
    the fallback. If neither target satisfies the constraints, the
    policy is skipped entirely and the next one in priority order is
    evaluated — matching how a route-map clause with a failed match
    falls through to the next clause rather than terminating.

No FastAPI dependencies live here — this module is pure business logic
and can be unit-tested independently of the web layer.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import Policy
from app.models.service import Service, ServiceStatus
from app.schemas.policy import RouteResult

logger = logging.getLogger("control_plane.policy_engine")

# Health statuses that allow routing. DEGRADED is included because the
# service is still responding — just with some intermittent failures.
_ROUTABLE_STATUSES = {ServiceStatus.HEALTHY, ServiceStatus.DEGRADED}


async def resolve_route(request_type: str, db: AsyncSession) -> RouteResult:
    """Return the best available service for the given request type.

    Evaluates all active policies whose match_request_type equals the
    supplied value, ordered by priority. For each candidate policy the
    engine checks both health status and network topology constraints
    before committing to a route.

    Args:
        request_type: Logical category supplied by the caller (e.g. "analytics").
        db: Active async database session (injected by FastAPI).

    Returns:
        A RouteResult describing which service was chosen and why,
        including the resolved service's network topology attributes.
    """
    policies = await _fetch_matching_policies(request_type, db)

    if not policies:
        logger.warning("No active policy found for request_type='%s'.", request_type)
        return RouteResult(
            request_type=request_type,
            resolved_service="",
            resolution="no_policy",
            message=f"No active policy matches request type '{request_type}'.",
        )

    for policy in policies:
        result = await _evaluate_policy(policy, request_type, db)
        if result.resolution in ("primary", "fallback"):
            return result

    logger.error(
        "All %d matching policies exhausted for request_type='%s' — no eligible service.",
        len(policies),
        request_type,
    )
    return RouteResult(
        request_type=request_type,
        resolved_service="",
        resolution="no_healthy_service",
        message="All matching policies were evaluated but no eligible service is available.",
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
    """Evaluate a single policy against both health and network topology constraints.

    Tries the primary target first. If it fails either the health check
    or the network constraint, the fallback is attempted with the same
    validation. If both fail, returns a no_healthy_service result so
    the caller can proceed to the next policy in the list.
    """
    primary = await _fetch_service(policy.target_service_name, db)

    if _is_eligible(primary, policy):
        logger.info(
            "Policy '%s' resolved '%s' → primary '%s' "
            "(status=%s, region=%s, latency_zone=%s).",
            policy.name, request_type, policy.target_service_name,
            primary.status, primary.region, primary.latency_zone,
        )
        return _build_result(request_type, primary, "primary", policy.name)

    # Log why the primary was rejected.
    _log_rejection(policy, primary, "primary")

    # Try fallback if configured.
    if policy.fallback_service_name:
        fallback = await _fetch_service(policy.fallback_service_name, db)

        if _is_eligible(fallback, policy):
            logger.warning(
                "Policy '%s': primary '%s' ineligible — failing over to '%s' "
                "(region=%s, latency_zone=%s).",
                policy.name, policy.target_service_name,
                policy.fallback_service_name,
                fallback.region, fallback.latency_zone,
            )
            return _build_result(request_type, fallback, "fallback", policy.name)

        _log_rejection(policy, fallback, "fallback")

    return RouteResult(
        request_type=request_type,
        resolved_service="",
        resolution="no_healthy_service",
        policy_name=policy.name,
        message=(
            f"Policy '{policy.name}': no eligible service found. "
            f"Constraints — region: {policy.match_region or 'any'}, "
            f"latency_zone: {policy.match_latency_zone or 'any'}."
        ),
    )


def _is_eligible(service: Service | None, policy: Policy) -> bool:
    """Return True if the service passes both health and network topology checks.

    Health gate: service must exist and have a routable status.
    Network gate (applied only when the policy sets a constraint):
      - region must match exactly         (BGP community-style filter)
      - latency_zone must match exactly   (OSPF cost-style preference)
    """
    if service is None or service.status not in _ROUTABLE_STATUSES:
        return False

    if policy.match_region and service.region != policy.match_region:
        return False

    if policy.match_latency_zone and service.latency_zone.value != policy.match_latency_zone:
        return False

    return True


def _build_result(
    request_type: str,
    service: Service,
    resolution: str,
    policy_name: str,
) -> RouteResult:
    """Construct a RouteResult populated with the resolved service's network attributes."""
    return RouteResult(
        request_type=request_type,
        resolved_service=service.name,
        resolution=resolution,
        policy_name=policy_name,
        resolved_region=service.region,
        resolved_latency_zone=service.latency_zone.value,
        resolved_network_tags=service.network_tags or [],
        message=(
            f"Routed to {resolution} service '{service.name}' "
            f"(status={service.status.value}, region={service.region}, "
            f"latency_zone={service.latency_zone.value})."
        ),
    )


async def _fetch_service(name: str, db: AsyncSession) -> Service | None:
    """Look up a service by name; returns None if it is not registered."""
    return await db.scalar(select(Service).where(Service.name == name))


def _log_rejection(policy: Policy, service: Service | None, role: str) -> None:
    """Log why a candidate service was rejected during policy evaluation."""
    if service is None:
        reason = "not registered"
    elif service.status not in _ROUTABLE_STATUSES:
        reason = f"status={service.status.value}"
    elif policy.match_region and service.region != policy.match_region:
        reason = f"region mismatch (service={service.region}, policy={policy.match_region})"
    elif policy.match_latency_zone and service.latency_zone.value != policy.match_latency_zone:
        reason = (
            f"latency_zone mismatch "
            f"(service={service.latency_zone.value}, policy={policy.match_latency_zone})"
        )
    else:
        reason = "unknown"

    logger.warning(
        "Policy '%s': %s target '%s' rejected — %s.",
        policy.name, role,
        service.name if service else "N/A",
        reason,
    )
