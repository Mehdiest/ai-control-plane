"""JWT-based tenant identification dependency for rate limiting.

Security posture (fail-closed):
  - No Authorization header → 'anonymous' (only if ALLOW_ANONYMOUS_ACCESS is
    True; otherwise 401).
  - Malformed or invalid Bearer token → 401, never falls back to anonymous.
"""

import logging

from fastapi import Header, HTTPException, status

from app.core.config import get_settings

logger = logging.getLogger("control_plane.security")


async def get_tenant_id(
    authorization: str | None = Header(default=None),
) -> str:
    """Extract tenant_id from a Bearer JWT.

    Fail-closed: an invalid or expired token always raises 401.  Anonymous
    access is permitted only when no Authorization header is present **and**
    ``ALLOW_ANONYMOUS_ACCESS`` is enabled in settings.
    """
    settings = get_settings()

    # --- No header at all → anonymous (if allowed) or 401 ---
    if not authorization:
        if settings.allow_anonymous_access:
            return "anonymous"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: provide a valid Bearer JWT.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Header present but not a Bearer token → 401 ---
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header: expected 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.removeprefix("Bearer ").strip()

    # --- Decode JWT; any failure → 401 (fail-closed) ---
    try:
        from jose import JWTError, jwt

        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        tenant = payload.get("sub")
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="JWT payload is missing the 'sub' claim.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return str(tenant)
    except HTTPException:
        raise
    except JWTError as exc:
        logger.warning("JWT decode failed: %s — rejecting with 401.", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired JWT token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as exc:
        logger.error("Unexpected error during JWT decode: %s — rejecting with 401.", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication error.",
            headers={"WWW-Authenticate": "Bearer"},
        )
