from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from brokeberg.config import get_settings
from brokeberg.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Single source for the URL: DATABASE_URL via brokeberg.config, never alembic.ini.
DATABASE_URL = get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DB connection."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # A plain engine (not brokeberg.db.get_engine): pgvector registration needs the
    # `vector` extension, which the baseline migration is what creates.
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
