"""
AI Control Plane — application entrypoint.

Phase 2 scope: policy-based routing engine on top of Phase 1's
service registry and health checking. The policy engine evaluates
routing rules in priority order and selects the healthiest available
target — mirroring route-map / policy-based routing in traditional
network infrastructure.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.database import init_db
from app.models import policy as _policy_model  # noqa: F401 — registers table with Base.metadata
from app.models import service as _service_model  # noqa: F401 — registers table with Base.metadata
from app.services.health_checker import create_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("control_plane")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database and start the health-check scheduler on startup."""
    await init_db()

    scheduler = create_scheduler()
    scheduler.start()
    logger.info(
        "Health check scheduler started (interval=%ds).",
        settings.health_check_interval_seconds,
    )

    yield

    scheduler.shutdown(wait=False)
    logger.info("Health check scheduler stopped.")


app = FastAPI(
    title=settings.app_name,
    description=(
        "A lightweight control plane for AI services — service registry, "
        "background health checking, and policy-based routing."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness endpoint for the control plane itself (not the services it manages)."""
    return {"status": "ok", "service": settings.app_name}
