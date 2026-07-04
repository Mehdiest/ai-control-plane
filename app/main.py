"""
AI Control Plane — application entrypoint.

Phase 1 scope: service registry + background health checking.
Downstream services (e.g. the Enterprise AI BI Platform's Copilot
endpoint) register themselves here and are polled on an interval,
the same way a router tracks neighbor reachability.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.database import init_db
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
    description="A lightweight control plane for registering, health-checking, "
    "and (in later phases) routing traffic across AI services.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness endpoint for the control plane itself (not the services it manages)."""
    return {"status": "ok", "service": settings.app_name}
