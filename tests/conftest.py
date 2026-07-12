"""Shared pytest fixtures for the AI Control Plane test suite."""

import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import text

# Point to SQLite before any app module is imported so the engine is
# created with the right URL from the start.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RATE_LIMIT_ENABLED", "true")

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

import app.models.policy   # noqa: F401, E402 — registers Policy table with Base.metadata
import app.models.quota    # noqa: F401, E402 — registers Quota table with Base.metadata
import app.models.request_log  # noqa: F401, E402 — registers RequestLog table with Base.metadata
import app.models.service  # noqa: F401, E402 — registers Service table with Base.metadata

from app.core.database import AsyncSessionLocal, init_db  # noqa: E402
from app.core.redis import set_redis_client  # noqa: E402
from app.models.service import LatencyZone, Service, ServiceStatus  # noqa: E402
from app.models.policy import Policy  # noqa: E402
from app.models.quota import Quota  # noqa: E402
from app.models.request_log import RequestLog  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_database():
    """Re-create all tables before each test so tests are fully isolated."""
    await init_db()
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM request_logs"))
        await session.execute(text("DELETE FROM quotas"))
        await session.execute(text("DELETE FROM policies"))
        await session.execute(text("DELETE FROM services"))
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def fake_redis():
    """Inject a FakeRedis client so tests need no real Redis server."""
    from fakeredis import aioredis as fake_aioredis

    client = fake_aioredis.FakeRedis(decode_responses=True)
    set_redis_client(client)
    yield client
    await client.aclose()
    set_redis_client(None)  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def db_session():
    """Yield a live async session for direct database interaction in tests."""
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def healthy_service(db_session) -> Service:
    """A registered, healthy EU-west service available for routing tests."""
    svc = Service(
        name="bi-platform-eu",
        base_url="https://enterprise-ai-bi-platform-production.up.railway.app",
        health_check_path="/docs",
        status=ServiceStatus.HEALTHY,
        region="eu-west",
        latency_zone=LatencyZone.HIGH,
        network_tags=["cloud", "railway", "eu"],
    )
    db_session.add(svc)
    await db_session.commit()
    await db_session.refresh(svc)
    return svc


@pytest_asyncio.fixture
async def local_service(db_session) -> Service:
    """A registered, healthy on-premise low-latency service."""
    svc = Service(
        name="local-llm",
        base_url="http://localhost:11434",
        health_check_path="/health",
        status=ServiceStatus.HEALTHY,
        region="on-premise",
        latency_zone=LatencyZone.LOW,
        network_tags=["on-premise", "air-gapped", "gpu"],
    )
    db_session.add(svc)
    await db_session.commit()
    await db_session.refresh(svc)
    return svc


# ---------------------------------------------------------------------------
# HTTP client fixture (used by conflict tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def async_client():
    """Yield an async HTTP test client wired to the FastAPI app."""
    from httpx import AsyncClient, ASGITransport

    # Seed a dummy service so policy conflict tests can reference it.
    async with AsyncSessionLocal() as db:
        from app.models.service import Service, ServiceStatus
        svc = Service(
            name="dummy-svc",
            base_url="http://example.com",
            health_check_path="/health",
            status=ServiceStatus.HEALTHY,
        )
        db.add(svc)
        await db.commit()

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client