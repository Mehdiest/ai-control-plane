"""Pydantic schemas for routing policies and the route-resolution API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.service import LatencyZone


class PolicyCreate(BaseModel):
    """Payload for creating a new routing policy."""

    name: str = Field(..., min_length=1, max_length=120, examples=["prefer-eu-gpu"])
    priority: int = Field(default=100, ge=1, le=9999, examples=[1])
    weight: int = Field(
        default=100, ge=0, le=1000, examples=[95],
        description="Traffic share within a priority group. weight=0 = instant rollback.",
    )
    match_request_type: str = Field(..., min_length=1, max_length=100, examples=["analytics"])
    match_region: str | None = Field(
        default=None, max_length=80, examples=["eu-west"],
        description="Only services in this region are eligible.",
    )
    match_latency_zone: LatencyZone | None = Field(
        default=None,
        description="Only services in this latency zone are eligible.",
    )
    match_network_tags: list[str] = Field(
        default_factory=list,
        examples=[["gpu", "eu"]],
        description="All listed tags must be present on the target service. Empty = no constraint.",
    )
    target_service_name: str = Field(..., min_length=1, max_length=120, examples=["bi-platform-copilot"])
    fallback_service_name: str | None = Field(default=None, examples=["local-llm"])
    is_active: bool = Field(default=True)


class PolicyUpdate(BaseModel):
    """Partial update payload — all fields optional."""

    priority: int | None = Field(default=None, ge=1, le=9999)
    weight: int | None = Field(default=None, ge=0, le=1000)
    match_request_type: str | None = Field(default=None, min_length=1, max_length=100)
    match_region: str | None = None
    match_latency_zone: LatencyZone | None = None
    match_network_tags: list[str] | None = None
    target_service_name: str | None = Field(default=None, min_length=1, max_length=120)
    fallback_service_name: str | None = None
    is_active: bool | None = None


class PolicyWeightUpdate(BaseModel):
    """Lightweight payload for the canary weight-adjustment endpoint."""

    weight: int = Field(..., ge=0, le=1000, examples=[10])


class PolicyRead(BaseModel):
    """Public representation of a stored policy."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    priority: int
    weight: int
    match_request_type: str
    match_region: str | None
    match_latency_zone: str | None
    match_network_tags: list[str]
    target_service_name: str
    fallback_service_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RouteRequest(BaseModel):
    """Caller payload for resolving which service should handle a request."""

    request_type: str = Field(
        ..., min_length=1, max_length=100, examples=["analytics"],
        description="Logical category of the request.",
    )


class RouteResult(BaseModel):
    """Resolution outcome returned by the policy engine."""

    request_type: str
    resolved_service: str
    resolution: str = Field(
        description="One of: 'primary' | 'fallback' | 'no_policy' | 'no_healthy_service'"
    )
    policy_name: str | None = Field(default=None)
    policy_weight: int | None = Field(default=None)
    resolved_region: str | None = Field(default=None)
    resolved_latency_zone: str | None = Field(default=None)
    resolved_network_tags: list[str] = Field(default_factory=list)
    message: str
