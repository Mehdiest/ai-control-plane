"""Policy Engine — the routing brain of the control plane.

Resolves which downstream service should handle a request by evaluating
active policies in priority order, then applying a three-stage match:

  Stage 1 — Request match: match_request_type vs caller's request_type.
  Stage 2 — Network topology match: region, latency_zone, network_tags.
  Stage 3 — Canary weighted selection: within a priority group, weight
             controls traffic share via random.choices().
"""

import logging
import random
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import Policy
from app.models.service import Service, ServiceStatus
from app.schemas.policy import RouteResult

logger = logging.getLogger("control_plane.policy_engine")

_ROUTABLE_STATUSES = {ServiceStatus.HEALTHY, ServiceStatus.DEGRADED}


async def resolve_route(request_type: str, db: AsyncSession) -> RouteResult:
    """Return the best available service for the given request type."""
    policies = await _fetch_matching_policies(request_type, db)

    if not policies:
        logger.warning("No active policy found for request_type='%s'.", request_type)
        return RouteResult(
            request_type=request_type,
            resolved_service="",
            resolution="no_policy",
            message=f"No active policy matches request type '{request_type}'.",
        )

    for priority, group in groupby(policies, key=lambda p: p.priority):
        group_policies = list(group)
        selected = _select_weighted(group_policies)

        if selected is None:
            logger.info(
                "Priority group %d for '%s': all policies have weight=0, skipping.",
                priority, request_type,
            )
            continue

        result = await _evaluate_policy(selected, request_type, db)
        if result.resolution in ("primary", "fallback"):
            return result

        # Safety net: try remaining policies in the group before falling through.
        remaining = [p for p in group_policies if p.id != selected.id and p.weight > 0]
        for policy in remaining:
            result = await _evaluate_policy(policy, request_type, db)
            if result.resolution in ("primary", "fallback"):
                return result

    logger.error(
        "All %d matching policies exhausted for request_type='%s'.",
        len(policies), request_type,
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

def _select_weighted(policies: list[Policy]) -> Policy | None:
    """Select one policy from a priority group using weighted random.

    Returns None if all policies have weight=0 (canary rollback state).
    """
    eligible = [p for p in policies if p.weight > 0]
    if not eligible:
        return None
    if len(eligible) == 1:
        return eligible[0]
    return random.choices(eligible, weights=[p.weight for p in eligible], k=1)[0]


async def _fetch_matching_policies(request_type: str, db: AsyncSession) -> list[Policy]:
    """Load active policies matching the request type, sorted by priority."""
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
    """Evaluate a single policy against health and network topology constraints."""
    primary = await _fetch_service(policy.target_service_name, db)

    if _is_eligible(primary, policy):
        logger.info(
            "Policy '%s' resolved '%s' → primary '%s' (status=%s, region=%s, weight=%d).",
            policy.name, request_type, policy.target_service_name,
            primary.status, primary.region, policy.weight,
        )
        return _build_result(request_type, primary, "primary", policy)

    _log_rejection(policy, primary, "primary")

    if policy.fallback_service_name:
        fallback = await _fetch_service(policy.fallback_service_name, db)
        if _is_eligible(fallback, policy):
            logger.warning(
                "Policy '%s': primary '%s' ineligible — failing over to '%s'.",
                policy.name, policy.target_service_name, policy.fallback_service_name,
            )
            return _build_result(request_type, fallback, "fallback", policy)
        _log_rejection(policy, fallback, "fallback")

    return RouteResult(
        request_type=request_type,
        resolved_service="",
        resolution="no_healthy_service",
        policy_name=policy.name,
        policy_weight=policy.weight,
        message=(
            f"Policy '{policy.name}': no eligible service found. "
            f"Constraints — region: {policy.match_region or 'any'}, "
            f"latency_zone: {policy.match_latency_zone or 'any'}, "
            f"network_tags: {policy.match_network_tags or 'any'}."
        ),
    )


def _is_eligible(service: Service | None, policy: Policy) -> bool:
    """Return True if the service passes health and all network topology checks.

    Network gate evaluation order:
      1. region       — exact match (BGP community-style filter)
      2. latency_zone — exact match (OSPF cost-style preference)
      3. network_tags — subset match (BGP extended community matching:
                        all required tags must be present on the service)
    """
    if service is None or service.status not in _ROUTABLE_STATUSES:
        return False

    if policy.match_region and service.region != policy.match_region:
        return False

    if policy.match_latency_zone and service.latency_zone.value != policy.match_latency_zone:
        return False

    if policy.match_network_tags:
        svc_tags = set(service.network_tags or [])
        if not set(policy.match_network_tags).issubset(svc_tags):
            return False

    return True


def _build_result(
    request_type: str,
    service: Service,
    resolution: str,
    policy: Policy,
) -> RouteResult:
    """Construct a RouteResult with the resolved service's network attributes."""
    return RouteResult(
        request_type=request_type,
        resolved_service=service.name,
        resolution=resolution,
        policy_name=policy.name,
        policy_weight=policy.weight,
        resolved_region=service.region,
        resolved_latency_zone=service.latency_zone.value,
        resolved_network_tags=service.network_tags or [],
        message=(
            f"Routed to {resolution} service '{service.name}' "
            f"(status={service.status.value}, region={service.region}, "
            f"latency_zone={service.latency_zone.value}, weight={policy.weight})."
        ),
    )


async def _fetch_service(name: str, db: AsyncSession) -> Service | None:
    """Look up a service by name; returns None if not registered."""
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
    elif policy.match_network_tags and not set(policy.match_network_tags).issubset(
        set(service.network_tags or [])
    ):
        reason = (
            f"network_tags mismatch "
            f"(service={service.network_tags}, policy={policy.match_network_tags})"
        )
    else:
        reason = "unknown"

    logger.warning(
        "Policy '%s': %s target '%s' rejected — %s.",
        policy.name, role,
        service.name if service else "N/A",
        reason,
    )
