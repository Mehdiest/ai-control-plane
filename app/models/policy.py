"""ORM model representing a routing policy."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Policy(Base):
    """A named, prioritised routing rule managed by the control plane."""

    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # Traffic share within a priority group (canary rollout).
    # weight=0 removes the policy from canary split — instant rollback.
    weight: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # --- Match conditions ---

    # Required: top-level request classifier (like an ACL match in a route-map).
    match_request_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Optional: restrict to services in a specific region (BGP community-style filter).
    match_region: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Optional: restrict to services in a specific latency class (OSPF cost-style).
    match_latency_zone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Optional: all listed tags must be present on the target service
    # (BGP extended community matching — every community must match).
    match_network_tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # --- Routing targets ---
    target_service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    fallback_service_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
