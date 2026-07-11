"""
Alembic migration environment.

Wired to the project's own ``Base.metadata`` and reads the database URL
from the application settings (``.env``) rather than ``alembic.ini``.
The async URL (``postgresql+asyncpg://``) is converted to a sync URL
for Alembic's synchronous migration engine.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# --- Project imports -------------------------------------------------------
from app.core.config import get_settings
from app.core.database import Base

# Import models so their tables are registered on Base.metadata.
import app.models.policy  # noqa: F401
import app.models.quota   # noqa: F401
import app.models.service  # noqa: F401

# --- Alembic config --------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Inject the database URL from application settings. Alembic uses a
# synchronous engine, so convert the async driver to its sync counterpart.
_settings = get_settings()
_sync_url = _settings.database_url.replace("+asyncpg", "+psycopg2")
config.set_main_option("sqlalchemy.url", _sync_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with a real DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()