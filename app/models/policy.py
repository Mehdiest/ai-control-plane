"""
ORM model representing a routing policy.

A policy defines which service should handle a given request type,
and what to fall back to if the primary target is unavailable.

Phase 2 introduced basic priority-based routing. This update adds
network-aware match conditions — region and latency zone constraints
that the engine evaluates alongside request type, mirroring how a
route-map in traditional networking can match on both ACL and
community attributes before applying a routing action.

Evaluation order:
  1. match_request_type  (required — like an ACL match)
  2. match_region        (optional — like a BGP community filter)
  3. match_latency_zone  (optional — like an OSPF cost preference)
  4. priority            (tiebreaker when multiple policies match)
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Policy(Base):
    """A named, prioritised routing rule managed by the control plane."""

    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Human-readable identifier, unique across all policies.
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)

    # Lower number = evaluated first (like sequence numbers in a route-map).
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # --- Match conditions ---

    # Primary match: the logical request category (e.g. "analytics", "copilot").
    # Always required — acts as the top-level classifier before network
    # constraints are applied.
    match_request_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Optional network match: restrict this policy to services in a specific
    # region (e.g. "eu-west", "on-premise"). When set, the engine will only
    # route to target services whose `region` field matches this value —
    # useful for data-residency enforcement.
    match_region: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Optional network match: restrict this policy to services within a
    # specific latency classification. When set, the engine skips any target
    # whose `latency_zone` does not match — useful for latency-sensitive
    # workloads that should never be routed to high-latency cold-start services.
    match_latency_zone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- Routing targets ---
    # Both reference the `name` column of the services table rather than
    # the UUID so policies remain human-readable in plain SQL.
    target_service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    fallback_service_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Disabled policies are stored but skipped during routing evaluation,
    # allowing safe rollback without deletion.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
