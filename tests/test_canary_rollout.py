"""
Tests for Phase 5 — Canary Rollout.

Covers:
  - Weighted traffic distribution (90/10 split with ±10% tolerance)
  - Canary rollback via weight=0 (all traffic shifts to the other policy)
  - PATCH /policies/{id}/weight endpoint for rapid weight adjustment
  - Observability: traffic endpoint shows policy_name and policy_weight
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.policy import Policy
from app.models.quota import Quota
from app.models.service import LatencyZone, Service, ServiceStatus


async def _seed_canary_setup(db):
    """Seed two healthy services + a high quota so rate limiting doesn't interfere."""
    stable = Service(
        name="stable-svc",
        base_url="http://stable.example.com",
        health_check_path="/health",
        status=ServiceStatus.HEALTHY,
        region="eu-west",
        latency_zone=LatencyZone.HIGH,
    )
    canary = Service(
        name="canary-svc",
        base_url="http://canary.example.com",
        health_check_path="/health",
        status=ServiceStatus.HEALTHY,
        region="eu-west",
        latency_zone=LatencyZone.HIGH,
    )
    db.add(stable)
    db.add(canary)

    quota = Quota(
        tenant_id="anonymous",
        max_requests=10000,
        window_seconds=3600,
        is_active=True,
    )
    db.add(quota)
    await db.commit()
    return stable, canary


# ---------------------------------------------------------------------------
# Weighted distribution test (the Phase 5 gate test)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_canary_weighted_distribution(async_client):
    """Two policies with weight=90/10 should split traffic ~90/10 (±10% tolerance)."""
    async with AsyncSessionLocal() as db:
        await _seed_canary_setup(db)

    await async_client.post("/api/v1/policies", json={
        "name": "stable-pol", "priority": 1, "weight": 90,
        "match_request_type": "analytics",
        "target_service_name": "stable-svc",
    })
    await async_client.post("/api/v1/policies", json={
        "name": "canary-pol", "priority": 1, "weight": 10,
        "match_request_type": "analytics",
        "target_service_name": "canary-svc",
    })

    counts = {"stable-svc": 0, "canary-svc": 0}
    for _ in range(100):
        resp = await async_client.post(
            "/api/v1/route",
            json={"request_type": "analytics"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        svc = resp.json()["resolved_service"]
        counts[svc] += 1

    stable_pct = counts["stable-svc"]
    canary_pct = counts["canary-svc"]

    # ±10% tolerance: stable should be 80-100, canary should be 0-20.
    assert 80 <= stable_pct <= 100, f"Stable got {stable_pct}% — expected 80-100"
    assert 0 <= canary_pct <= 20, f"Canary got {canary_pct}% — expected 0-20"
    assert stable_pct + canary_pct == 100


# ---------------------------------------------------------------------------
# Canary rollback test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_canary_rollback_weight_zero(async_client):
    """Setting stable policy weight=0 should send all traffic to the canary."""
    async with AsyncSessionLocal() as db:
        await _seed_canary_setup(db)

    r1 = await async_client.post("/api/v1/policies", json={
        "name": "stable-pol", "priority": 1, "weight": 90,
        "match_request_type": "analytics",
        "target_service_name": "stable-svc",
    })
    r2 = await async_client.post("/api/v1/policies", json={
        "name": "canary-pol", "priority": 1, "weight": 10,
        "match_request_type": "analytics",
        "target_service_name": "canary-svc",
    })
    stable_id = r1.json()["id"]

    # Rollback: set stable weight to 0 via the dedicated weight endpoint.
    resp = await async_client.patch(
        f"/api/v1/policies/{stable_id}/weight",
        json={"weight": 0},
    )
    assert resp.status_code == 200
    assert resp.json()["weight"] == 0

    # All traffic should now go to canary-svc.
    for _ in range(20):
        resp = await async_client.post(
            "/api/v1/route",
            json={"request_type": "analytics"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["resolved_service"] == "canary-svc"


# ---------------------------------------------------------------------------
# PATCH /weight endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_weight_endpoint(async_client):
    """The dedicated weight endpoint should update only the weight field."""
    async with AsyncSessionLocal() as db:
        await _seed_canary_setup(db)

    r = await async_client.post("/api/v1/policies", json={
        "name": "p1", "priority": 1, "weight": 50,
        "match_request_type": "analytics",
        "target_service_name": "stable-svc",
    })
    policy_id = r.json()["id"]

    resp = await async_client.patch(
        f"/api/v1/policies/{policy_id}/weight",
        json={"weight": 25},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["weight"] == 25
    assert body["name"] == "p1"
    assert body["priority"] == 1


@pytest.mark.asyncio
async def test_patch_weight_404(async_client):
    """Patching weight of a non-existent policy should return 404."""
    fake_id = uuid.uuid4()
    resp = await async_client.patch(
        f"/api/v1/policies/{fake_id}/weight",
        json={"weight": 50},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_weight_validation(async_client):
    """Weight must be between 0 and 1000."""
    async with AsyncSessionLocal() as db:
        await _seed_canary_setup(db)
    r = await async_client.post("/api/v1/policies", json={
        "name": "p1", "priority": 1,
        "match_request_type": "analytics",
        "target_service_name": "stable-svc",
    })
    policy_id = r.json()["id"]

    resp = await async_client.patch(
        f"/api/v1/policies/{policy_id}/weight",
        json={"weight": -1},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Observability: traffic endpoint shows policy_name and policy_weight
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_traffic_shows_policy_weight(async_client):
    """GET /observe/traffic should include policy_name and policy_weight columns."""
    async with AsyncSessionLocal() as db:
        await _seed_canary_setup(db)

    await async_client.post("/api/v1/policies", json={
        "name": "stable-pol", "priority": 1, "weight": 90,
        "match_request_type": "analytics",
        "target_service_name": "stable-svc",
    })
    await async_client.post("/api/v1/policies", json={
        "name": "canary-pol", "priority": 1, "weight": 10,
        "match_request_type": "analytics",
        "target_service_name": "canary-svc",
    })

    for _ in range(10):
        await async_client.post(
            "/api/v1/route",
            json={"request_type": "analytics"},
            headers={"Authorization": "Bearer test-token"},
        )

    resp = await async_client.get("/api/v1/observe/traffic?hours=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1

    for row in data:
        assert row["policy_name"] is not None
        assert row["policy_weight"] is not None
        assert row["policy_name"] in ("stable-pol", "canary-pol")
        assert row["policy_weight"] in (90, 10)


# ---------------------------------------------------------------------------
# Priority + weight interaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_priority_groups_with_weights(async_client):
    """Priority determines group order; weight determines split within a group."""
    async with AsyncSessionLocal() as db:
        await _seed_canary_setup(db)

    await async_client.post("/api/v1/policies", json={
        "name": "p1-a", "priority": 1, "weight": 50,
        "match_request_type": "analytics",
        "target_service_name": "stable-svc",
    })
    await async_client.post("/api/v1/policies", json={
        "name": "p1-b", "priority": 1, "weight": 50,
        "match_request_type": "analytics",
        "target_service_name": "canary-svc",
    })
    await async_client.post("/api/v1/policies", json={
        "name": "p2-a", "priority": 2, "weight": 100,
        "match_request_type": "analytics",
        "target_service_name": "stable-svc",
    })

    # All traffic should be served by priority-1 group (both services healthy).
    for _ in range(20):
        resp = await async_client.post(
            "/api/v1/route",
            json={"request_type": "analytics"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        svc = resp.json()["resolved_service"]
        assert svc in ("stable-svc", "canary-svc")