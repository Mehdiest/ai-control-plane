"""
Unit tests for policy conflict validation.

Phase 5 — Canary Rollout: the priority-uniqueness constraint has been
removed. Multiple active policies may now share the same priority to form
a canary group; `weight` controls the traffic split within the group.

These tests verify:
  - Name uniqueness is still enforced (409 on duplicate name).
  - Same-priority active policies are now allowed (canary groups).
  - Inactive policies never block active ones.
"""

import pytest

from app.core.database import AsyncSessionLocal
from app.models.policy import Policy
from app.models.service import Service, ServiceStatus


async def _seed_service(db) -> None:
    svc = Service(
        name="dummy-svc",
        base_url="http://example.com",
        health_check_path="/health",
        status=ServiceStatus.HEALTHY,
    )
    db.add(svc)
    await db.commit()


async def _seed_policy(db, name: str, priority: int, request_type: str = "analytics") -> Policy:
    p = Policy(
        name=name,
        priority=priority,
        match_request_type=request_type,
        target_service_name="dummy-svc",
        is_active=True,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


# ---------------------------------------------------------------------------
# Name uniqueness (still enforced)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_duplicate_name_raises_409(async_client):
    """Creating two policies with the same name must return 409."""
    await async_client.post("/api/v1/policies", json={
        "name": "p1", "priority": 1,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    response = await async_client.post("/api/v1/policies", json={
        "name": "p1", "priority": 2,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Same-priority active policies now allowed (canary groups)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_same_priority_allowed(async_client):
    """Phase 5: two active policies with the same priority must succeed (canary group)."""
    r1 = await async_client.post("/api/v1/policies", json={
        "name": "stable", "priority": 1, "weight": 90,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    assert r1.status_code == 201

    r2 = await async_client.post("/api/v1/policies", json={
        "name": "canary", "priority": 1, "weight": 10,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    assert r2.status_code == 201
    assert r2.json()["priority"] == 1
    assert r2.json()["weight"] == 10


@pytest.mark.asyncio
async def test_update_priority_to_existing_now_allowed(async_client):
    """Phase 5: PATCHing a policy's priority to match another must succeed."""
    r1 = await async_client.post("/api/v1/policies", json={
        "name": "p1", "priority": 1,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    r2 = await async_client.post("/api/v1/policies", json={
        "name": "p2", "priority": 2,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    p2_id = r2.json()["id"]

    # Change p2's priority to 1 — now allowed (canary group with p1).
    response = await async_client.patch(f"/api/v1/policies/{p2_id}", json={"priority": 1})
    assert response.status_code == 200
    assert response.json()["priority"] == 1


@pytest.mark.asyncio
async def test_update_own_priority_no_conflict(async_client):
    """PATCHing a policy without changing priority must succeed."""
    r1 = await async_client.post("/api/v1/policies", json={
        "name": "p1", "priority": 1,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    p1_id = r1.json()["id"]

    # Update the fallback name — priority unchanged, must succeed.
    response = await async_client.patch(
        f"/api/v1/policies/{p1_id}",
        json={"fallback_service_name": "dummy-svc"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_inactive_policy_allows_same_priority(async_client):
    """An inactive policy must not block creation of an active policy with the same priority."""
    await async_client.post("/api/v1/policies", json={
        "name": "inactive-p", "priority": 1, "is_active": False,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    response = await async_client.post("/api/v1/policies", json={
        "name": "active-p", "priority": 1, "is_active": True,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    assert response.status_code == 201