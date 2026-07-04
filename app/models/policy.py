"""
ORM model representing a routing policy.

A policy defines which service should handle a given request type,
and what to fall back to if the primary target is unavailable —
mirroring the role of a route-map with a fallback static route
in traditional network policy-based routing.

Policies are prioritised: the engine evaluates them in ascending
priority order and applies the first match, the same way an ACL
or route-map processes clauses top-to-bottom.
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

    # Match condition: the logical request category this policy applies to
    # (e.g. "analytics", "copilot", "default"). The router compares this
    # against the `request_type` field supplied by the caller.
    match_request_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Routing targets — both reference the `name` column of the services table
    # rather than the UUID so policies remain readable in plain SQL.
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
