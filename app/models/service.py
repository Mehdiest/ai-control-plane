"""
ORM model representing a service registered with the control plane.

A "service" is any downstream AI workload the control plane governs —
an LLM provider, an internal agent, or an external API such as the
Enterprise AI BI Platform's Copilot endpoint. Phase 1 only tracks
identity and health; routing metadata is added in Phase 2.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ServiceStatus(str, enum.Enum):
    """Lifecycle status of a registered service, mirroring how a router treats a neighbor."""

    UNKNOWN = "unknown"       # registered but not yet health-checked
    HEALTHY = "healthy"       # last check succeeded
    DEGRADED = "degraded"     # some recent failures, still usable
    UNHEALTHY = "unhealthy"   # exceeded failure threshold, excluded from routing


class Service(Base):
    """A downstream AI service tracked by the control plane."""

    __tablename__ = "services"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    health_check_path: Mapped[str] = mapped_column(String(200), default="/health", nullable=False)

    status: Mapped[ServiceStatus] = mapped_column(
        Enum(ServiceStatus), default=ServiceStatus.UNKNOWN, nullable=False
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
