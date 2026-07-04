"""
Pydantic schemas for the service registry API.

Kept separate from the ORM model so the API contract can evolve
independently of the database schema.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models.service import ServiceStatus


class ServiceCreate(BaseModel):
    """Payload for registering a new service with the control plane."""

    name: str = Field(..., min_length=1, max_length=120, examples=["bi-platform-copilot"])
    base_url: HttpUrl = Field(..., examples=["https://enterprise-ai-bi-platform-production.up.railway.app"])
    health_check_path: str = Field(default="/health", max_length=200)


class ServiceRead(BaseModel):
    """Public representation of a registered service, including live health data."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    base_url: str
    health_check_path: str
    status: ServiceStatus
    consecutive_failures: int
    last_latency_ms: float | None
    last_checked_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class RegistrySummary(BaseModel):
    """Aggregate view of the whole registry, useful for a dashboard's landing view."""

    total: int
    healthy: int
    degraded: int
    unhealthy: int
    unknown: int
    services: list[ServiceRead]
