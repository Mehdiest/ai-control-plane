"""Pydantic schemas for the service registry API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models.service import LatencyZone, ServiceStatus


class ServiceCreate(BaseModel):
    """Payload for registering a new service with the control plane."""

    name: str = Field(..., min_length=1, max_length=120, examples=["bi-platform-copilot"])
    base_url: HttpUrl = Field(
        ..., examples=["https://enterprise-ai-bi-platform-production.up.railway.app"]
    )
    health_check_path: str = Field(default="/health", max_length=200)

    @field_validator("health_check_path")
    @classmethod
    def ensure_leading_slash(cls, v: str) -> str:
        """Prepend '/' if missing to prevent malformed URLs in the health checker."""
        return v if v.startswith("/") else f"/{v}"

    region: str = Field(
        default="default",
        max_length=80,
        examples=["eu-west", "us-east", "on-premise"],
    )
    latency_zone: LatencyZone = Field(default=LatencyZone.MEDIUM)
    network_tags: list[str] = Field(default_factory=list, examples=[["cloud", "railway"]])


class ServiceRead(BaseModel):
    """Public representation of a registered service."""

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
    region: str
    latency_zone: LatencyZone
    network_tags: list[str]
    created_at: datetime
    updated_at: datetime


class RegistrySummary(BaseModel):
    """Aggregate view of the whole registry."""

    total: int
    healthy: int
    degraded: int
    unhealthy: int
    unknown: int
    services: list[ServiceRead]