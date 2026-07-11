"""
Unit tests for the policy engine routing logic.

Covers the core routing scenarios: primary resolution, failover,
network topology constraints (region and latency zone), policy
fallthrough, and no-match edge cases.
"""

import pytest
import pytest_asyncio

from app.core.database import AsyncSessionLocal
from app.models.policy import Policy
from app.models.service import LatencyZone, Service, ServiceStatus
from app.services.policy_engine import resolve_route
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_policy(db, **kwargs) -> Policy:
    defaults = dict(priority=1, match_request_type="analytics",
                    match_region=None, match_latency_zone=None,
                    fallback_service_name=None, is_active=True)
    defaults.update(kwargs)
    p = Policy(**defaults)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _set_status(db, name: str, status: ServiceStatus) -> None:
    svc = await db.scalar(select(Service).where(Service.name == name))
    svc.status = status
    await db.commit()


# ---------------------------------------------------------------------------
# Basic routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_routes_to_primary_when_healthy(healthy_service, local_service):
    """Primary service is healthy → resolution must be 'primary'."""
    async with AsyncSessionLocal() as db:
        await _make_policy(db, name="p1", target_service_name="bi-platform-eu",
                           fallback_service_name="local-llm")
        result = await resolve_route("analytics", db)

    assert result.resolution == "primary"
    assert result.resolved_service == "bi-platform-eu"
    assert result.policy_name == "p1"


@pytest.mark.asyncio
async def test_failover_when_primary_unhealthy(healthy_service, local_service):
    """Primary is unhealthy → engine falls back to the configured fallback."""
    async with AsyncSessionLocal() as db:
        await _make_policy(db, name="p1", target_service_name="bi-platform-eu",
                           fallback_service_name="local-llm")
        await _set_status(db, "bi-platform-eu", ServiceStatus.UNHEALTHY)
        result = await resolve_route("analytics", db)

    assert result.resolution == "fallback"
    assert result.resolved_service == "local-llm"


@pytest.mark.asyncio
async def test_no_healthy_service_when_both_down(healthy_service, local_service):
    """Both primary and fallback are unhealthy → resolution must be 'no_healthy_service'."""
    async with AsyncSessionLocal() as db:
        await _make_policy(db, name="p1", target_service_name="bi-platform-eu",
                           fallback_service_name="local-llm")
        await _set_status(db, "bi-platform-eu", ServiceStatus.UNHEALTHY)
        await _set_status(db, "local-llm", ServiceStatus.UNHEALTHY)
        result = await resolve_route("analytics", db)

    assert result.resolution == "no_healthy_service"
    assert result.resolved_service == ""


@pytest.mark.asyncio
async def test_no_policy_for_unknown_request_type(healthy_service):
    """No policy exists for this request type → resolution must be 'no_policy'."""
    async with AsyncSessionLocal() as db:
        result = await resolve_route("unknown-type", db)

    assert result.resolution == "no_policy"
    assert result.resolved_service == ""


# ---------------------------------------------------------------------------
# Health status transitions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_degraded_service_is_still_routable(healthy_service):
    """A DEGRADED service is still responding and must remain eligible for routing."""
    async with AsyncSessionLocal() as db:
        await _make_policy(db, name="p1", target_service_name="bi-platform-eu")
        await _set_status(db, "bi-platform-eu", ServiceStatus.DEGRADED)
        result = await resolve_route("analytics", db)

    assert result.resolution == "primary"
    assert result.resolved_service == "bi-platform-eu"


@pytest.mark.asyncio
async def test_unknown_status_service_is_not_routable(healthy_service):
    """A service in UNKNOWN status has not been health-checked yet and must not be routed to."""
    async with AsyncSessionLocal() as db:
        await _make_policy(db, name="p1", target_service_name="bi-platform-eu")
        await _set_status(db, "bi-platform-eu", ServiceStatus.UNKNOWN)
        result = await resolve_route("analytics", db)

    assert result.resolution == "no_healthy_service"


