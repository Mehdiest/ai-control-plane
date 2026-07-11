"""
Phase 3 — Rate Limiting & Quota per Tenant.

Test gate scenarios:
1. Tenant with quota=5 in window=60s → 6th request returns 429.
2. Tenant without a quota → requests pass (default behavior).
3. Quota exists but is_active=False → requests pass.
"""

import pytest

from app.core.database import AsyncSessionLocal
from app.models.policy import Policy
from app.models.quota import Quota
from app.models.service import Service, ServiceStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_quota(db, tenant_id: str, max_requests: int = 5,
                        window_seconds: int = 60, is_active: bool = True) -> Quota:
    q = Quota(
        tenant_id=tenant_id,
        max_requests=max_requests,
        window_seconds=window_seconds,
        is_active=is_active,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


async def _seed_service_and_policy(db) -> None:
    """Seed a healthy service + a simple policy so /route can resolve.

    Uses a unique service name to avoid clashing with the dummy-svc
    already seeded by the ``async_client`` fixture.
    """
    svc = Service(
        name="rate-limit-test-svc",
        base_url="http://example.com",
        health_check_path="/health",
        status=ServiceStatus.HEALTHY,
    )
    db.add(svc)
    p = Policy(
        name="p1",
        priority=1,
        match_request_type="analytics",
        target_service_name="rate-limit-test-svc",
        is_active=True,
    )
    db.add(p)
    await db.commit()


# ---------------------------------------------------------------------------
# Service-level tests (direct rate_limiter.check_rate_limit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quota_exceeded_after_max_requests():
    """Quota=5 → first 5 requests allowed, 6th is denied."""
    async with AsyncSessionLocal() as db:
        await _create_quota(db, tenant_id="acme", max_requests=5, window_seconds=60)

        from app.services.rate_limiter import check_rate_limit

        for i in range(5):
            result = await check_rate_limit("acme", db)
            assert result.allowed, f"Request {i+1} should be allowed"

        result = await check_rate_limit("acme", db)
        assert not result.allowed, "6th request should be denied"
        assert result.count == 6


@pytest.mark.asyncio
async def test_no_quota_means_pass():
    """Tenant without a quota row → all requests pass."""
    async with AsyncSessionLocal() as db:
        from app.services.rate_limiter import check_rate_limit

        for _ in range(20):
            result = await check_rate_limit("ghost-tenant", db)
            assert result.allowed
            assert result.quota is None


@pytest.mark.asyncio
async def test_inactive_quota_means_pass():
    """Quota exists but is_active=False → requests pass without counting."""
    async with AsyncSessionLocal() as db:
        await _create_quota(db, tenant_id="sleeper", max_requests=1,
                            window_seconds=60, is_active=False)

        from app.services.rate_limiter import check_rate_limit

        for _ in range(10):
            result = await check_rate_limit("sleeper", db)
            assert result.allowed


# ---------------------------------------------------------------------------
# API-level tests (POST /api/v1/route with 429)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_route_returns_429_after_quota_exceeded(async_client):
    """End-to-end: 6th /route call returns 429 Too Many Requests."""
    async with AsyncSessionLocal() as db:
        await _seed_service_and_policy(db)
        await _create_quota(db, tenant_id="anonymous", max_requests=5, window_seconds=60)

    payload = {"request_type": "analytics"}

    for i in range(5):
        resp = await async_client.post("/api/v1/route", json=payload)
        assert resp.status_code == 200, f"Request {i+1} should succeed, got {resp.status_code}"

    resp = await async_client.post("/api/v1/route", json=payload)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert resp.headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_route_passes_without_quota(async_client):
    """No quota defined for the tenant → /route always returns 200."""
    async with AsyncSessionLocal() as db:
        await _seed_service_and_policy(db)

    payload = {"request_type": "analytics"}

    for _ in range(15):
        resp = await async_client.post("/api/v1/route", json=payload)
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_route_passes_with_inactive_quota(async_client):
    """Quota exists but is_active=False → /route always returns 200."""
    async with AsyncSessionLocal() as db:
        await _seed_service_and_policy(db)
        await _create_quota(db, tenant_id="anonymous", max_requests=1,
                            window_seconds=60, is_active=False)

    payload = {"request_type": "analytics"}

    for _ in range(10):
        resp = await async_client.post("/api/v1/route", json=payload)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Quota CRUD API tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_quota_endpoint(async_client):
    """POST /api/v1/quotas creates a quota and returns 201."""
    resp = await async_client.post("/api/v1/quotas", json={
        "tenant_id": "acme",
        "max_requests": 100,
        "window_seconds": 60,
        "is_active": True,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["tenant_id"] == "acme"
    assert data["max_requests"] == 100
    assert data["window_seconds"] == 60
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_quota_conflict_on_duplicate(async_client):
    """POST /api/v1/quotas with an existing tenant_id returns 409."""
    payload = {"tenant_id": "acme", "max_requests": 10, "window_seconds": 60}
    resp1 = await async_client.post("/api/v1/quotas", json=payload)
    assert resp1.status_code == 201

    resp2 = await async_client.post("/api/v1/quotas", json=payload)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_get_quota_status_endpoint(async_client):
    """GET /api/v1/quotas/{tenant_id} returns quota with live consumption."""
    await async_client.post("/api/v1/quotas", json={
        "tenant_id": "acme", "max_requests": 5, "window_seconds": 60,
    })

    resp = await async_client.get("/api/v1/quotas/acme")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == "acme"
    assert data["max_requests"] == 5
    assert data["current_count"] == 0
    assert data["remaining"] == 5


@pytest.mark.asyncio
async def test_get_quota_not_found(async_client):
    """GET /api/v1/quotas/{unknown} returns 404."""
    resp = await async_client.get("/api/v1/quotas/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_quota_endpoint(async_client):
    """PATCH /api/v1/quotas/{tenant_id} updates the limit."""
    await async_client.post("/api/v1/quotas", json={
        "tenant_id": "acme", "max_requests": 5, "window_seconds": 60,
    })

    resp = await async_client.patch("/api/v1/quotas/acme", json={"max_requests": 100})
    assert resp.status_code == 200
    assert resp.json()["max_requests"] == 100


@pytest.mark.asyncio
async def test_patch_quota_toggle_active(async_client):
    """PATCH can deactivate a quota."""
    await async_client.post("/api/v1/quotas", json={
        "tenant_id": "acme", "max_requests": 5, "window_seconds": 60,
    })

    resp = await async_client.patch("/api/v1/quotas/acme", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_reset_counter_endpoint(async_client):
    """DELETE /api/v1/quotas/{tenant_id}/counter resets the Redis counter."""
    await async_client.post("/api/v1/quotas", json={
        "tenant_id": "acme", "max_requests": 5, "window_seconds": 60,
    })

    # Consume some quota.
    from app.services.rate_limiter import check_rate_limit
    async with AsyncSessionLocal() as db:
        await check_rate_limit("acme", db)
        await check_rate_limit("acme", db)

    resp = await async_client.delete("/api/v1/quotas/acme/counter")
    assert resp.status_code == 204

    # Counter should be back to 0.
    status_resp = await async_client.get("/api/v1/quotas/acme")
    assert status_resp.json()["current_count"] == 0