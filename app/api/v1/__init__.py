"""Aggregates all v1 API routers into a single APIRouter."""

from fastapi import APIRouter

from app.api.v1.observe import router as observe_router
from app.api.v1.policies import router as policies_router
from app.api.v1.quotas import router as quotas_router
from app.api.v1.registry import router as registry_router

api_router = APIRouter()
api_router.include_router(registry_router)
api_router.include_router(policies_router)
api_router.include_router(quotas_router)
api_router.include_router(observe_router)
