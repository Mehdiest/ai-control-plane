"""
Unit tests for the health-checker engine.

Validates status transitions (healthy → degraded → unhealthy) and
failure counter behaviour without making any real network calls —
httpx is patched with a lightweight mock.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.database import AsyncSessionLocal
from app.models.service import Service, ServiceStatus
from app.services.health_checker import _record_failure, run_health_check_cycle
from sqlalchemy import select


# ---------------------------------------------------------------------------
# _record_failure unit tests (pure logic, no I/O)
# ---------------------------------------------------------------------------

def _make_service(failures: int = 0) -> Service:
    """Build a detached Service instance suitable for testing _record_failure."""
    svc = Service(
        name="test-svc",
        base_url="http://example.com",
        health_check_path="/health",
        status=ServiceStatus.HEALTHY,
        consecutive_failures=failures,
    )
    return svc


def test_first_failure_sets_degraded():
    """A single failure should set status to DEGRADED, not UNHEALTHY."""
    svc = _make_service(failures=0)
    _record_failure(svc, "HTTP 503")
    assert svc.status == ServiceStatus.DEGRADED
    assert svc.consecutive_failures == 1
    assert svc.last_error == "HTTP 503"


def test_failure_at_threshold_sets_unhealthy():
    """Reaching the configured threshold (default 3) must flip status to UNHEALTHY."""
    from app.core.config import get_settings
    threshold = get_settings().unhealthy_after_failures

    svc = _make_service(failures=threshold - 1)
    _record_failure(svc, "connection refused")
    assert svc.status == ServiceStatus.UNHEALTHY
    assert svc.consecutive_failures == threshold


def test_error_message_is_truncated_at_1000_chars():
    """Error messages longer than 1000 characters must be truncated before storage."""
    svc = _make_service()
    _record_failure(svc, "x" * 2000)
    assert len(svc.last_error) == 1000


# ---------------------------------------------------------------------------
# health_check_path normalisation (schema validator)
# ---------------------------------------------------------------------------

def test_health_check_path_gets_leading_slash():
    """ServiceCreate must prepend '/' to paths that omit it."""
    from app.schemas.service import ServiceCreate
    svc = ServiceCreate(
        name="test",
        base_url="http://example.com",
        health_check_path="health",   # missing leading slash
    )
    assert svc.health_check_path == "/health"


def test_health_check_path_with_slash_unchanged():
    """Paths that already start with '/' must not be modified."""
    from app.schemas.service import ServiceCreate
    svc = ServiceCreate(
        name="test",
        base_url="http://example.com",
        health_check_path="/health",
    )
    assert svc.health_check_path == "/health"


# ---------------------------------------------------------------------------
# run_health_check_cycle integration (mocked HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_healthy_response_clears_failures():
    """A successful HTTP response must reset consecutive_failures and set HEALTHY."""
    async with AsyncSessionLocal() as db:
        svc = Service(
            name="mock-svc",
            base_url="http://mock.example.com",
            health_check_path="/health",
            status=ServiceStatus.DEGRADED,
            consecutive_failures=2,
        )
        db.add(svc)
        await db.commit()

    mock_response = MagicMock()
    mock_response.is_success = True

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("app.services.health_checker.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await run_health_check_cycle()

    async with AsyncSessionLocal() as db:
        result = await db.scalar(select(Service).where(Service.name == "mock-svc"))
        assert result.status == ServiceStatus.HEALTHY
        assert result.consecutive_failures == 0
        assert result.last_error is None


@pytest.mark.asyncio
async def test_failed_response_increments_failures():
    """A non-success HTTP response must increment consecutive_failures."""
    async with AsyncSessionLocal() as db:
        svc = Service(
            name="failing-svc",
            base_url="http://mock.example.com",
            health_check_path="/health",
            status=ServiceStatus.HEALTHY,
            consecutive_failures=0,
        )
        db.add(svc)
        await db.commit()

    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 503

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("app.services.health_checker.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await run_health_check_cycle()

    async with AsyncSessionLocal() as db:
        result = await db.scalar(select(Service).where(Service.name == "failing-svc"))
        assert result.consecutive_failures == 1
        assert result.status == ServiceStatus.DEGRADED
