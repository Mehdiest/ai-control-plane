"""JWT-based tenant identification dependency for rate limiting."""

import logging

from fastapi import Header

from app.core.config import get_settings

logger = logging.getLogger("control_plane.security")


async def get_tenant_id(
    authorization: str | None = Header(default=None),
) -> str:
    """Extract tenant_id from a Bearer JWT, falling back to 'anonymous'."""
    if not authorization or not authorization.startswith("Bearer "):
        return "anonymous"

    token = authorization.removeprefix("Bearer ").strip()

    try:
        from jose import jwt

        settings = get_settings()
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        tenant = payload.get("tenant_id", "anonymous")
        return str(tenant)
    except Exception as exc:
        logger.warning("JWT decode failed: %s — falling back to anonymous.", exc)
        return "anonymous"