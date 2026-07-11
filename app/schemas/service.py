"""
Pydantic schemas for the service registry API.

Kept separate from the ORM model so the API contract can evolve
independently of the database schema.
"""

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
        """Guarantee the path starts with '/' so URL construction in the health
        checker is always safe.

        Without this, a value like 'health' would produce a malformed URL
        (e.g. 'https://example.comhealth') instead of the intended
        'https://example.com/health'.
        """
        return v if v.startswith("/") else f"/{v}"

    # Network topology metadata — optional at registration time.
    region: str = Field(
        default="default",
        max_length=80,
        examples=["eu-west", "us-east", "on-premise"],
        description="Logical or physical region where the service is hosted. "
                    "Used by network-aware routing policies for data-residency enforcement.",
    )
    latency_zone: LatencyZone = Field(
        default=LatencyZone.MEDIUM,
        description="Expected round-trip latency classification. "
                    "The engine prefers lower-latency services when multiple candidates qualify.",
    )
    network_tags: list[str] = Field(
        default_factory=list,
        examples=[["cloud", "railway", "eu"]],
        description="Free-form labels for routing constraints "
                    "(e.g. 'on-premise', 'air-gapped', 'gpu'). "
                    "Policies can require all specified tags to be present before routing.",
    )


class ServiceRead(BaseModel):
    """Public representation of a registered service, including live health and network data."""

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

    # Network topology fields
    region: str
    latency_zone: LatencyZone
    network_tags: list[str]

    created_at: datetime
    updated_at: datetime


class RegistrySummary(BaseModel):
    """Aggregate view of the whole registry, useful for a dashboard landing view."""

    total: int
    healthy: int
    degraded: int
    unhealthy: int
    unknown: int
    services: list[ServiceRead]
