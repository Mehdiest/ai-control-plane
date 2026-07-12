"""ORM model for the request-log table used by the observability dashboard."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RequestLog(Base):
    """A single /route resolution recorded for observability analytics."""

    __tablename__ = "request_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    request_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resolved_service: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resolution: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # Phase 5 — canary observability: which policy handled the request and
    # its weight at resolution time, so the traffic dashboard can show the
    # canary split alongside the resolved service.
    policy_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    policy_weight: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )