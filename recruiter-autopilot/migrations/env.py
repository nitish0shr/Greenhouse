"""Alembic migration environment configuration."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all models to register them with Base.metadata
from src.models.base import Base
from src.models import (  # noqa: F401
    Application,
    ApplicationState,
    ApplicationStateTransition,
    AuditLog,
    CalendarEvent,
    CalendarEventMapping,
    Candidate,
    EmailLog,
    EmailTemplate,
    ExceptionQueueItem,
    Job,
    JobStageConfig,
    KillSwitch,
    Rubric,
    RubricVersion,
    ScoringResult,
    SLAConfig,
    SLAViolation,
    WebhookEvent,
)

# Load settings
from src.config import settings

# this is the Alembic Config object
config = context.config

# Override sqlalchemy.url from settings
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model's MetaData object for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
