"""Pydantic schemas for the quota management API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class QuotaCreate(BaseModel):
    """Payload for creating a quota for a tenant."""

    tenant_id: str = Field(..., min_length=1, max_length=120, examples=["acme-corp"])
    max_requests: int = Field(..., ge=1, examples=[100])
    window_seconds: int = Field(..., ge=1, examples=[60])
    is_active: bool = Field(default=True)


class QuotaUpdate(BaseModel):
    """Partial update payload — all fields optional."""

    max_requests: int | None = Field(default=None, ge=1)
    window_seconds: int | None = Field(default=None, ge=1)
    is_active: bool | None = None


class QuotaRead(BaseModel):
    """Public representation of a stored quota."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: str
    max_requests: int
    window_seconds: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class QuotaStatus(BaseModel):
    """Quota with current consumption — returned by GET /quotas/{tenant_id}."""

    tenant_id: str
    max_requests: int
    window_seconds: int
    is_active: bool
    current_count: int = Field(description="Requests consumed in the current window.")
    remaining: int = Field(description="Requests remaining before the limit is hit.")
    window_reset_seconds: int | None = Field(
        default=None,
        description="Seconds until the current window expires (None if no active counter).",
    )