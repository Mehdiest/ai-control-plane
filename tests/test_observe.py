"""Tests for the observability dashboard (Phase 4).

Covers:
  - RequestLog persistence on /route calls
  - GET /observe/summary
  - GET /observe/traffic
  - GET /observe/errors
  - GET /observe/latency
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.request_log import RequestLog
from app.models.service import LatencyZone, Service, ServiceStatus
from app.models.policy import Policy


@pytest.mark.asyncio
async def test_route_logs_request(async_client):
    """Each /route call should persist a RequestLog row."""
    # Seed a healthy service + active policy so resolution is "primary".
    async with AsyncSessionLocal() as db:
        svc = Service(
            name="bi-platform-eu",
            base_url="https://example.com",
            health_check_path="/health",
            status=ServiceStatus.HEALTHY,
            region="eu-west",
            latency_zone=LatencyZone.HIGH,
        )
        db.add(svc)
        pol = Policy(
            name="p1",
            match_request_type="analytics",
            target_service_name="bi-platform-eu",
            priority=1,
            is_active=True,
        )
        db.add(pol)
        await db.commit()

    resp = await async_client.post(
        "/api/v1/route",
        json={"request_type": "analytics"},
    )
    assert resp.status_code == 200

    async with AsyncSessionLocal() as db:
        logs = (await db.execute(__import__("sqlalchemy").select(RequestLog))).scalars().all()
        assert len(logs) == 1
        assert logs[0].request_type == "analytics"
        assert logs[0].resolved_service == "bi-platform-eu"
        assert logs[0].resolution == "primary"
        assert logs[0].latency_ms is not None


@pytest.mark.asyncio
async def test_observe_summary_empty(async_client):
    """Summary with no data should return zeros (except the dummy-svc seeded by async_client)."""
    resp = await async_client.get("/api/v1/observe/summary")
    assert resp.status_code == 200
    data = resp.json()
    # The async_client fixture seeds one dummy-svc, so counts reflect that.
    assert data["total_services"] == 1
    assert data["healthy"] == 1
    assert data["active_policies"] == 0
    assert data["requests_last_hour"] == 0


@pytest.mark.asyncio
async def test_observe_summary_with_data(async_client):
    """Summary should reflect seeded services, policies, and recent logs."""
    async with AsyncSessionLocal() as db:
        svc = Service(
            name="svc-a",
            base_url="http://example.com",
            health_check_path="/health",
            status=ServiceStatus.HEALTHY,
        )
        db.add(svc)
        pol = Policy(
            name="p1",
            match_request_type="analytics",
            target_service_name="svc-a",
            priority=1,
            is_active=True,
        )
        db.add(pol)
        db.add(RequestLog(
            tenant_id="t1",
            request_type="analytics",
            resolved_service="svc-a",
            resolution="primary",
            latency_ms=12.5,
        ))
        await db.commit()

    resp = await async_client.get("/api/v1/observe/summary")
    assert resp.status_code == 200
    data = resp.json()
    # async_client fixture seeds dummy-svc, plus svc-a we added = 2 total
    assert data["total_services"] == 2
    assert data["healthy"] == 2
    assert data["active_policies"] == 1
    assert data["requests_last_hour"] == 1


@pytest.mark.asyncio
async def test_observe_traffic(async_client):
    """Traffic endpoint should group by service + resolution."""
    async with AsyncSessionLocal() as db:
        for i in range(3):
            db.add(RequestLog(
                tenant_id="t1",
                request_type="analytics",
                resolved_service="svc-a",
                resolution="primary",
                latency_ms=10.0,
            ))
        db.add(RequestLog(
            tenant_id="t1",
            request_type="analytics",
            resolved_service="none",
            resolution="no_healthy_service",
            latency_ms=1.0,
        ))
        await db.commit()

    resp = await async_client.get("/api/v1/observe/traffic?hours=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # Highest count first
    assert data[0]["count"] == 3
    assert data[0]["resolved_service"] == "svc-a"


@pytest.mark.asyncio
async def test_observe_errors(async_client):
    """Errors endpoint should only return error resolutions."""
    async with AsyncSessionLocal() as db:
        db.add(RequestLog(
            tenant_id="t1",
            request_type="analytics",
            resolved_service="svc-a",
            resolution="primary",
            latency_ms=10.0,
        ))
        db.add(RequestLog(
            tenant_id="t1",
            request_type="analytics",
            resolved_service="none",
            resolution="no_healthy_service",
            latency_ms=1.0,
        ))
        db.add(RequestLog(
            tenant_id="t1",
            request_type="analytics",
            resolved_service="none",
            resolution="no_policy",
            latency_ms=1.0,
        ))
        await db.commit()

    resp = await async_client.get("/api/v1/observe/errors?hours=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    resolutions = {row["resolution"] for row in data}
    assert resolutions == {"no_healthy_service", "no_policy"}


@pytest.mark.asyncio
async def test_observe_latency(async_client):
    """Latency endpoint should return average latency per service."""
    async with AsyncSessionLocal() as db:
        db.add(RequestLog(
            tenant_id="t1",
            request_type="analytics",
            resolved_service="svc-a",
            resolution="primary",
            latency_ms=10.0,
        ))
        db.add(RequestLog(
            tenant_id="t1",
            request_type="analytics",
            resolved_service="svc-a",
            resolution="primary",
            latency_ms=20.0,
        ))
        db.add(RequestLog(
            tenant_id="t1",
            request_type="analytics",
            resolved_service="svc-b",
            resolution="primary",
            latency_ms=5.0,
        ))
        await db.commit()

    resp = await async_client.get("/api/v1/observe/latency?hours=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # Ordered by avg latency ascending — svc-b (5.0) should be first
    assert data[0]["resolved_service"] == "svc-b"
    assert data[0]["avg_latency_ms"] == 5.0
    assert data[1]["resolved_service"] == "svc-a"
    assert data[1]["avg_latency_ms"] == 15.0
    assert data[1]["sample_count"] == 2