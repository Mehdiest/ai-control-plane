"""
Central application configuration.

All environment-driven settings live here so the rest of the codebase
never reads `os.environ` directly. This keeps configuration testable
and makes it obvious, at a glance, what the control plane depends on.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings, loaded from environment variables or a .env file."""

    # --- General ---
    app_name: str = "AI Control Plane"
    api_v1_prefix: str = "/api/v1"
    environment: str = "development"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/control_plane"

    # --- Health Checking ---
    health_check_interval_seconds: int = 15
    health_check_timeout_seconds: float = 5.0
    unhealthy_after_failures: int = 3

    # --- Security (used from Phase 3 onward, defined early for forward compatibility) ---
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so the .env file is parsed only once."""
    return Settings()
