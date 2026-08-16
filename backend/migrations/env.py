import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add the app directory to the path so we can import models
# In Docker: models are at /app/models.py, migrations at /alembic/migrations/
# Locally: models are at backend/app/models.py, migrations at backend/migrations/
if os.path.exists('/app/models.py'):
    sys.path.insert(0, '/app')
else:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

# Import all models so they're registered with SQLModel metadata.
# F401: unused by design -- importing them is the whole point, it is what
# populates SQLModel.metadata for alembic autogenerate.
from sqlmodel import SQLModel

from config import settings
from models import (  # noqa: F401
    DownloadJob,
    MediaAccess,
    MediaDetails,
    Subscription,
    TaskRecord,
    TranscriptBlock,
    User,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Get the database URL from the centralized config module
# This ensures Alembic uses the same config.yml as the rest of the app
# Use psycopg (v3) driver - convert postgresql:// to postgresql+psycopg://
database_url = settings.database.url
if database_url.startswith('postgresql://'):
    database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
config.set_main_option('sqlalchemy.url', database_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use SQLModel's metadata for autogenerate support
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option('sqlalchemy.url')
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # One transaction per revision, not one for the whole run. Postgres refuses
            # to reference an enum value added in the same transaction, so a revision
            # that adds one and a later revision that uses it can only both apply in a
            # single `upgrade head` if the first one commits first.
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
