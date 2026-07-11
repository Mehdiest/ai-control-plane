"""
ORM model representing a service registered with the control plane.

A "service" is any downstream AI workload the control plane governs —
an LLM provider, an internal agent, or an external API such as the
Enterprise AI BI Platform's Copilot endpoint.

Each service carries network topology metadata (region, latency zone,
and free-form tags) so the policy engine can make routing decisions
that mirror topology-aware routing in traditional networks — the same
way OSPF uses link cost or BGP uses community tags to prefer certain
paths over others.

Storage note: `network_tags` uses JSON rather than a native ARRAY so
the model remains portable across both PostgreSQL (production) and
SQLite (local testing) without dialect-specific type overrides.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ServiceStatus(str, enum.Enum):
    """Lifecycle status of a registered service, mirroring how a router treats a neighbor."""

    UNKNOWN = "unknown"      # registered but not yet health-checked
    HEALTHY = "healthy"      # last check succeeded
    DEGRADED = "degraded"    # some recent failures, still usable
    UNHEALTHY = "unhealthy"  # exceeded failure threshold, excluded from routing


class LatencyZone(str, enum.Enum):
    """Relative latency classification for a service's hosting environment.

    Mirrors the concept of OSPF link cost — a lower-cost (lower-latency)
    path is preferred when the policy allows it.
    """

    LOW = "low"        # on-premise or same-region deployment
    MEDIUM = "medium"  # nearby cloud region
    HIGH = "high"      # cross-region or cold-start cloud (e.g. Railway free tier)


class Service(Base):
    """A downstream AI service tracked by the control plane."""

    __tablename__ = "services"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    health_check_path: Mapped[str] = mapped_column(String(200), default="/health", nullable=False)

    # --- Health state ---
    status: Mapped[ServiceStatus] = mapped_column(
        Enum(ServiceStatus), default=ServiceStatus.UNKNOWN, nullable=False
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # --- Network topology metadata ---

    # `region` identifies where the service is physically or logically hosted
    # (e.g. "eu-west", "us-east", "on-premise"). Used by the policy engine
    # to enforce data-residency or locality constraints — analogous to BGP
    # communities that restrict route advertisement to certain ASes.
    region: Mapped[str] = mapped_column(
        String(80), default="default", nullable=False, index=True
    )

    # `latency_zone` is a human-assigned classification of the expected
    # round-trip latency from the control plane to this service.
    # The engine prefers lower-latency services when multiple candidates
    # are eligible, mirroring OSPF's preference for lower link-cost paths.
    latency_zone: Mapped[LatencyZone] = mapped_column(
        Enum(LatencyZone), default=LatencyZone.MEDIUM, nullable=False
    )

    # `network_tags` is a free-form label set for routing constraints that
    # don't fit region or latency — e.g. ["on-premise", "air-gapped", "gpu"].
    # Policies can require specific tags to be present before routing,
    # similar to BGP community matching in route filtering.
    # Stored as JSON for cross-database portability.
    network_tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
