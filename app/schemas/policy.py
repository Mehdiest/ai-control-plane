"""
Pydantic schemas for routing policies and the route-resolution API.

Kept deliberately separate from the ORM model so the API contract
can evolve independently of the persistence layer.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PolicyCreate(BaseModel):
    """Payload for creating a new routing policy."""

    name: str = Field(..., min_length=1, max_length=120, examples=["prefer-bi-platform"])
    priority: int = Field(default=100, ge=1, le=9999, examples=[1])
    match_request_type: str = Field(
        ..., min_length=1, max_length=100, examples=["analytics"]
    )
    target_service_name: str = Field(..., min_length=1, max_length=120, examples=["bi-platform-copilot"])
    fallback_service_name: str | None = Field(default=None, examples=["mock-service"])
    is_active: bool = Field(default=True)


class PolicyUpdate(BaseModel):
    """Partial update payload — all fields are optional."""

    priority: int | None = Field(default=None, ge=1, le=9999)
    match_request_type: str | None = Field(default=None, min_length=1, max_length=100)
    target_service_name: str | None = Field(default=None, min_length=1, max_length=120)
    fallback_service_name: str | None = None
    is_active: bool | None = None


class PolicyRead(BaseModel):
    """Public representation of a stored policy."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    priority: int
    match_request_type: str
    target_service_name: str
    fallback_service_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RouteRequest(BaseModel):
    """Caller payload for resolving which service should handle a request."""

    request_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        examples=["analytics"],
        description="Logical category of the request (must match a policy's match_request_type).",
    )


class RouteResult(BaseModel):
    """Resolution outcome returned by the policy engine."""

    request_type: str
    resolved_service: str
    resolution: str = Field(
        description="One of: 'primary' | 'fallback' | 'no_policy' | 'no_healthy_service'"
    )
    policy_name: str | None = Field(
        default=None, description="Name of the policy that was matched, if any."
    )
    message: str
