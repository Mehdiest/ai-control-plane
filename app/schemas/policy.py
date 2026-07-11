"""
Pydantic schemas for routing policies and the route-resolution API.

Kept separate from the ORM model so the API contract can evolve
independently of the persistence layer.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.service import LatencyZone


class PolicyCreate(BaseModel):
    """Payload for creating a new routing policy."""

    name: str = Field(..., min_length=1, max_length=120, examples=["prefer-eu-low-latency"])
    priority: int = Field(default=100, ge=1, le=9999, examples=[1])
    match_request_type: str = Field(
        ..., min_length=1, max_length=100, examples=["analytics"]
    )

    # Optional network match conditions.
    match_region: str | None = Field(
        default=None,
        max_length=80,
        examples=["eu-west"],
        description="When set, only services in this region are eligible as routing targets.",
    )
    match_latency_zone: LatencyZone | None = Field(
        default=None,
        description="When set, only services in this latency zone are eligible as routing targets.",
    )

    target_service_name: str = Field(
        ..., min_length=1, max_length=120, examples=["bi-platform-copilot"]
    )
    fallback_service_name: str | None = Field(default=None, examples=["local-llm"])
    is_active: bool = Field(default=True)


class PolicyUpdate(BaseModel):
    """Partial update payload — all fields optional."""

    priority: int | None = Field(default=None, ge=1, le=9999)
    match_request_type: str | None = Field(default=None, min_length=1, max_length=100)
    match_region: str | None = None
    match_latency_zone: LatencyZone | None = None
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
    match_region: str | None
    match_latency_zone: str | None
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
        default=None, description="Name of the matched policy, if any."
    )
    resolved_region: str | None = Field(
        default=None, description="Region of the resolved service."
    )
    resolved_latency_zone: str | None = Field(
        default=None, description="Latency zone of the resolved service."
    )
    resolved_network_tags: list[str] = Field(
        default_factory=list,
        description="Network tags of the resolved service.",
    )
    message: str
