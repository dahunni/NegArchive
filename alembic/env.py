"""Alembic environment.

One rule: the database comes from ``DATABASE_URL`` in the environment, never from
``alembic.ini`` (whose ``sqlalchemy.url`` is empty on purpose). If it is unset, this
fails loudly instead of migrating something unexpected.

    DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:5432/negarchive \
        alembic upgrade head

``app/main.py`` runs the same upgrade in process at startup.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app import models  # noqa: F401  (imported for the side effect above)

# Importing the models registers every table on Base.metadata, which is what
# `alembic revision --autogenerate` compares the database against.
from app.db import Base, database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# `database_url()` raises DatabaseNotConfigured with an explanation when unset.
config.set_main_option("sqlalchemy.url", database_url())


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (``alembic upgrade head --sql``)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations against a live connection."""
    connectable = config.attributes.get("connection", None)

    if connectable is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
