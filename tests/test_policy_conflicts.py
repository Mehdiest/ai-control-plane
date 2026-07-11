"""
Unit tests for policy conflict validation.

Verifies that both create and update operations enforce the rule:
no two active policies for the same request type may share the same
priority value.
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
# Create conflict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_conflict_raises_409(async_client):
    """Creating two active policies with the same request type and priority must return 409."""
    await async_client.post("/api/v1/policies", json={
        "name": "p1", "priority": 1,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    response = await async_client.post("/api/v1/policies", json={
        "name": "p2", "priority": 1,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    assert response.status_code == 409
    assert "priority" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Update conflict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_priority_conflict_raises_409(async_client):
    """PATCHing a policy's priority to collide with an existing policy must return 409."""
    r1 = await async_client.post("/api/v1/policies", json={
        "name": "p1", "priority": 1,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    r2 = await async_client.post("/api/v1/policies", json={
        "name": "p2", "priority": 2,
        "match_request_type": "analytics", "target_service_name": "dummy-svc",
    })
    p2_id = r2.json()["id"]

    # Try to change p2's priority to 1 — should collide with p1.
    response = await async_client.patch(f"/api/v1/policies/{p2_id}", json={"priority": 1})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_update_own_priority_no_conflict(async_client):
    """PATCHing a policy without changing priority must not raise a false conflict."""
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
