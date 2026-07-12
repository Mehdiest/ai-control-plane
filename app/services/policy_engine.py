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

  Stage 3 — Canary weighted selection (added in Phase 5):
    When multiple active policies share the same priority, they form a
    "canary group". Within the group, `weight` controls what fraction
    of traffic each policy receives via `random.choices()`. A weight
    of 0 removes a policy from the canary split entirely — instant
    rollback without deletion.

    Priority and weight work together:
      - Priority — which group of policies is evaluated first
      - Weight   — within a group of equal-priority policies, what
                   percentage of traffic goes to each

No FastAPI dependencies live here — this module is pure business logic
and can be unit-tested independently of the web layer.
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

# Health statuses that allow routing. DEGRADED is included because the
# service is still responding — just with some intermittent failures.
_ROUTABLE_STATUSES = {ServiceStatus.HEALTHY, ServiceStatus.DEGRADED}


async def resolve_route(request_type: str, db: AsyncSession) -> RouteResult:
    """Return the best available service for the given request type.

    Evaluates all active policies whose match_request_type equals the
    supplied value, ordered by priority. Policies sharing the same
    priority form a canary group — within the group, one policy is
    selected via weighted random selection. If the selected policy's
    targets are unavailable, remaining policies in the group are tried
    as a safety net before falling through to the next priority group.

    Args:
        request_type: Logical category supplied by the caller (e.g. "analytics").
        db: Active async database session (injected by FastAPI).

    Returns:
        A RouteResult describing which service was chosen and why,
        including the resolved service's network topology attributes
        and the matched policy's canary weight.
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

    # Group policies by priority. `itertools.groupby` requires the input
    # to be sorted by the key — `_fetch_matching_policies` already sorts
    # by priority ascending, so this is safe.
    for priority, group in groupby(policies, key=lambda p: p.priority):
        group_policies = list(group)

        # Select one policy from this group via weighted random selection.
        selected = _select_weighted(group_policies)

        if selected is None:
            # All policies in this group have weight=0 — skip to next group.
            logger.info(
                "Priority group %d for request_type='%s': all policies have "
                "weight=0, skipping group.",
                priority, request_type,
            )
            continue

        # Try the selected policy first.
        result = await _evaluate_policy(selected, request_type, db)
        if result.resolution in ("primary", "fallback"):
            return result

        # Safety net: if the selected policy failed (e.g. its target is
        # unhealthy), try the remaining policies in the group before
        # falling through to the next priority group. This prevents a
        # single downed canary target from failing requests when a
        # healthy alternative exists in the same group.
        remaining = [p for p in group_policies if p.id != selected.id and p.weight > 0]
        for policy in remaining:
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

def _select_weighted(policies: list[Policy]) -> Policy | None:
    """Select one policy from a priority group using weighted random.

    Policies with weight=0 are excluded from the selection — this is
    the canary rollback mechanism. If all policies have weight=0,
    returns None so the caller can skip the group.

    Uses `random.choices()` — simple and dependency-free. When only one
    policy has a non-zero weight, it is returned directly without
    invoking the RNG for deterministic behaviour.
    """
    eligible = [p for p in policies if p.weight > 0]

    if not eligible:
        return None

    if len(eligible) == 1:
        return eligible[0]

    weights = [p.weight for p in eligible]
    return random.choices(eligible, weights=weights, k=1)[0]


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
            "(status=%s, region=%s, latency_zone=%s, weight=%d).",
            policy.name, request_type, policy.target_service_name,
            primary.status, primary.region, primary.latency_zone, policy.weight,
        )
        return _build_result(request_type, primary, "primary", policy)

    # Log why the primary was rejected.
    _log_rejection(policy, primary, "primary")

    # Try fallback if configured.
    if policy.fallback_service_name:
        fallback = await _fetch_service(policy.fallback_service_name, db)

        if _is_eligible(fallback, policy):
            logger.warning(
                "Policy '%s': primary '%s' ineligible — failing over to '%s' "
                "(region=%s, latency_zone=%s, weight=%d).",
                policy.name, policy.target_service_name,
                policy.fallback_service_name,
                fallback.region, fallback.latency_zone, policy.weight,
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
    policy: Policy,
) -> RouteResult:
    """Construct a RouteResult populated with the resolved service's network attributes."""
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