# ---------------------------------------------------------------------------
# Network topology constraints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_region_constraint_matches_correct_service(healthy_service, local_service):
    """Policy with match_region='eu-west' must route only to the eu-west service."""
    async with AsyncSessionLocal() as db:
        await _make_policy(db, name="p1", match_region="eu-west",
                           target_service_name="bi-platform-eu")
        result = await resolve_route("analytics", db)

    assert result.resolution == "primary"
    assert result.resolved_region == "eu-west"


@pytest.mark.asyncio
async def test_region_constraint_rejects_wrong_region(healthy_service, local_service):
    """Policy with match_region='eu-west' must not route to an on-premise service."""
    async with AsyncSessionLocal() as db:
        # Target is the on-premise service which has region='on-premise', not 'eu-west'.
        await _make_policy(db, name="p1", match_region="eu-west",
                           target_service_name="local-llm")
        result = await resolve_route("analytics", db)

    assert result.resolution == "no_healthy_service"


@pytest.mark.asyncio
async def test_latency_zone_constraint_matches_low_latency(healthy_service, local_service):
    """Policy with match_latency_zone='low' must prefer the on-premise low-latency service."""
    async with AsyncSessionLocal() as db:
        await _make_policy(db, name="p1", match_latency_zone="low",
                           target_service_name="local-llm")
        result = await resolve_route("analytics", db)

    assert result.resolution == "primary"
    assert result.resolved_latency_zone == "low"


@pytest.mark.asyncio
async def test_latency_zone_constraint_rejects_high_latency(healthy_service, local_service):
    """Policy with match_latency_zone='low' must reject a HIGH-latency service as target."""
    async with AsyncSessionLocal() as db:
        # bi-platform-eu has latency_zone=HIGH — should be rejected.
        await _make_policy(db, name="p1", match_latency_zone="low",
                           target_service_name="bi-platform-eu")
        result = await resolve_route("analytics", db)

    assert result.resolution == "no_healthy_service"


@pytest.mark.asyncio
async def test_network_tags_included_in_result(healthy_service, local_service):
    """Route result must include the resolved service's network tags."""
    async with AsyncSessionLocal() as db:
        await _make_policy(db, name="p1", target_service_name="bi-platform-eu")
        result = await resolve_route("analytics", db)

    assert "cloud" in result.resolved_network_tags
    assert "eu" in result.resolved_network_tags


# ---------------------------------------------------------------------------
# Policy fallthrough (priority ordering)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_falls_through_to_lower_priority_policy(healthy_service, local_service):
    """When a region-constrained policy (priority 1) fails, engine evaluates
    the next policy (priority 10) with no region constraint."""
    async with AsyncSessionLocal() as db:
        # Priority 1: eu-west only — target will be unhealthy.
        await _make_policy(db, name="eu-only", priority=1, match_region="eu-west",
                           target_service_name="bi-platform-eu")
        # Priority 10: any region — local-llm is the target.
        await _make_policy(db, name="any-region", priority=10, match_region=None,
                           target_service_name="local-llm")
        await _set_status(db, "bi-platform-eu", ServiceStatus.UNHEALTHY)
        result = await resolve_route("analytics", db)

    assert result.resolution == "primary"
    assert result.resolved_service == "local-llm"
    assert result.policy_name == "any-region"


@pytest.mark.asyncio
async def test_inactive_policy_is_skipped(healthy_service, local_service):
    """An inactive policy must never participate in routing evaluation."""
    async with AsyncSessionLocal() as db:
        # Active policy routes to local-llm.
        await _make_policy(db, name="active-p", priority=10,
                           target_service_name="local-llm", is_active=True)
        # Inactive policy would route to bi-platform-eu — must be ignored.
        await _make_policy(db, name="inactive-p", priority=1,
                           target_service_name="bi-platform-eu", is_active=False)
        result = await resolve_route("analytics", db)

    assert result.resolved_service == "local-llm"
    assert result.policy_name == "active-p"
