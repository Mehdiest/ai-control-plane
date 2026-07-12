"""Pydantic schemas for the observability dashboard API."""

from pydantic import BaseModel, Field


class ObserveSummary(BaseModel):
    """High-level snapshot returned by GET /observe/summary."""

    total_services: int
    healthy: int
    degraded: int
    unhealthy: int
    unknown: int
    active_policies: int
    requests_last_hour: int


class TrafficEntry(BaseModel):
    """One row in the traffic-distribution breakdown."""

    resolved_service: str
    resolution: str
    count: int


class ErrorStats(BaseModel):
    """One row in the error breakdown."""

    resolved_service: str
    resolution: str
    count: int


class LatencyStats(BaseModel):
    """Average latency for a single service."""

    resolved_service: str
    avg_latency_ms: float
    sample_count: int


class RequestLogRead(BaseModel):
    """Public representation of a stored request log entry."""

    id: str
    tenant_id: str
    request_type: str
    resolved_service: str
    resolution: str
    latency_ms: float | None
    created_at: str